#!/usr/bin/python3
# coding: utf-8
import json
import logging
import requests
import socket
from base64 import b64decode
from os.path import basename
from subprocess import run, CalledProcessError, PIPE
from sys import stdin, argv
logging.basicConfig()
log = logging.getLogger(__name__)
DEPLOY = '/deploy'


class Do(object):
    """Chain several commands (in a shell or as a function)
    """
    def __init__(self, cmd, test=False, cwd=None):
        self.test = test
        self.cwd = cwd
        self.then(cmd, cwd)

    def then(self, cmd, cwd=None):
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
        cwd = cwd or self.cwd
        self.cwd = cwd
        try:
            if cwd:
                cmd = 'cd "{}" && {}'.format(cwd, cmd)
            if self.test:
                cmd = "echo '{}'".format(cmd)
            out = run(cmd, shell=True, check=True, stderr=PIPE, stdout=PIPE)
        except CalledProcessError as e:
            log.error("Failed to run %s: %s", e.cmd, e.stderr.decode())
            raise
        print(out.stdout.decode().strip())
        return self


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
    @staticmethod
    def register_service(name):
        def func():
            try:
                path = '{}/{}/service.json'.format(DEPLOY, name)
                with open(path) as f:
                    compose = f.read()
            except Exception as e:
                log.error('Could not read %s', path)
                raise
            requests.post('http://localhost:8500/v1/agent/register/service',
                          json.dumps(json.loads(compose)))
        return func


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
    except Exception as e:
        log.error('deploymaster error: '
                  'you should specify a hostname and repository')
        raise(e)
    # ACTIONS
    if host == target:
        Do('rm -rf "{}/{}"'.format(DEPLOY, name), cwd=DEPLOY, test=test) \
          .then('git clone "{}"'.format(repo)) \
          .then('docker-compose up -d', cwd='{}/{}'.format(DEPLOY, name)) \
          .then('rm -rf "{}/{}"'.format(DEPLOY, name), cwd=DEPLOY) \
          .then('buttervolume snapshot {}'.format(name)) \
          .then('buttervolume schedule snapshot {} 60') \
          .then(Consul.register_service(name))
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
