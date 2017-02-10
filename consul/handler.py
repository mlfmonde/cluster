#!/usr/bin/python3
# coding: utf-8
import socket
from base64 import b64decode
import logging
from sys import stdin, argv
from subprocess import run, CalledProcessError, PIPE
import json
logging.basicConfig()
log = logging.getLogger(__name__)


def do(command, test):
    try:
        if test:
            command = "echo '{}'".format(command)
        out = run(command, shell=True, check=True, stderr=PIPE, stdout=PIPE)
    except CalledProcessError as e:
        log.warning("Error running {}: {}".format(e.cmd, e.stderr.decode()))
        return
    print(out.stdout.decode())


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
    except Exception as e:
        log.error('deploymaster error: '
                  'you should specify a hostname and repository')
        raise(e)
    if host == target:
        do("cd /tmp "
           "&& rm -rf repo"
           "&& git clone {} repo"
           "&& cd repo" 
           "&& docker-compose up -d"
           "&& cd .. && rm -rf repo"
           .format(repo), test)
    else:
        do("No action", test)


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
