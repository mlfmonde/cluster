#!/usr/bin/python3
# coding: utf-8
import json
import logging
import requests
import socket
import time
import yaml
from base64 import b64decode
from os.path import basename, join, exists
from subprocess import run as srun, CalledProcessError, PIPE
from sys import stdin, argv
DEPLOY = '/deploy'
logging.basicConfig(level=logging.DEBUG, filename=join(DEPLOY, 'handler.log'))
log = logging.getLogger(__name__)


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
            res = srun(cmd, shell=True, check=True, stdout=PIPE, stderr=PIPE)
            out = res.stdout.decode().strip()
            return out
    except CalledProcessError as e:
        log.error("Failed to run %s: %s", e.cmd, e.stderr.decode())
        raise


class Application(object):
    """commands
    """
    def __init__(self, url, cwd=None, test=False):
        self.test = test  # for unit tests
        self.url = url  # of the git repository
        name = basename(url.strip('/'))
        self.name = name[:-4] if name.endswith('.git') else name  # repository
        self.path = join(DEPLOY, self.name)  # path of the checkout
        self._services = None
        self._containers = None
        self._inspects = None
        self._volumes = None
        self._lock = False

    def do(self, cmd, cwd=None, runintest=True):
        log.info(cmd)
        return _run(cmd, cwd=cwd, test=self.test and not runintest)

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
        log.info('Waited too much :(')

    @property
    def services(self):
        """name of the services in the compose file
        """
        if self._services is None:
            out = self.do('docker-compose config --services', cwd=self.path)
            self._services = [s.strip() for s in out.split('\n')]
        return self._services

    @property
    def containers(self):
        """name of the running containers
        """
        if self._containers is None:
            self._containers = concat(
                [self.do('docker-compose ps -q {}'
                         .format(s), cwd=self.path).split('\n')
                 for s in self.services])
        return self._containers

    @property
    def inspects(self):
        """inspect data of the containers
        """
        if self._inspects is None:
            self._inspects = concat(
                [json.loads(self.do('docker inspect {}'.format(c)))
                 for c in self.containers if c.strip()])
        return self._inspects

    @property
    def volumes(self):
        """active volumes of the running app
        """
        if self._volumes is None:
            self._volumes = [
                Volume(m['Name'], test=self.test)
                for m in concat([c['Mounts'] for c in self.inspects])
                if m['Driver'] == 'btrfs']
        return self._volumes

    @property
    def active_node(self):
        """active node for the current app
        """
        domains = [self.domain(s) for s in self.services]
        domains = [d for d in domains if d is not None]
        domain = domains[0] if domains else ''
        try:
            cmd = 'consul kv get site/{}'.format(domain)
            return json.loads(self.do(cmd))['node']
        except:
            log.warn('Could not determine the active node for %s', domain)
            return None

    def clean(self):
        self.do('rm -rf "{}"'.format(self.path))

    def fetch(self, retrying=False):
        try:
            if not exists(self.path):
                self.do('git clone "{}"'.format(self.url), cwd=DEPLOY)
            else:
                self.do('git pull', cwd=self.path)
        except CalledProcessError:
            if not retrying:
                log.warn("Failed to fetch %s, retrying", self.name)
                self.fetch(retrying=True)
            else:
                raise

    def start(self):
        log.info("Starting the project %s", self.name)
        self.do('docker-compose up -d', cwd=self.path)

    def stop(self):
        log.info("Stopping the project %s", self.name)
        self.do('docker-compose down', cwd=self.path)

    def _members(self):
        if not self.test:
            return self.do('consul members')
        else:
            return (
                'Node   Address            Status  Type       DC\n'
                'edjo   10.91.210.58:8301  alive   server     dc1\n'
                'nepri  10.91.210.57:8301  alive   server     dc1\n'
                'tayt   10.91.210.59:8301  alive   server     dc1')

    def members(self):
        members = {}
        for m in self._members().split('\n')[1:]:
            name, ip, status = m.split()[:3]
            members[name] = {'ip': ip.split(':')[0], 'status': status}
        return members

    def domain(self, service):
        """DOMAIN configured in the compose for the service
        """
        try:
            with open(join(self.path, 'docker-compose.yml')) as c:
                compose = yaml.load(c.read())
        except:
            raise EnvironmentError('Could not read docker-compose.yml file')
        try:
            return compose['services'][service]['environment']['DOMAIN']
        except:
            log.warn('Could not find a DOMAIN env var in the compose file')

    def ps(self, service):
        ps = self.do('docker-compose ps {}'.format(service), cwd=self.path)
        return ps.split('\n')[-1].split()

    def register_kv(self, target, hostname):
        """register a service in the kv store
        so that consul-template can regenerate the
        caddy and haproxy conf files
        """
        log.info("Registering URLs of %s in the kv store", self.name)
        for service in self.services:
            domain = self.domain(service)
            if not domain:
                continue
            container_name, _, state = self.ps(service)
            if state == 'Up':
                # store the domain and name in the kv
                value = {
                    'domain': domain,
                    'node': target,
                    'ip': self.members()[target]['ip'],
                    'ct': container_name}
                cmd = ("consul kv put site/{} '{}'"
                       .format(domain, json.dumps(value)))
                self.do(cmd, runintest=False)
                log.info("Registered %s", cmd)
            else:
                raise RuntimeError('%s deployment failed', self.name)

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
        """snapshot all volumes of a running compose
        """
        return self.do("buttervolume snapshot {}".format(self.volume))

    def schedule_snapshots(self, timer):
        """schedule snapshots of all volumes of a running compose
        """
        self.do("buttervolume schedule snapshot {} {}"
                .format(timer, self.volume))

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
        target = payload.split()[0].decode()
        repo_url = payload.split()[1].decode()
    except Exception as e:
        log.error('deploymaster error: '
                  'you should specify a hostname and repository URL')
        raise(e)

    app = Application(repo_url, test=test)
    if hostname == target:
        app.fetch()
        app.wait_lock()
        for volume in app.volumes:
            volume.restore()
        app.start()
        for volume in app.volumes:
            volume.schedule_snapshots(60)
        app.register_kv(target, hostname)  # for consul-template
        app.register_consul()  # for consul check
    elif hostname == app.active_node:
        app.lock()
        # first replicate live to lower downtime
        for volume in app.volumes:
            volume.schedule_snapshots(0)
            volume.send(volume.snapshot(), app.members()[target]['ip'])
        # then stop and replicate again (should be faster)
        app.stop()
        for volume in app.volumes:
            volume.send(volume.snapshot(), app.members()[target]['ip'])
        app.unlock()
        for volume in app.volumes:
            volume.delete()


if __name__ == '__main__':
    try:  # test mode?
        test = argv[0] == 'test'
    except:
        test = False
    hostname = socket.gethostname()
    # read json from stdin
    handle(stdin.read(), hostname, test)
