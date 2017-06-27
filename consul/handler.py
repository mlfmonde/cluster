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
    """commands
    """
    def __init__(self, repo_url, cwd=None, test=False):
        self.test = test  # for unit tests
        self.repo_url = repo_url  # of the git repository
        name = basename(repo_url.strip('/'))
        self.name = name[:-4] if name.endswith('.git') else name  # repository
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

    def lock(self):
        self.do('consul kv put deploying/{}'.format(self.name))

    def unlock(self):
        self.do('consul kv delete deploying/{}'.format(self.name))

    def wait_lock(self):
        loops = 0
        while loops < 60:
            log.info('Waiting lock release for %s', self.name)
            try:
                self.do('consul kv get deploying/{}'.format(self.name))
            except Exception:
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

    @property
    def slave_node(self):
        """slave node for the current app
        """
        domain = ''
        try:
            domains = [self.domain(s) for s in self.services]
            domains = [d for d in domains if d is not None]
            domain = domains[0] if domains else ''
            if not domain:
                urls = [self.url(s) for s in self.services]
                urls = [d for d in urls if d is not None]
                url = urls[0] if urls else ''
                domain = urlparse(url).netloc.split(':')[0]
            cmd = 'consul kv get site/{}'.format(domain)
            return json.loads(self.do(cmd))['slave']
        except:
            log.warn('Could not determine the slave node for %s', domain)
            return None

    @property
    def master_node(self):
        """master node for the current app
        """
        domain = ''
        try:
            domains = [self.domain(s) for s in self.services]
            domains = [d for d in domains if d is not None]
            domain = domains[0] if domains else ''
            if not domain:
                urls = [self.url(s) for s in self.services]
                urls = [d for d in urls if d is not None]
                url = urls[0] if urls else ''
                domain = urlparse(url).netloc.split(':')[0]
            cmd = 'consul kv get site/{}'.format(domain)
            return json.loads(self.do(cmd))['node']
        except:
            log.warn('Could not determine the master node for %s', domain)
            return None

    def clean(self):
        self.do('rm -rf "{}"'.format(self.path))

    def fetch(self, retrying=False):
        try:
            if exists(self.path):
                self.do('rm -rf "{}"'.format(self.repo_url), cwd=DEPLOY)
            self.do('git clone --depth 1 "{}"'.format(self.repo_url), cwd=DEPLOY)
            self._services = None
            self._volumes = None
            self._compose = None
        except CalledProcessError:
            if not retrying:
                log.warn("Failed to fetch %s, retrying", self.name)
                self.fetch(retrying=True)
            else:
                raise

    def start(self):
        log.info("Starting the project %s", self.name)
        self.do('docker-compose up -d --build', cwd=self.path)

    def stop(self):
        log.info("Stopping the project %s", self.name)
        self.do('docker-compose down', cwd=self.path)

    def _members(self):
        if self.test:
            return (
                'Node   Address            Status  Type       DC\n'
                'edjo   10.91.210.58:8301  alive   server     dc1\n'
                'nepri  10.91.210.57:8301  alive   server     dc1\n'
                'tayt   10.91.210.59:8301  alive   server     dc1')
        return self.do('consul members')

    def members(self):
        members = {}
        for m in self._members().split('\n')[1:]:
            name, ip, status = m.split()[:3]
            members[name] = {'ip': ip.split(':')[0], 'status': status}
        return members

    def tls(self, service):
        """TLS configured in the compose for the service
        """
        try:
            return self.compose['services'][service]['environment']['TLS']
        except:
            log.info('Could not find a TLS environment variable for '
                     'service %s in the compose file of %s',
                     service, self.name)

    def url(self, service):
        """URL configured in the compose for the service
        """
        try:
            return self.compose['services'][service]['environment']['URL']
        except:
            log.warn('Could not find a URL environment variable for '
                     'service %s in the compose file of %s',
                     service, self.name)

    def domain(self, service):
        """DOMAIN configured in the compose for the service
        WARNING deprecated, don't use
        """
        try:
            return self.compose['services'][service]['environment']['DOMAIN']
        except:
            log.info('Could not find a DOMAIN environment variable for '
                     'service %s in the compose file of %s',
                     service, self.name)

    def proto(self, service):
        """frontend PROTO configured in the compose for the service.
        Defaults to http:// if unspecified
        """
        try:
            return self.compose['services'][service]['environment']['PROTO']
        except:
            log.warn('Could not find a PROTO environment variable for '
                     'service %s in the compose file of %s',
                     service, self.name)
            return 'http://'

    def port(self, service):
        """frontend PORT configured in the compose for the service.
        Defaults to 80 if unspecified
        """
        try:
            return self.compose['services'][service]['environment']['PORT']
        except:
            log.warn('Could not find a PORT environment variable for '
                     'service %s in the compose file of %s',
                     service, self.name)
            return '80'

    def ps(self, service):
        ps = self.do('docker ps -f name=%s --format "table {{.Status}}"'
                     % self.container_name(service))
        return ps.split('\n')[-1].strip()

    def register_kv(self, target, slave, hostname):
        """register a service in the kv store
        so that consul-template can regenerate the
        caddy and haproxy conf files
        """
        log.info("Registering URLs of %s in the kv store", self.name)
        for service in self.services:
            domain = self.domain(service)
            url = self.url(service)
            tls = self.tls(service)
            if not domain and not url:
                continue
            if not url:
                url = 'https://{}:443'.format(domain)
            domain = urlparse(url).netloc.split(':')[0]
            # store the domain and name in the kv
            ct = self.container_name(service)
            port = self.port(service)
            proto = self.proto(service)
            value = {
                'domain': domain,  # deprecated, don't use (domain is the key)
                'url': url,
                'tls': tls,
                'node': target,
                'slave': slave,
                'ip': self.members()[target]['ip'],
                'ct': '{proto}{ct}:{port}'.format(**locals())}
            cmd = ("consul kv put site/{} '{}'"
                   .format(domain, json.dumps(value)))
            self.do(cmd, runintest=False)
            log.info("Registered %s", cmd)

    def register_consul(self):
        """register a service in consul
        """
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
        return self.do("docker volume rm {}".format(self.volume))

    def restore(self, snapshot=None):
        if snapshot is None:  # use the latest snapshot
            snapshot = self.volume
        self.do("buttervolume restore {}".format(snapshot))

    def send(self, snapshot, target):
        self.do("buttervolume send {} {}".format(target, snapshot))


def handle_one(event, hostname, test=False):
    event_name = event.get('Name')
    payload = event.get('Payload')
    if not payload:
        return
    if event_name == 'deploymaster':
        deploymaster(b64decode(payload), hostname, test)
    else:
        log.error('Unknown event name: {}'.format(event_name))


def handle(events, hostname, test=False):
    for event in json.loads(events):
        handle_one(event, hostname, test)


def deploymaster(payload, hostname, test):
    """Keep in mind this is executed in the consul container
    Deployments are done in the DEPLOY folder.
    Any remaining stuff in this folder are a sign of a failed deploy
    """
    # check
    try:
        if len(payload.split()) == 2:  # just target
            target = payload.split()[0].decode()
            slave = None
            repo_url = payload.split()[1].decode()
        elif len(payload.split()) == 3:  # target + slave
            target = payload.split()[0].decode()
            slave = payload.split()[1].decode()
            repo_url = payload.split()[2].decode()
        else:
            raise Exception
    except Exception as e:
        log.error('deploymaster error: '
                  'you should specify "<target> <repo>" '
                  'or "<target> <slave> <repo>"')
        raise(e)
    app = Application(repo_url, test=test)
    master_node = app.master_node
    if hostname == target:
        app.fetch()
        oldslave = app.slave_node
        master_node = app.master_node
        time.sleep(2)
        for volume in app.volumes:
            if oldslave is not None:
                volume.schedule_replicate(0, app.members()[oldslave]['ip'])
            volume.schedule_snapshots(0)
        if master_node is not None and master_node != hostname:
            app.wait_lock()
            for volume in app.volumes:
                volume.restore()
        for volume in app.volumes:
            if slave is not None:
                volume.schedule_replicate(60, app.members()[slave]['ip'])
            else:
                volume.schedule_snapshots(60)
        app.register_kv(target, slave, hostname)  # for consul-template
        app.register_consul()  # for consul check
        app.start()
    elif hostname == master_node:
        app.lock()
        # first replicate live to lower downtime
        for volume in app.volumes:
            volume.schedule_snapshots(0)
            oldslave = app.slave_node
            if oldslave is not None:
                volume.schedule_replicate(0, app.members()[oldslave]['ip'])
            volume.send(volume.snapshot(), app.members()[target]['ip'])
        # then stop and replicate again (should be faster)
        app.stop()
        for volume in app.volumes:
            volume.send(volume.snapshot(), app.members()[target]['ip'])
        app.unlock()
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
    hostname = socket.gethostname()
    # read json from stdin
    handle(stdin.read(), hostname, test)
