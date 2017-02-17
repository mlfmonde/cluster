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


def run(cmd):
    return srun(cmd, shell=True, check=True, stdout=PIPE, stderr=PIPE)


def concat(xs):
    return [y for x in xs for y in x]


class Do(object):
    """Chain several commands (in a shell or as a function)
    """
    def __init__(self, cmd, test=False, cwd=None):
        self.test = test
        self.cwd = cwd
        self.then(cmd, cwd)

    def then(self, cmd, cwd=None):
        # cmd is a function
        if hasattr(cmd, '__call__'):
            try:
                if self.test:
                    fname = cmd.__qualname__.rsplit('.', 2)[0]
                    print('run function: {}'.format(fname))
                else:
                    cmd()
            except Exception as e:
                log.error("Failed to run %s: %s",
                          cmd.__name__, str(e))
                raise
            return self
        # cmd is a shell instruction
        cwd = cwd or self.cwd
        self.cwd = cwd
        try:
            if cwd:
                cmd = 'cd "{}" && {}'.format(cwd, cmd)
            if self.test:
                cmd = "echo '{}'".format(cmd)
            print(cmd)
            print(run(cmd).stdout.decode().strip())
            return self
        except CalledProcessError as e:
            log.error("Failed to run %s: %s", e.cmd, e.stderr.decode())
            raise


def handle_one(event, host, test=False):
    name = event.get('Name')
    payload = event.get('Payload')
    if not payload:
        return
    if name == 'deploymaster':
        deploymaster(b64decode(payload), host, test)
    else:
        log.error('Unknown event name: {}'.format(name))


def handle(events, host, test=False):
    for event in json.loads(events):
        handle_one(event, host, test)


class Consul(object):
    """consul http endpoint wrapper for the Do class
    """
    def register_service(self, project):
        """register a service in consul
        """
        def closure():
            try:
                path = '{}/service.json'.format(project)
                with open(path) as f:
                    compose = f.read()
            except Exception as e:
                log.error('Could not read %s', path)
                raise
            requests.post('http://localhost:8500/v1/agent/register/service',
                          json.dumps(json.loads(compose)))
        return closure


class DockerCompose(object):
    """run commands against all volumes of a compose
    """
    def __init__(self, project):
        self.project = project

    def _volumes(self, path):
        """return all the volumes of a running compose
        """
        out = run('cd "{}" && docker-compose config --services'.format(path))
        services = [s.strip() for s in out.stdout.decode().split('\n')]
        containers = concat(
            [run('cd "{}" && docker-compose ps -q {}'
                 .format(self.project, s)).stdout.strip().decode().split('\n')
             for s in services])
        print(containers)
        inspects = concat(
            [json.loads(run('docker inspect {}'.format(c)).stdout.decode())
             for c in containers])
        volumes = [m['Name'] for m in concat([c['Mounts']
                   for c in inspects]) if m['Driver'] == 'btrfs']
        return volumes

    def snapshot(self):
        """snapshot all volumes of a running compose
        """
        def closure():
            try:
                for volume in self._volumes(self.project):
                    run("buttervolume snapshot {}".format(volume))
            except CalledProcessError as e:
                log.error("Failed to run %s: %s", e.cmd, e.stderr.decode())
                raise
        return closure

    def schedule_snapshots(self, timer):
        """schedule snapshots of all volumes of a running compose
        """
        def closure():
            try:
                for volume in self._volumes(self.project):
                    run("buttervolume schedule snapshot {} {}"
                        .format(timer, volume))
            except CalledProcessError as e:
                log.error("Failed to run %s: %s", e.cmd, e.stderr.decode())
                raise
        return closure


def deploymaster(payload, host, test):
    """Keep in mind this is executed in the consul container
    Deployments are done in the DEPLOY folder.
    Any remaining stuff in this folder are a sign of a failed deploy
    """
    # CHECKS
    try:
        target = payload.split()[0].decode()
        repo = payload.split()[1].decode()
        name = basename(repo.strip('/'))
        name = name[:-4] if name.endswith('.git') else name
        project = join(DEPLOY, name)
    except Exception as e:
        log.error('deploymaster error: '
                  'you should specify a hostname and repository')
        raise(e)
    # CHAINED ACTIONS
    if host == target:
        Do('rm -rf "{}"'.format(project), cwd=DEPLOY, test=test) \
         .then('git clone "{}"'.format(repo)) \
         .then('docker-compose up -d', cwd=project) \
         .then(DockerCompose(project).snapshot()) \
         .then(DockerCompose(project).schedule_snapshots(60)) \
         .then(Consul().register_service(project)) \
         .then('rm -rf "{}"'.format(project), cwd=DEPLOY)
    else:
        Do("No action", test)


if __name__ == '__main__':
    # test mode?
    try:
        test = argv[0] == 'test'
    except:
        test = False
    # hostname?
    host = socket.gethostname()
    # read json from stdin
    handle(stdin.read(), host, test)
