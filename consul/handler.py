#!/usr/bin/python3
# coding: utf-8
import hashlib
import json
import logging
import re
import requests
import socket
import time
import yaml
from base64 import b64decode
from contextlib import contextmanager
from datetime import datetime
from os.path import basename, join, exists
from subprocess import run as srun, CalledProcessError, PIPE
from sys import stdin, argv
from urllib.parse import urlparse
DEPLOY = '/deploy'
log = logging.getLogger()


def _run(cmd, cwd=None):
    try:
        if cwd:
            cmd = 'cd "{}" && {}'.format(cwd, cmd)
        log.info(cmd)
        res = srun(cmd, shell=True, check=True, stdout=PIPE, stderr=PIPE)
        return res.stdout.decode().strip()
    except CalledProcessError as e:
        log.error("Failed to run %s: %s", e.cmd, e.stderr.decode())
        raise


class Application(object):
    def __init__(self, repo_url, branch, cwd=None):
        self.repo_url, self.branch = repo_url.strip(), branch.strip()
        if self.repo_url.endswith('.git'):
            self.repo_url = self.repo_url[:-4]
        md5 = hashlib.md5(urlparse(self.repo_url.lower()).path.encode('utf-8')
                          ).hexdigest()
        repo_name = basename(self.repo_url.strip('/'))
        self.name = repo_name + ('_' + self.branch if self.branch else ''
                                 ) + '.' + md5
        self.path = join(DEPLOY, self.name)  # path of the checkout
        self._services = None
        self._volumes = None
        self._compose = None

    def check(self):
        """consistency check"""
        sites = {s['key']: json.loads(b64decode(s['value']).decode('utf-8'))
                 for s in json.loads(self.do('consul kv export site/'))}
        # check urls are not already used
        for service in self.services:
            urls = [self.url(service)] + self.redirect_from(service)
            for site in sites.values():
                if site.get('name') == self.name:
                    continue
                for url in urls:
                    if (url in site.get('redirect_from', [])
                            or url == site.get('url')):
                        msg = ('Aborting! Site {} is already deployed by {}'
                               .format(url, site['name']))
                        log.error(msg)
                        raise ValueError(msg)

    def do(self, cmd, cwd=None):
        return _run(cmd, cwd=cwd)

    @property
    def compose(self):
        """read the compose file
        """
        if self._compose is None:
            try:
                with open(join(self.path, 'docker-compose.yml')) as c:
                    self._compose = yaml.load(c.read())
            except:
                log.error('Could not read docker-compose.yml')
                raise EnvironmentError('Could not read docker-compose.yml')
        return self._compose

    @contextmanager
    def notify_transfer(self):
        try:
            yield
            self.do('consul kv put transfer/{}/success'.format(self.name))
        except:
            log.error('Volume transfer FAILED!')
            self.do('consul kv put transfer/{}/failure'.format(self.name))
            self.up()  # TODO move in the deploy
            raise
        log.info('Volume transfer SUCCEEDED!')

    def wait_notification(self):
        loops = 0
        while loops < 60:
            log.info('Waiting transfer notification for %s', self.name)
            res = self.do('consul kv get -keys transfer/{}'.format(self.name))
            if res:
                status = res.split('/')[-1]
                self.do('consul kv delete -recurse transfer/{}/'
                        .format(self.name))
                log.info('Transfer notification status: %s', status)
                return status
            time.sleep(1)
            loops += 1
        msg = ('Waited too much :( Master did not send a notification for %s')
        log.info(msg, self.name)
        raise RuntimeError(msg % self.name)

    @property
    def services(self):
        """name of the services in the compose file
        """
        if self._services is None:
            self._services = self.compose['services'].keys()
        return self._services

    @property
    def project(self):
        return re.sub(r'[^a-z0-9]', '', self.name.rsplit('.', 1)[0])

    @property
    def volumes(self):
        """btrfs volumes defined in the compose,
        or in the kv if no compose available
        """
        if self._volumes is None:
            try:
                self._volumes = [
                    Volume(self.project + '_' + v[0])
                    for v in self.compose.get('volumes', {}).items()
                    if v[1] and v[1].get('driver') == 'btrfs']
            except:
                log.info("No compose available,"
                         "reading volumes from the kv store")
                try:
                    self._volumes = [
                        Volume(v) for v in self.valueof(self.name, 'volumes')]
                except:
                    log.info("No volumes found in the kv store")
                    self._volumes = []
            self._volumes = self._volumes or None
        return self._volumes

    def container_name(self, service):
        """did'nt find a way to query reliably so do it static
        It assumes there is only 1 container for a project/service couple
        """
        return self.project + '_' + service + '_1'

    def valueof(self, name, key):
        """ return the current value of the key in the kv"""
        cmd = 'consul kv get site/{}'.format(name)
        return json.loads(self.do(cmd))[key]

    def compose_domain(self):
        """domain name of the first exposed service in the compose"""
        # FIXME prevents from exposing two domains in a compose
        domains = [self.domain(s) for s in self.services]
        domains = [d for d in domains if d is not None]
        return domains[0] if domains else ''

    @property
    def slave_node(self):
        """slave node for the current app """
        try:
            return self.valueof(self.name, 'slave')
        except:
            log.warn('Could not determine the slave node for %s', self.name)
            return None

    @property
    def master_node(self):
        """master node for the current app """
        try:
            return self.valueof(self.name, 'node')
        except:
            log.warn('Could not determine the master node for %s', self.name)
            return None

    def shelve(self):
        """move the checkout to a temporary location"""
        oldpath = self.path
        DTFORMAT = "%Y-%m-%dT%H:%M:%S.%f"
        newpath = oldpath + '@' + datetime.now().strftime(DTFORMAT)
        self.do("mv {} {}".format(oldpath, newpath))
        self.path = newpath
        log.info('Successfully shelved %s', newpath)

    def unshelve(self):
        """restore the shelved checkout"""
        oldpath = self.path
        DTFORMAT = "%Y-%m-%dT%H:%M:%S.%f"
        try:
            newpath = oldpath.rsplit('@', 1)[0]
            time.strptime(oldpath.split('@')[-1], DTFORMAT)  # check
        except:
            log.error('Could not unshelve %s', oldpath)
            return
        self.do("mv {} {}".format(oldpath, newpath))
        self.path = newpath
        log.info('Successfully unshelved %s', oldpath)

    def clean(self):
        self.do('rm -rf "{}"'.format(self.path))

    def fetch(self, retrying=False):
        try:
            if exists(self.path):
                self.clean()
            self.do('git clone --depth 1 {} "{}" "{}"'
                    .format('-b "%s"' % self.branch if self.branch else '',
                            self.repo_url, self.name),
                    cwd=DEPLOY)
            self._services = None
            self._volumes = None
            self._compose = None
        except CalledProcessError:
            if not retrying:
                log.warn("Failed to fetch %s, retrying", self.repo_url)
                self.fetch(retrying=True)
            else:
                raise

    def up(self):
        log.info("Starting %s", self.name)
        self.do('docker-compose up -d --build', cwd=self.path)

    def down(self):
        log.info("Stopping %s", self.name)
        self.do('docker-compose down', cwd=self.path)

    def _members(self):
        return self.do('consul members')

    def members(self):
        members = {}
        for m in self._members().split('\n')[1:]:
            name, ip, status = m.split()[:3]
            members[name] = {'ip': ip.split(':')[0], 'status': status}
        return members

    def compose_env(self, service, name, default=None):
        """retrieve an environment variable from the service in the compose
        """
        try:
            val = self.compose['services'][service]['environment'][name]
            log.info('Found a %s environment variable for '
                     'service %s in the compose file of %s',
                     name, service, self.name)
            return val
        except:
            log.info('No %s environment variable for '
                     'service %s in the compose file of %s',
                     name, service, self.name)
            return default

    def tls(self, service):
        """used to disable tls with TLS: self_signed """
        return self.compose_env(service, 'TLS')

    def url(self, service):
        """end url to expose the service """
        return self.compose_env(service, 'URL')

    def redirect_from(self, service):
        """ list of redirects transmitted to caddy """
        lines = self.compose_env(service, 'REDIRECT_FROM', '').split('\n')
        return [l.strip() for l in lines if len(l.split()) == 1]

    def redirect_to(self, service):
        """ list of redirects transmitted to caddy """
        lines = self.compose_env(service, 'REDIRECT_TO', '').split('\n')
        return [l.strip() for l in lines if 1 <= len(l.split()) <= 3]

    def domain(self, service):
        """ domain computed from the URL
        """
        return urlparse(self.url).netloc.split(':')[0]

    def proto(self, service):
        """frontend protocol configured in the compose for the service.
        """
        return self.compose_env(service, 'PROTO', 'http://')

    def port(self, service):
        """frontend port configured in the compose for the service.
        """
        return self.compose_env(service, 'PORT', '80')

    def ps(self, service):
        ps = self.do('docker ps -f name=%s --format "table {{.Status}}"'
                     % self.container_name(service))
        return ps.split('\n')[-1].strip()

    def register_kv(self, target, slave, myself):
        """register a service in the key/value store
        so that consul-template can regenerate the
        caddy and haproxy conf files
        """
        log.info("Registering URLs of %s in the key/value store",
                 self.name)
        for service in self.services:
            url = self.url(service)
            redirect_from = self.redirect_from(service)
            redirect_to = self.redirect_to(service)
            tls = self.tls(service)
            if not url:
                # service not exposed to the web
                continue
            domain = urlparse(url).netloc.split(':')[0]
            # store the domain and name in the kv
            ct = self.container_name(service)
            port = self.port(service)
            proto = self.proto(service)
            value = {
                'name': self.name,  # name of the service, and key in the kv
                'domain': domain,  # used by haproxy
                'ip': self.members()[target]['ip'],  # used by haproxy
                'node': target,  # used by haproxy and caddy
                'url': url,  # used by caddy
                'redirect_from': redirect_from,  # used by caddy
                'redirect_to': redirect_to,  # used by caddy
                'tls': tls,  # used by caddy
                'slave': slave,  # used by the handler
                'volumes': [v.name for v in self.volumes],
                'ct': '{proto}{ct}:{port}'.format(**locals())}  # used by caddy
            self.do("consul kv put site/{} '{}'"
                    .format(self.name, json.dumps(value)))
            log.info("Registered %s", self.name)

    def unregister_kv(self):
        self.do("consul kv delete site/{}".format(self.name))

    def register_consul(self):
        """register a service and check in consul
        """
        urls = [self.url(s) for s in self.services]
        svc = json.dumps({
            'Name': self.name,
            'Checks': [{
                'HTTP': url,
                'Interval': '60s'} for url in urls if url]})
        url = 'http://localhost:8500/v1/agent/service/register'
        res = requests.post(url, svc)
        if res.status_code != 200:
            msg = 'Consul service register failed: {}'.format(res.reason)
            log.error(msg)
            raise RuntimeError(msg)
        log.info("Registered %s in consul", self.name)

    def unregister_consul(self):
        for service in self.services:
            url = self.url(service)
            if not url:
                continue
            url = ('http://localhost:8500/v1/agent/service/deregister/:{}'
                   .format(self.name))
            res = requests.put(url)
            if res.status_code != 200:
                msg = 'Consul service deregister failed: {}'.format(res.reason)
                log.error(msg)
                raise RuntimeError(msg)
            log.info("Deregistered %s in consul", self.name)

    def enable_snapshot(self, enable):
        """enable or disable scheduled snapshots
        """
        for volume in self.volumes:
            volume.schedule_snapshots(60 if enable else 0)

    def enable_replicate(self, enable, ip):
        """enable or disable scheduled replication
        """
        for volume in self.volumes:
            volume.schedule_replicate(60 if enable else 0, ip)

    def enable_purge(self, enable):
        for volume in self.volumes:
            volume.schedule_purge(1440 if enable else 0, '1h:1d:1w:4w:1y')


class Volume(object):
    """wrapper for buttervolume cli
    """
    def __init__(self, name):
        self.name = name

    def do(self, cmd, cwd=None):
        return _run(cmd, cwd=cwd)

    def snapshot(self):
        """snapshot the volume
        """
        log.info(u'Snapshotting volume: {}'.format(self.name))
        return self.do("buttervolume snapshot {}".format(self.name))

    def schedule_snapshots(self, timer):
        """schedule snapshots of the volume
        """
        self.do("buttervolume schedule snapshot {} {}"
                .format(timer, self.name))

    def schedule_replicate(self, timer, slavehost):
        """schedule a replication of the volume
        """
        self.do("buttervolume schedule replicate:{} {} {}"
                .format(slavehost, timer, self.name))

    def schedule_purge(self, timer, pattern):
        """schedule a purge of the snapshots
        """
        self.do("buttervolume schedule purge:{} {} {}"
                .format(pattern, timer, self.name))

    def delete(self):
        """destroy a volume
        """
        log.info(u'Destroying volume: {}'.format(self.name))
        return self.do("docker volume rm {}".format(self.name))

    def restore(self, snapshot=None):
        if snapshot is None:  # use the latest snapshot
            snapshot = self.name
        log.info(u'Restoring snapshot: {}'.format(snapshot))
        restored = self.do("buttervolume restore {}".format(snapshot))
        log.info('Restored %s', restored)

    def send(self, snapshot, target):
        log.info(u'Sending snapshot: {}'.format(snapshot))
        self.do("buttervolume send {} {}".format(target, snapshot))


def handle(events, myself):
    for event in json.loads(events)[-1:]:
        event_name = event.get('Name')
        payload = b64decode(event.get('Payload', '')).decode('utf-8')
        if not payload:
            return
        log.info(u'Received event: {} with payload: {}'
                 .format(event_name, payload))
        try:
            payload = json.loads(payload)
        except:
            msg = 'Wrong event payload format. Please provide json'
            log.error(msg)
            raise Exception(msg)

        if event_name == 'deploy':
            deploy(payload, myself)
        elif event_name == 'destroy':
            destroy(payload, myself)
        else:
            log.error('Unknown event name: {}'.format(event_name))


def deploy(payload, myself):
    """Keep in mind this is executed in the consul container
    Deployments are done in the DEPLOY folder.
    """
    repo_url = payload['repo']
    newmaster = payload['target']
    newslave = payload.get('slave')
    branch = payload.get('branch', '')

    oldapp = Application(repo_url, branch=branch)
    oldmaster = oldapp.master_node
    oldslave = oldapp.slave_node
    newapp = Application(repo_url, branch=branch)
    members = newapp.members()

    if oldmaster == myself:  # master ->
        log.info('I was the master of %s', oldapp.name)
        oldapp.down()
        if oldslave:
            oldapp.enable_replicate(False, members[oldslave]['ip'])
        else:
            oldapp.enable_snapshot(False)
        oldapp.enable_purge(False)
        oldapp.shelve()
        if newmaster == myself:  # master -> master
            log.info("I'm still the master of %s", newapp.name)
            newapp.fetch()
            newapp.check()
            if newslave:
                newapp.enable_replicate(True, members[newslave]['ip'])
            else:
                newapp.enable_snapshot(True)
            newapp.enable_purge(True)
            newapp.register_kv(newmaster, newslave, myself)  # for consul-templ
            newapp.register_consul()  # for consul check
            newapp.up()
        elif newslave == myself:  # master -> slave
            log.info("I'm now the slave of %s", newapp.name)
            with newapp.notify_transfer():
                for volume in newapp.volumes:
                    volume.send(volume.snapshot(), members[newmaster]['ip'])
            oldapp.unregister_consul()
            for volume in newapp.volumes:
                volume.delete()
            newapp.enable_purge(True)
        else:  # master -> nothing
            log.info("I'm nothing now for %s", newapp.name)
            with newapp.notify_transfer():
                for volume in newapp.volumes:
                    volume.send(volume.snapshot(), members[newmaster]['ip'])
            oldapp.unregister_consul()
            for volume in newapp.volumes:
                volume.delete()
        oldapp.clean()

    elif oldslave == myself:  # slave ->
        log.info("I was the slave of %s", oldapp.name)
        oldapp.enable_purge(False)
        oldapp.down()
        if newmaster == myself:  # slave -> master
            log.info("I'm now the master of %s", newapp.name)
            newapp.fetch()
            newapp.check()
            newapp.wait_notification()  # wait for master notification
            for volume in newapp.volumes:
                volume.restore()
            if newslave:
                newapp.enable_replicate(True, members[newslave]['ip'])
            else:
                newapp.enable_snapshot(True)
            newapp.enable_purge(True)
            newapp.register_kv(newmaster, newslave, myself)  # for consul-templ
            newapp.register_consul()  # for consul check
            newapp.up()
        elif newslave == myself:  # slave -> slave
            log.info("I'm still the slave of %s", newapp.name)
            newapp.enable_purge(True)
        else:  # slave -> nothing
            log.info("I'm nothing now for %s", newapp.name)

    else:  # nothing ->
        log.info("I was nothing for %s", oldapp.name)
        if newmaster == myself:  # nothing -> master
            log.info("I'm now the master of %s", newapp.name)
            newapp.fetch()
            newapp.check()
            if oldslave:
                newapp.wait_notification()  # wait for master notification
                for volume in newapp.volumes:
                    volume.restore()
            if newslave:
                newapp.enable_replicate(True, members[newslave]['ip'])
            else:
                newapp.enable_snapshot(True)
            newapp.enable_purge(True)
            newapp.register_kv(newmaster, newslave, myself)  # for consul-templ
            newapp.register_consul()  # for consul check
            newapp.up()
        elif newslave == myself:  # nothing -> slave
            log.info("I'm now the slave of %s", newapp.name)
            newapp.enable_purge(True)
        else:  # nothing -> nothing
            log.info("I'm still nothing for %s", newapp.name)


def destroy(payload, myself):
    """ destroy containers, unregister, remove schedules but keep volumes
    """
    repo_url = payload['repo']
    branch = payload.get('branch', '')

    oldapp = Application(repo_url, branch=branch)
    oldmaster = oldapp.master_node
    oldslave = oldapp.slave_node
    members = oldapp.members()

    if oldmaster == myself:  # master ->
        log.info('I was the master of %s', oldapp.name)
        oldapp.down()
        oldapp.unregister_consul()
        if oldslave:
            oldapp.enable_replicate(False, members[oldslave]['ip'])
        else:
            oldapp.enable_snapshot(False)
        oldapp.enable_purge(False)
        oldapp.unregister_kv()
        oldapp.clean()
    elif oldslave == myself:  # slave ->
        log.info("I was the slave of %s", oldapp.name)
        oldapp.enable_purge(False)
    else:  # nothing ->
        log.info("I was nothing for %s", oldapp.name)


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG,
                        format='{asctime}\t{levelname}\t{message}',
                        filename=join(DEPLOY, 'handler.log'),
                        style='{')
    myself = socket.gethostname()
    # read json from stdin
    handle(len(argv) == 2 and argv[1] or stdin.read(), myself)
