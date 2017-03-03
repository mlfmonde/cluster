#!/usr/bin/python3
# coding: utf-8
import json
import logging
import requests
import socket
from base64 import b64decode
from os.path import basename, join
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


class Repository(object):
    """commands
    """
    def __init__(self, url, cwd=None, test=False):
        self.test = test
        self.url = url
        self.cwd = cwd
        name = basename(url.strip('/'))
        self.name = name[:-4] if name.endswith('.git') else name
        self.path = join(DEPLOY, self.name)

    def run(self, cmd, cwd=None, runintest=True):
        return _run(cmd, cwd=cwd, test=self.test and not runintest)

    def services(self):
        out = self.run('docker-compose config --services', cwd=self.path)
        return [s.strip() for s in out.split('\n')]

    def containers(self):
        return concat(
            [self.run('docker-compose ps -q {}'
                      .format(s), cwd=self.path).split('\n')
             for s in self.services()])

    def inspects(self):
        return concat(
            [json.loads(self.run('docker inspect {}'.format(c)))
             for c in self.containers()])

    def volumes(self):
        """return all the volumes of a running compose
        """
        return [Volume(m['Name'], test=self.test) for m in concat([c['Mounts']
                for c in self.inspects()]) if m['Driver'] == 'btrfs']

    def clean(self):
        self.run('rm -rf "{}"'.format(self.path))

    def fetch(self):
        self.run('git clone "{}"'.format(self.url), cwd=DEPLOY)

    def start(self):
        log.info("Starting the project %s", self.name)
        self.run('docker-compose up -d', cwd=self.path)

    def _members(self):
        if not self.test:
            return self.run('consul members')
        else:
            return (
                'Node   Address            Status  Type       DC\n'
                'edjo   10.91.210.58:8301  alive   server     dc1\n'
                'nepri  10.91.210.57:8301  alive   server     dc1\n'
                'tayt   10.91.210.59:8301  alive   server     dc1')

    def members(self):
        members = {}
        for m in self._members().split('\n')[2:]:
            name, ip, status = m.split()[:3]
            members[name] = {'ip': ip.split(':')[0], 'status': status}
        return members

    def site_url(self, service):
        return self.run("docker-compose exec -T {} sh -c 'echo $URL'"
                        .format(service), cwd=self.path)

    def ps(self, service):
        ps = self.run('docker-compose ps {}'.format(service), cwd=self.path)
        return ps.split('\n')[-1].split()

    def register_kv(self, target, hostname):
        """register a service in the kv store
        so that consul-template can regenerate the
        caddy and haproxy conf files
        """
        # get the configured URL directly in the container
        log.info("Registering URLs of %s in the kv store", self.name)
        for service in self.services():
            site_url = self.site_url(service)
            if not site_url:
                continue
            container_name, _, state = self.ps(service)
            if state == 'Up':
                # store the url and name in the kv
                value = {
                    'url': site_url,
                    'node': target,
                    'ip': self.members()[target]['ip'],
                    'ct': container_name}
                cmd = ("consul kv delete site/{}".format(site_url))
                self.run(cmd, runintest=False)
                cmd = ("consul kv put site/{} '{}'"
                       .format(site_url, json.dumps(value)))
                self.run(cmd, runintest=False)
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

    def run(self, cmd, cwd=None):
        return _run(cmd, cwd=cwd, test=self.test)

    def snapshot(self):
        """snapshot all volumes of a running compose
        """
        self.run("buttervolume snapshot {}".format(self.volume))

    def schedule_snapshots(self, timer):
        """schedule snapshots of all volumes of a running compose
        """
        self.run("buttervolume schedule snapshot {} {}"
                 .format(timer, self.volume))


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
                  'you should specify a hostname and URL')
        raise(e)
    # deploy
    if hostname == target:
        repo = Repository(repo_url, test=test)
        repo.clean()
        repo.fetch()
        repo.start()
        for volume in repo.volumes():
            volume.snapshot()
            volume.schedule_snapshots(60)
        repo.register_kv(target, hostname)  # for consul-template
        repo.register_consul()  # for consul check
    else:
        print("No action")


if __name__ == '__main__':
    # test mode?
    try:
        test = argv[0] == 'test'
    except:
        test = False
    # hostname?
    hostname = socket.gethostname()
    # read json from stdin
    handle(stdin.read(), hostname, test)
