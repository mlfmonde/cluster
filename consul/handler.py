#!/usr/bin/python3
# coding: utf-8
import json
import logging
import os
import re
import requests
import socket
import time
import yaml
from base64 import b64decode
from contextlib import contextmanager
from os.path import basename, join, exists
from subprocess import run as srun, CalledProcessError, PIPE
from sys import stdin, argv
from urllib.parse import urlparse
DEPLOY = '/deploy'
log = logging.getLogger()


def concat(xs):
    return [y for x in xs for y in x]


def _run(cmd, cwd=None, test=False):
    try:
        if cwd:
            cmd = 'cd "{}" && {}'.format(cwd, cmd)
        if test:
            print(cmd)
            return ''
        else:
            log.info(cmd)
            res = srun(cmd, shell=True, check=True, stdout=PIPE, stderr=PIPE)
            out = res.stdout.decode().strip()
            return out
    except CalledProcessError as e:
        log.error("Failed to run %s: %s", e.cmd, e.stderr.decode())
        raise


class Application(object):
    def __init__(self, repo_url, branch, cwd=None, test=False):
        self.test = test  # for unit tests
        self.repo_url, self.branch = repo_url, branch
        repo_name = basename(self.repo_url.strip('/'))
        if repo_name.endswith('.git'):
            repo_name = repo_name[:-4]
        self.name = repo_name + ('_' + self.branch if self.branch else '')
        self.path = join(DEPLOY, self.name)  # path of the checkout
        self._services = None
        self._volumes = None
        self._lock = False
        self._compose = None

    def do(self, cmd, cwd=None, runintest=True):
        return _run(cmd, cwd=cwd, test=self.test and not runintest)

    @property
    def compose(self):
        """read the compose file
        """
        if self._compose is None:
            try:
                with open(join(self.path, 'docker-compose.yml')) as c:
                    self._compose = yaml.load(c.read())
            except:
                raise EnvironmentError('Could not read docker-compose.yml')
        return self._compose

    @contextmanager
    def lock(self):
        self.do('consul kv put transferring/{}'.format(self.name))
        try:
            yield
        except:
            log.error('Volume transfer FAILED!')
            self.unlock()
            self.start()
            raise
        log.error('Volume transfer SUCCEEDED!')
        self.unlock()

    def unlock(self):
        self.do('consul kv delete transferring/{}'.format(self.name))

    def wait_lock(self):
        loops = 0
        while loops < 60:
            log.info('Waiting lock release for %s', self.name)
            try:
                self.do('consul kv get transferring/{}'.format(self.name))
            except CalledProcessError:
                log.info('Lock released')
                return
            time.sleep(1)
            loops += 1
        self.unlock()
        log.info('Waited too much :(')
        raise RuntimeError('deployment of {} failed'.format(self.name))

    @property
    def services(self):
        """name of the services in the compose file
        """
        if self._services is None:
            self._services = self.compose['services'].keys()
        return self._services

    @property
    def project(self):
        return re.sub(r'[^a-z0-9]', '', self.name.lower())

    @property
    def volumes(self):
        """btrfs volumes defined in the compose
        """
        if self._volumes is None:
            self._volumes = [
                Volume(self.project + '_' + v[0], test=self.test)
                for v in self.compose.get('volumes', {}).items()
                if v[1] and v[1].get('driver') == 'btrfs']
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

    def clean(self):
        self.do('rm -rf "{}"'.format(self.path))

    def fetch(self, retrying=False):
        try:
            if exists(self.path):
                self.clean()
            self.do('git clone --depth 1 -b "{}" "{}" "{}"'
                    .format(self.branch, self.repo_url, self.name), cwd=DEPLOY)
            self._services = None
            self._volumes = None
            self._compose = None
        except CalledProcessError:
            if not retrying:
                log.warn("Failed to fetch %s, retrying", self.repo_url)
                self.fetch(retrying=True)
            else:
                raise

    def start(self):
        log.info("Starting %s", self.name)
        self.do('docker-compose up -d --build', cwd=self.path)

    def stop(self):
        log.info("Stopping %s", self.name)
        self.do('docker-compose down', cwd=self.path)

    def _members(self):
        if self.test:
            return (
                'Node   Address            Status  Type       DC\n'
                'node1   10.10.10.11:8301  alive   server     dc1\n'
                'node2   10.10.10.12:8301  alive   server     dc1\n'
                'node3   10.10.10.13:8301  alive   server     dc1')
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
                'tls': tls,  # used by caddy
                'slave': slave,  # used by the handler
                'ct': '{proto}{ct}:{port}'.format(**locals())}  # used by caddy
            cmd = ("consul kv put site/{} '{}'"
                   .format(self.name, json.dumps(value)))
            self.do(cmd, runintest=False)
            log.info("Registered: %s", cmd)

    def register_consul(self):
        """register a service in consul
        """
        # FIXME generate automatically
        try:
            path = '{}/service.json'.format(self.path)
            log.info("Registering %s in consul", self.path)
            content = '{}'
            with open(path) as f:
                content = f.read()
        except Exception:
            log.error('Could not read %s', path)
            raise
        url = 'http://localhost:8500/v1/agent/service/register'
        svc = json.dumps(json.loads(content))
        if self.test:
            print('POST', url, content)
        else:
            res = requests.post(url, svc)
            if res.status_code != 200:
                raise RuntimeError('Consul service register failed: {}'
                                   .format(res.reason))
            log.info("Registered %s in consul", self.path)


class Volume(object):
    """wrapper for buttervolume cli
    """
    def __init__(self, volume, test=False):
        self.test = test
        self.volume = volume

    def do(self, cmd, cwd=None):
        return _run(cmd, cwd=cwd, test=self.test)

    def snapshot(self):
        """snapshot the volume
        """
        log.info(u'Snapshotting volume: {}'.format(self.volume))
        return self.do("buttervolume snapshot {}".format(self.volume))

    def schedule_snapshots(self, timer):
        """schedule snapshots of the volume
        """
        self.do("buttervolume schedule snapshot {} {}"
                .format(timer, self.volume))

    def schedule_replicate(self, timer, slavehost):
        """schedule a replication of the volume
        """
        self.do("buttervolume schedule replicate:{} {} {}"
                .format(slavehost, timer, self.volume))

    def delete(self):
        """destroy a volume
        """
        log.info(u'Destroying volume: {}'.format(self.volume))
        return self.do("docker volume rm {}".format(self.volume))

    def restore(self, snapshot=None):
        log.info(u'Restoring snapshot: {}'.format(snapshot))
        if snapshot is None:  # use the latest snapshot
            snapshot = self.volume

    def send(self, snapshot, target):
        log.info(u'Sending snapshot: {}'.format(snapshot))
        self.do("buttervolume send {} {}".format(target, snapshot))


def handle(events, myself, test=False):
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
            raise Exception('Wrong event payload format. Please provide json')

        if event_name == 'deploymaster':
            deploymaster(payload, myself, test)
        else:
            log.error('Unknown event name: {}'.format(event_name))


def deploymaster(payload, myself, test):
    """Keep in mind this is executed in the consul container
    Deployments are done in the DEPLOY folder.
    """
    repo_url = payload['repo']
    target = payload['target']
    slave = payload.get('slave')
    branch = payload.get('branch', 'master')

    app = Application(repo_url, branch=branch, test=test)
    master_node = app.master_node
    oldslave = app.slave_node
    members = app.members()
    if myself == target:  # 1st deployment or slave that will turn to master
        app.fetch()
        time.sleep(2)  # let the master put the lock
        if myself != master_node and master_node is not None:
            app.wait_lock()
            for volume in app.volumes:
                volume.restore()
        for volume in app.volumes:
            if slave:
                volume.schedule_replicate(60, members[slave]['ip'])
            else:
                volume.schedule_snapshots(60)
        app.register_kv(target, slave, myself)  # for consul-template
        app.register_consul()  # for consul check
        app.start()
    elif myself == master_node:  # master that will turn to a slave
        with app.lock():
            # first replicate live to lower downtime
            for volume in app.volumes:
                volume.send(volume.snapshot(), members[target]['ip'])
                volume.schedule_snapshots(0)
                if oldslave is not None:
                    volume.schedule_replicate(0, members[oldslave]['ip'])
            # then stop and replicate again (should be faster)
            app.stop()
            for volume in app.volumes:
                volume.send(volume.snapshot(), members[target]['ip'])
        for volume in app.volumes:
            volume.delete()


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG,
                        format='{asctime}\t{levelname}\t{message}',
                        filename=join(DEPLOY, 'handler.log'),
                        style='{')
    try:  # test mode?
        test = argv[0] == 'test'
    except:
        test = False
    test = os.environ.get('TEST', test) and True or False
    myself = socket.gethostname()
    # read json from stdin
    handle(len(argv) == 2 and argv[1] or stdin.read(), myself, test)
