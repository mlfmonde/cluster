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
logging.basicConfig(level=logging.DEBUG)
log = logging.getLogger(__name__)
DEPLOY = '/deploy'


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
    def __init__(self, hostname, url, test=False, cwd=None):
        self.hostname = hostname
        self.url = url
        self.cwd = cwd
        self.test = test
        name = basename(url.strip('/'))
        self.name = name[:-4] if name.endswith('.git') else name
        self.path = join(DEPLOY, self.name)

    def run(self, cmd, cwd=None):
        return _run(cmd, cwd=cwd, test=self.test)

    def volumes(self):
        """return all the volumes of a running compose
        """
        out = self.run('docker-compose config --services', cwd=self.path)
        services = [s.strip() for s in out.split('\n')]
        containers = concat(
            [self.run('docker-compose ps -q {}'
                      .format(s), cwd=self.path).split('\n')
             for s in services])
        inspects = concat(
            [json.loads(_run('docker inspect {}'.format(c)))
             for c in containers])
        volumes = [Volume(m['Name']) for m in concat([c['Mounts']
                   for c in inspects]) if m['Driver'] == 'btrfs']
        return volumes

    def clean(self):
        self.run('rm -rf "{}"'.format(self.path))

    def fetch(self):
        self.run('git clone "{}"'.format(self.url), cwd=DEPLOY)

    def start(self):
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
        for m in self._members()[1:]:
            name, ip, status = m[:2]
            members[name] = {'ip': ip.split(':')[0], 'status': status}

    def update_haproxy(self):
        #members = self.members()
        # template + ip master + url → fichier haproxy.cfg + haproxy.cfg.old → restart haproxy → si fail, reprendre le old.
        pass

    def register_consul(self):
        """register a service in consul
        """
        try:
            path = '{}/service.json'.format(self.path)
            compose = '{}'
            if not self.test:
                with open(path) as f:
                    compose = f.read()
        except Exception:
            log.error('Could not read %s', path)
            raise
        url = 'http://localhost:8500/v1/agent/service/register'
        svc = json.dumps(json.loads(compose))
        if self.test:
            print('POST', url, svc)
        else:
            res = requests.post(url, svc)
            if res.status_code != 200:
                raise RuntimeError('Consul service register failed: {}'
                                   .format(res.reason))


class Volume(object):
    """wrapper for buttervolume
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
        project = Repository(hostname, repo_url, test=test)
        project.clean()
        project.fetch()
        project.start()
        for volume in project.volumes():
            volume.snapshot()
            volume.schedule_snapshots(60)
        project.update_haproxy()
        project.register_consul()
        project.clean()
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
