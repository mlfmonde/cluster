#!/usr/bin/python3
# coding: utf-8
# TODO identify pure functions
import hashlib
import json
import logging
import re
import requests
import socket
import time
import yaml
from base64 import b64decode, b64encode
from contextlib import contextmanager
from datetime import datetime
from functools import reduce
from os.path import basename, join, exists
from subprocess import run as srun, CalledProcessError, PIPE
from sys import stdin, argv
from urllib.parse import urlparse
from uuid import uuid1
DTFORMAT = "%Y-%m-%dT%H:%M:%S.%f"
DEPLOY = '/deploy'
log = logging.getLogger()
HANDLED = join(DEPLOY, 'events.log')
if not exists(HANDLED):
    open(HANDLED, 'x')


def do(cmd, cwd=None):
    """ Run a command"""
    try:
        if cwd:
            cmd = 'cd "{}" && {}'.format(cwd, cmd)
        log.info('Running: ' + cmd)
        res = srun(cmd, shell=True, check=True, stdout=PIPE, stderr=PIPE)
        return res.stdout.decode().strip()
    except CalledProcessError as e:
        log.error("Failed to run %s: %s", e.cmd, e.stderr.decode())
        raise


def kv(self, name, key):
    """ return the current value of the key in the kv"""
    try:
        cmd = 'consul kv get app/{}'.format(name)
        value = json.loads(do(cmd))[key]
        log.info('Reading %s in kv: %s = %s', name, key, value)
        return value
    except:
        log.warn('Could not determine the %s node for %s', key, self.name)
        return None


class Application(object):
    """ represents a docker compose, its proxy conf and deployment path
    """
    def __init__(self, repo_url, branch, cwd=None):
        self.repo_url, self.branch = repo_url.strip(), branch.strip()
        if self.repo_url.endswith('.git'):
            self.repo_url = self.repo_url[:-4]
        md5 = hashlib.md5(urlparse(self.repo_url.lower()).path.encode('utf-8')
                          ).hexdigest()
        repo_name = basename(self.repo_url.strip('/'))
        self.name = repo_name + ('_' + self.branch if self.branch else ''
                                 ) + '.' + md5[:5]  # don't need full md5
        self._services = None
        self._volumes = None
        self._compose = None
        self._deploy_date = None

    @property
    def deploy_date(self):
        """date of the last deployment"""
        if self._deploy_date is None:
            self._deploy_date = kv(self.name, 'deploy_date')
        return self._deploy_date

    def _path(self, deploy_date=None):
        """path of the deployment checkout"""
        deploy_date = deploy_date or self.deploy_date
        if deploy_date:
            return join(DEPLOY, self.name + '@' + deploy_date)
        return None

    @property
    def path(self):
        return self._path()

    def check(self):
        """consistency check"""
        all_apps = {s['key']: json.loads(b64decode(s['value']).decode('utf-8'))
                    for s in json.loads(do('consul kv export app/'))}
        # check urls are not already used
        for service in self.services:
            service_urls = self.proxy_conf(service).get('urls', [])
            for appname, appconf in all_apps.items():
                if appname == self.name:
                    continue
                for url in [u.get('url') for u in service_urls]:
                    if (url == appconf.get('url')):
                        msg = ('Aborting! {} is already deployed by {}'
                               .format(url, appname))
                        log.error(msg)
                        raise ValueError(msg)

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
            do('consul kv put migrate/{}/success'.format(self.name))
        except:
            log.error('Volume migrate FAILED!')
            do('consul kv put migrate/{}/failure'.format(self.name))
            self.up()  # TODO move in the deploy
            raise
        log.info('Volume migrate SUCCEEDED!')

    def wait_transfer(self):
        loops = 0
        while loops < 60:
            log.info('Waiting migrate notification for %s', self.name)
            res = do('consul kv get -keys migrate/{}'.format(self.name))
            if res:
                status = res.split('/')[-1]
                do('consul kv delete -recurse migrate/{}/'
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
        return re.sub(r'[^a-z0-9]', '', self.name)

    @property
    def volumes_from_kv(self):
        """volumes defined in the kv
        """
        if self._volumes is None:
            try:
                self._volumes = [
                    Volume(v) for v in kv(self.name, 'volumes')]
            except:
                log.info("No volumes found in the kv")
            self._volumes = self._volumes or None
        return self._volumes

    @property
    def volumes(self):
        """btrfs volumes defined in the compose
        """
        if self._volumes is None:
            try:
                self._volumes = [
                    Volume(self.project + '_' + v[0])
                    for v in self.compose.get('volumes', {}).items()
                    if v[1] and v[1].get('driver') == 'btrfs']
            except:
                log.info("No volumes found in the compose")
                self._volumes = []
        return self._volumes

    def container_name(self, service):
        """did'nt find a way to query reliably so do it static
        It assumes there is only 1 container for a project/service couple
        """
        return self.project + '_' + service + '_1'  # FIXME _1

    def clean(self):
        if self.path and exists(self.path):
            do('rm -rf "{}"'.format(self.path))

    def download(self, retrying=False):
        try:
            self.clean()
            deploy_date = datetime.now().strftime(DTFORMAT)
            path = self._path(deploy_date)
            do('git clone --depth 1 {} "{}" "{}"'
               .format('-b "%s"' % self.branch if self.branch else '',
                       self.repo_url, path),
               cwd=DEPLOY)
            self._deploy_date = deploy_date
            self._services = None
            self._volumes = None
            self._compose = None
        except CalledProcessError:
            if not retrying:
                log.warn("Failed to download %s, retrying", self.repo_url)
                self.download(retrying=True)
            else:
                raise

    def up(self):
        if self.path and exists(self.path):
            log.info("Starting %s", self.name)
            do('docker-compose -p "{}" up -d --build'
               .format(self.project),
               cwd=self.path)
        else:
            log.info("No deployment, cannot start %s", self.name)

    def down(self, deletevolumes=False):
        if self.path and exists(self.path):
            log.info("Stopping %s", self.name)
            v = '-v' if deletevolumes else ''
            do('docker-compose -p "{}" down {}'.format(self.project, v),
               cwd=self.path)
        else:
            log.info("No deployment, cannot stop %s", self.name)

    @property
    def members(self):
        members = {}
        for m in do('consul members').split('\n')[1:]:
            name, ip, status = m.split()[:3]
            members[name] = {'ip': ip.split(':')[0], 'status': status}
        return members

    def proxy_conf(self, service):
        """retrieve the reverse proxy config from the compose
        """
        if self._cluster_conf is None:
            try:
                name = 'PROXY_CONF'
                val = self.compose['services'][service]['environment'][name]
                log.info('Found a %s environment variable for '
                         'service %s in the compose file of %s',
                         name, service, self.name)
                return json.loads(val)
            except:
                log.info('Invalid or missing %s environment variable for '
                         'service %s in the compose file of %s',
                         name, service, self.name)
        return self._cluster_conf or {}

    def ps(self, service):
        ps = do('docker ps -f name=%s --format "table {{.Status}}"'
                % self.container_name(service))
        return ps.split('\n')[-1].strip()

    def register_kv(self, target, slave):
        """register services in the key/value store
        so that consul-template can regenerate the
        caddy and haproxy conf files
        """
        log.info("Registering URLs of %s in the key/value store",
                 self.name)
        for service in self.services:
            value = self.proxy_conf(service)
            value.setdefault('urls', [])
            value.update({
                'repo_url': self.repo_url,
                'branch': self.branch,
                'deploy_date': self._deploy_date,
                'ip': self.members[target]['ip'],
                'master': target,  # for haproxy and caddy
                'slave': slave,  # for the handler
                'volumes': [v.name for v in self.volumes]})
            for url in value['urls']:
                if not url['url']:
                    log.error('Found a PROXY_CONF without url '
                              'for service %s of %s',
                              service, self.name)
                    continue
                url['domain'] = urlparse(url['url']).netloc.split(':')[0]
                url.setdefault('port', '80')
                url.setdefault('proto', 'http://')
                url.setdefault('ctname', self.container_name(service))
                url.setdefault('ct', '{proto}{ctname}:{port}'.format(**url))

            do("consul kv put app/{} '{}'"
               .format(self.name, json.dumps(value)))
            log.info("Registered %s", self.name)

    def unregister_kv(self):
        do("consul kv delete app/{}".format(self.name))

    def register_consul(self):
        """register a service and check in consul
        """
        urls = reduce(list.__add__,
                      [self.proxy_conf(s)['urls'].keys() for s in self.services
                       if self.proxy_conf(s)['urls']])
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
        res = requests.put(
            'http://localhost:8500/v1/agent/service/deregister/{}'
            .format(self.name))
        if res.status_code != 200:
            msg = 'Consul service deregister failed: {}'.format(res.reason)
            log.error(msg)
            raise RuntimeError(msg)
        log.info("Deregistered %s in consul", self.name)

    def enable_snapshot(self, enable):
        """enable or disable scheduled snapshots
        """
        for volume in self.volumes_from_kv:
            volume.schedule_snapshots(60 if enable else 0)

    def enable_replicate(self, enable, ip):
        """enable or disable scheduled replication
        """
        for volume in self.volumes_from_kv:
            volume.schedule_replicate(60 if enable else 0, ip)

    def enable_purge(self, enable):
        for volume in self.volumes_from_kv:
            volume.schedule_purge(1440 if enable else 0, '1h:1d:1w:4w:1y')


class Volume(object):
    """wrapper for buttervolume cli
    """
    def __init__(self, name):
        self.name = name

    def snapshot(self):
        """snapshot the volume
        """
        volumes = [l.split()[1] for l in do(
                   "docker volume ls -f driver=btrfs").splitlines()[1:]]
        if self.name in volumes:
            log.info(u'Snapshotting volume: {}'.format(self.name))
            return do("buttervolume snapshot {}".format(self.name))
        else:
            log.warn('Could not snapshot unexisting volume %s', self.name)

    def schedule_snapshots(self, timer):
        """schedule snapshots of the volume
        """
        do("buttervolume schedule snapshot {} {}"
           .format(timer, self.name))

    def schedule_replicate(self, timer, slavehost):
        """schedule a replication of the volume
        """
        do("buttervolume schedule replicate:{} {} {}"
           .format(slavehost, timer, self.name))

    def schedule_purge(self, timer, pattern):
        """schedule a purge of the snapshots
        """
        do("buttervolume schedule purge:{} {} {}"
           .format(pattern, timer, self.name))

    def delete(self):
        """destroy a volume
        """
        log.info(u'Destroying volume: {}'.format(self.name))
        return do("docker volume rm {}".format(self.name))

    def restore(self, snapshot=None, target=''):
        if snapshot is None:  # use the latest snapshot
            snapshot = self.name
        log.info(u'Restoring snapshot: {}'.format(snapshot))
        restored = do("buttervolume restore {} {}"
                      .format(snapshot, target))
        target = 'as {}'.format(target) if target else ''
        log.info('Restored %s %s (after a backup: %s)',
                 snapshot, target, restored)

    def send(self, snapshot, target):
        log.info(u'Sending snapshot: {}'.format(snapshot))
        do("buttervolume send {} {}".format(target, snapshot))


def handle(events, myself):
    for event in json.loads(events):
        event_id = event.get('ID')
        if event_id + '\n' in open(HANDLED, 'r').readlines():
            log.info('Event already handled in the past: %s', event_id)
            continue
        open(HANDLED, 'a').write(event_id + '\n')
        event_name = event.get('Name')
        payload = b64decode(event.get('Payload', '')).decode('utf-8')
        if not payload:
            return
        log.info(u'**** Received event: {} with ID: {} and payload: {}'
                 .format(event_name, event_id, payload))
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
        elif event_name == 'migrate':
            migrate(payload, myself)
        else:
            log.error('Unknown event name: {}'.format(event_name))


def deploy(payload, myself):
    """Keep in mind this is executed in the consul container
    Deployments are done in the DEPLOY folder. Needs:
    {"repo"': <url>, "branch": <branch>, "target": <host>, "slave": <host>}
    """
    repo_url = payload['repo']
    newmaster = payload['target']
    newslave = payload.get('slave')
    if newmaster == newslave:
        msg = "Slave must be different than the target Master"
        log.error(msg)
        raise AssertionError(msg)
    branch = payload.get('branch')
    if not branch:
        msg = "Branch is mandatory"
        log.error(msg)
        raise AssertionError(msg)

    oldapp = Application(repo_url, branch=branch)
    oldmaster = kv(oldapp.name, 'master')
    oldslave = kv(oldapp.name, 'slave')
    newapp = Application(repo_url, branch=branch)
    members = newapp.members

    if oldmaster == myself:  # master ->
        log.info('** I was the master of %s', oldapp.name)
        oldapp.down()
        if oldslave:
            oldapp.enable_replicate(False, members[oldslave]['ip'])
        else:
            oldapp.enable_snapshot(False)
        oldapp.enable_purge(False)
        if newmaster == myself:  # master -> master
            log.info("** I'm still the master of %s", newapp.name)
            for volume in oldapp.volumes_from_kv:
                volume.snapshot()
            newapp.download()
            newapp.check()
            newapp.up()
            if newslave:
                newapp.enable_replicate(True, members[newslave]['ip'])
            else:
                newapp.enable_snapshot(True)
            newapp.enable_purge(True)
            newapp.register_kv(newmaster, newslave)  # for consul-template
            newapp.register_consul()  # for consul check
        elif newslave == myself:  # master -> slave
            log.info("** I'm now the slave of %s", newapp.name)
            with newapp.notify_transfer():
                for volume in newapp.volumes_from_kv:
                    volume.send(volume.snapshot(), members[newmaster]['ip'])
            oldapp.unregister_consul()
            oldapp.down(deletevolumes=True)
            newapp.enable_purge(True)
        else:  # master -> nothing
            log.info("** I'm nothing now for %s", newapp.name)
            with newapp.notify_transfer():
                for volume in newapp.volumes_from_kv:
                    volume.send(volume.snapshot(), members[newmaster]['ip'])
            oldapp.unregister_consul()
            oldapp.down(deletevolumes=True)
        oldapp.clean()

    elif oldslave == myself:  # slave ->
        log.info("** I was the slave of %s", oldapp.name)
        oldapp.enable_purge(False)
        if newmaster == myself:  # slave -> master
            log.info("** I'm now the master of %s", newapp.name)
            newapp.download()
            newapp.check()
            newapp.wait_transfer()  # wait for master notification
            for volume in newapp.volumes_from_kv:
                volume.restore()
            newapp.up()
            if newslave:
                newapp.enable_replicate(True, members[newslave]['ip'])
            else:
                newapp.enable_snapshot(True)
            newapp.enable_purge(True)
            newapp.register_kv(newmaster, newslave)  # for consul-template
            newapp.register_consul()  # for consul check
        elif newslave == myself:  # slave -> slave
            log.info("** I'm still the slave of %s", newapp.name)
            newapp.enable_purge(True)
        else:  # slave -> nothing
            log.info("** I'm nothing now for %s", newapp.name)

    else:  # nothing ->
        log.info("** I was nothing for %s", oldapp.name)
        if newmaster == myself:  # nothing -> master
            log.info("** I'm now the master of %s", newapp.name)
            newapp.download()
            newapp.check()
            if oldslave:
                newapp.wait_transfer()  # wait for master notification
                for volume in newapp.volumes_from_kv:
                    volume.restore()
            newapp.up()
            if newslave:
                newapp.enable_replicate(True, members[newslave]['ip'])
            else:
                newapp.enable_snapshot(True)
            newapp.enable_purge(True)
            newapp.register_kv(newmaster, newslave)  # for consul-template
            newapp.register_consul()  # for consul check
        elif newslave == myself:  # nothing -> slave
            log.info("** I'm now the slave of %s", newapp.name)
            newapp.download()
            newapp.enable_purge(True)
        else:  # nothing -> nothing
            log.info("** I'm still nothing for %s", newapp.name)


def destroy(payload, myself):
    """Destroy containers, unregister, remove schedules and volumes,
    but keep snapshots. Needs:
    {"repo"': <url>, "branch": <branch>}
    """
    repo_url = payload['repo']
    branch = payload.get('branch')
    if not branch:
        msg = "Branch is mandatory"
        log.error(msg)
        raise AssertionError(msg)

    oldapp = Application(repo_url, branch=branch)
    oldmaster = kv(oldapp.name, 'master')
    oldslave = kv(oldapp.name, 'slave')
    members = oldapp.members

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
        for volume in oldapp.volumes_from_kv:
            volume.snapshot()
        oldapp.down(deletevolumes=True)
        oldapp.clean()
    elif oldslave == myself:  # slave ->
        log.info("I was the slave of %s", oldapp.name)
        oldapp.enable_purge(False)
    else:  # nothing ->
        log.info("I was nothing for %s", oldapp.name)
    log.info("Successfully destroyed")


def migrate(payload, myself):
    """migrate volumes from one app to another. Needs:
    {"repo"': <url>, "branch": <branch>,
     "target": {"repo": <url>, "branch": <branch>}}
    If the "repo" or "branch" of the "target" is not given, it is the same as
    the source
    """
    repo_url = payload['repo']
    branch = payload['branch']
    target = payload['target']
    assert(target.get('repo') or target.get('branch'))

    sourceapp = Application(repo_url, branch=branch)
    targetapp = Application(target.get('repo', repo_url),
                            branch=target.get('branch', branch))
    source_node = kv(sourceapp.name, 'master')
    target_node = kv(targetapp.name, 'master')
    if source_node != myself and target_node != myself:
        log.info('Not concerned by this event')
        return
    source_volumes = []
    target_volumes = []
    # find common volumes
    for source_volume in sourceapp.volumes:
        source_name = source_volume.name.split('_', 1)[1]
        for target_volume in targetapp.volumes:
            target_name = target_volume.name.split('_', 1)[1]
            if source_name == target_name:
                source_volumes.append(source_volume)
                target_volumes.append(target_volume)
            else:
                continue
    log.info('Found %s volumes to restore: %s',
             len(source_volumes), repr([v.name for v in source_volumes]))
    # tranfer and restore volumes
    if source_node != target_node:
        if source_node == myself:
            with sourceapp.notify_transfer():
                for volume in source_volumes:
                    volume.send(
                        volume.snapshot(),
                        targetapp.members[target_node]['ip'])
        if target_node == myself:
            sourceapp.wait_transfer()
    if target_node == myself:
        targetapp.down()
        for source_vol, target_vol in zip(source_volumes, target_volumes):
            source_vol.restore(target=target_vol.name)
        targetapp.up()
    log.info('Restored %s to %s', sourceapp.name, targetapp.name)


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG,
                        format='{asctime}\t{levelname}\t{message}',
                        filename=join(DEPLOY, 'handler.log'),
                        style='{')
    myself = socket.gethostname()
    manual_input = None
    if len(argv) >= 3:
        # allow to launch manually inside consul docker
        event = argv[1]
        payload = b64encode(' '.join(argv[2:]).encode('utf-8')).decode('utf-8')
        manual_input = json.dumps([{
            'ID': str(uuid1()), 'Name': event,
            'Payload': payload, 'Version': 1, 'LTime': 1}])

    handle(manual_input or stdin.read(), myself)
