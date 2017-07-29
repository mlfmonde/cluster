#!/usr/bin/env python3

import json
import socket
from subprocess import run, PIPE
from urllib.parse import urlparse


def apps():
    cmd = "consul kv get --recurse app/"
    res = run(cmd, shell=True, check=True, stdout=PIPE, stderr=PIPE)
    return res.stdout.decode('utf-8').strip().splitlines()


for app in apps():
    data = json.loads(app.split(':', 1)[1])
    pubkeys = data.get('pubkey')
    cts = data.get('ct')
    domain = data.get('domain')
    ip = data.get('ip')
    target = data.get('master')
    myself = socket.gethostname()
    if not pubkeys:
        continue

    for s, ct in cts.items():
        pubkey = pubkeys[s]
        if pubkey.strip() and '\n' not in pubkey:
            if myself == target:
                print('command="docker exec -it {ct} bash" {pubkey}'
                      .format(**locals()))
            else:
                print('command="ssh -At gw@{ip}" {pubkey}'.format(**locals()))
