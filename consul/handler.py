#!/usr/bin/python3
# coding: utf-8
import socket
from base64 import b64decode
import logging
from sys import stdin, argv
from subprocess import run, CalledProcessError, PIPE
from os.path import basename
import json
logging.basicConfig()
log = logging.getLogger(__name__)


class Do(object):
    """Chain several commands
    """
    def __init__(self, cmd, test=False, cwd=None):
        self.test = test
        self.cwd = cwd
        self.then(cmd, cwd)

    def then(self, cmd, cwd=None):
        cwd = cwd or self.cwd
        self.cwd = cwd
        try:
            if cwd:
                cmd = 'cd "{}" && {}'.format(cwd, cmd)
            if self.test:
                cmd = "echo '{}'".format(cmd)
            out = run(cmd, shell=True, check=True, stderr=PIPE, stdout=PIPE)
        except CalledProcessError as e:
            log.error("Failed to run {}: {}".format(e.cmd, e.stderr.decode()))
            return None  # TODO
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


def deploymaster(payload, host, test):
    try:
        target = payload.split()[0].decode()
        repo = payload.split()[1].decode()
        name = basename(repo.strip('/'))
        name = name[:-4] if name.endswith('.git') else name
    except Exception as e:
        log.error('deploymaster error: '
                  'you should specify a hostname and repository')
        raise(e)
    if host == target:
        Do('rm -rf "/deploy/{}"'.format(name), cwd='/deploy', test=test) \
          .then('git clone {}'.format(repo)) \
          .then('docker-compose up -d', cwd='/deploy/{}'.format(name)) \
          .then('rm -rf "/deploy/{}"'.format(name), cwd='/deploy')
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
