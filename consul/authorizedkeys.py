#!/usr/bin/env python3

import json
import socket
from subprocess import run, PIPE
from urllib.parse import urlparse


def apps():
    cmd = "consul kv get --recurse app/"
    res = run(cmd, shell=True, check=True, stdout=PIPE, stderr=PIPE)
    return res.stdout.decode().strip().splitlines()


for app in apps():
    data = json.loads(app.split(':', 1)[1])
    pubkey = data.get('pubkey')
    ct = urlparse(data.get('ct')).hostname
    domain = data.get('domain')
    ip = data.get('ip')
    target = data.get('node')
    myself = socket.gethostname()
    if not pubkey:
        continue

    if myself == target:
        print('command="docker exec -it {ct} bash" {pubkey}'
              .format(**locals()))
    else:
        print('command="ssh -At gw@{ip}" {pubkey}'.format(**locals()))
