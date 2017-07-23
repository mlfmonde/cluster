#!/usr/bin/env python3
# coding: utf-8
import hashlib
import json
import logging
import os
import re
import requests
import socket
import time
import unittest
import yaml
from base64 import b64decode, b64encode
from contextlib import contextmanager
from datetime import datetime
from functools import reduce
from os.path import basename, join, exists, dirname
from shutil import copy, rmtree
from subprocess import run, CalledProcessError, PIPE
from sys import stdin, argv
from urllib.parse import urlparse
from uuid import uuid1
DTFORMAT = "%Y-%m-%dT%H:%M:%S.%f"
DEPLOY = '/deploy'
CADDYLOGS = '/var/log'
TEST = False
HERE = dirname(__file__)
log = logging.getLogger()


def do(cmd, cwd=None):
    """ Run a command"""
    cmd = argv[0] + ' ' + cmd if TEST else cmd
    try:
        if cwd and not TEST:
            cmd = 'cd "{}" && {}'.format(cwd, cmd)
        log.info('Running: ' + cmd)
        res = run(cmd, shell=True, check=True, stdout=PIPE, stderr=PIPE)
        return res.stdout.decode().strip()
    except CalledProcessError as e:
        log.error("Failed to run %s: %s", e.cmd, e.stderr.decode())
        raise e


def kv(name, key):
    """ return the current value of the key in the kv"""
    try:
        cmd = 'consul kv get app/{}'.format(name)
        value = json.loads(do(cmd), strict=False)[key]
        return value
    except Exception as e:
        log.warning('Could not read the key "%s" in the KV for %s: %s',
                    key, name, str(e))
        return None


class Application(object):
    """ represents a docker compose, its proxy conf and deployment path
    """
    def __init__(self, repo_url, branch, cwd=None):
        self.repo_url, self.branch = repo_url.strip().lower(), branch.strip()
        if self.repo_url.endswith('.git'):
            self.repo_url = self.repo_url[:-4]
        md5 = hashlib.md5(urlparse(self.repo_url).path.encode('utf-8')
                          ).hexdigest()
        repo_name = basename(self.repo_url.strip('/'))
        self.name = repo_name + ('_' + self.branch if self.branch else ''
                                 ) + '.' + md5[:5]  # don't need full md5
        self._services = None
        self._volumes = None
        self._compose = None
        self._deploy_date = None
        self._caddy = {}

    @property
    def deploy_date(self):
        """date of the last deployment"""
        if self._deploy_date is None:
            self._deploy_date = kv(self.name, 'deploy_date')
        return self._deploy_date

    def _path(self, deploy_date=None):
        """path of the deployment checkout"""
        deploy_date = deploy_date or self.deploy_date
        if deploy_date:
            return join(DEPLOY, self.name + '@' + deploy_date)
        return None

    @property
    def path(self):
        return self._path()

    def check(self):
        """consistency check"""
        all_apps = {
            s['key']: json.loads(
                b64decode(s['value']).decode('utf-8'), strict=False)
            for s in json.loads(do('consul kv export app/'))}
        # check urls are not already used
        for service in self.services:
            try:
                caddy = self.caddyfile(service)
            except Exception as e:
                log.error("Invalid CADDYFILE: %s", str(e))
                raise
            caddy_urls = reduce(list.__add__,
                                [c['keys'] for c in caddy], [])
            for appname, appconf in all_apps.items():
                app_urls = reduce(
                    list.__add__,
                    [c['keys'] for c in
                     Caddyfile.loads(
                        appconf.get('caddyfile', {'keys': []}))])
                if appname == self.name:
                    continue
                for url in caddy_urls:
                    if url in app_urls:
                        msg = ('Aborting! {} is already deployed by {}'
                               .format(url, appname))
                        log.error(msg)
                        raise ValueError(msg)

    @property
    def compose(self):
        """read the compose file
        """
        if self._compose is None:
            try:
                with open(join(self.path, 'docker-compose.yml')) as c:
                    self._compose = yaml.load(c.read())
            except Exception as e:
                log.error('Could not read docker-compose.yml: %s', str(e))
                raise
        return self._compose

    @contextmanager
    def notify_transfer(self):
        try:
            yield
            do('consul kv put migrate/{}/success'.format(self.name))
        except Exception as e:
            log.error('Volume migrate FAILED! : %s', str(e))
            do('consul kv put migrate/{}/failure'.format(self.name))
            self.up()  # TODO move in the deploy
            raise
        log.info('Volume migrate SUCCEEDED!')

    def wait_transfer(self):
        loops = 0
        while loops < 60:
            log.info('Waiting migrate notification for %s', self.name)
            res = do('consul kv get -keys migrate/{}'.format(self.name))
            if res:
                status = res.split('/')[-1]
                do('consul kv delete -recurse migrate/{}/'
                   .format(self.name))
                log.info('Transfer notification status: %s', status)
                return status
            time.sleep(1)
            loops += 1
        msg = ('Waited too much :( Master did not send a notification for %s')
        log.info(msg, self.name)
        raise RuntimeError(msg % self.name)

    @property
    def services(self):
        """name of the services in the compose file
        """
        if self._services is None:
            self._services = self.compose['services'].keys()
        return self._services

    @property
    def project(self):
        return re.sub(r'[^a-z0-9]', '', self.name)

    @property
    def volumes_from_kv(self):
        """volumes defined in the kv
        """
        if self._volumes is None:
            try:
                self._volumes = [
                    Volume(v) for v in kv(self.name, 'volumes')]
            except:
                log.info("No volumes found in the kv")
            self._volumes = self._volumes or None
        return self._volumes

    @property
    def volumes(self):
        """btrfs volumes defined in the compose
        """
        if self._volumes is None:
            try:
                self._volumes = [
                    Volume(self.project + '_' + v[0])
                    for v in self.compose.get('volumes', {}).items()
                    if v[1] and v[1].get('driver') == 'btrfs']
            except:
                log.info("No volumes found in the compose")
                self._volumes = []
        return self._volumes

    def container_name(self, service):
        """did'nt find a way to query reliably so do it static
        It assumes there is only 1 container for a project/service couple
        """
        return self.project + '_' + service + '_1'  # FIXME _1

    def clean(self):
        if self.path and exists(self.path):
            do('rm -rf "{}"'.format(self.path))

    def download(self, retrying=False):
        try:
            self.clean()
            deploy_date = datetime.now().strftime(DTFORMAT)
            path = self._path(deploy_date)
            do('git clone --depth 1 {} "{}" "{}"'
               .format('-b "%s"' % self.branch if self.branch else '',
                       self.repo_url, path),
               cwd=DEPLOY)
            self._deploy_date = deploy_date
            self._services = None
            self._volumes = None
            self._compose = None
        except CalledProcessError:
            if not retrying:
                log.warning("Failed to download %s, retrying", self.repo_url)
                self.download(retrying=True)
            else:
                raise

    def up(self):
        if self.path and exists(self.path):
            log.info("Starting %s", self.name)
            do('docker-compose -p "{}" up -d --build'
               .format(self.project),
               cwd=self.path)
        else:
            log.info("No deployment, cannot start %s", self.name)

    def down(self, deletevolumes=False):
        if self.path and exists(self.path):
            log.info("Stopping %s", self.name)
            v = '-v' if deletevolumes else ''
            do('docker-compose -p "{}" down {}'.format(self.project, v),
               cwd=self.path)
        else:
            log.info("No deployment, cannot stop %s", self.name)

    @property
    def members(self):
        members = {}
        for m in do('consul members').split('\n')[1:]:
            name, ip, status = m.split()[:3]
            members[name] = {'ip': ip.split(':')[0], 'status': status}
        return members

    def caddyfile(self, service):
        """retrieve the caddyfile config from the compose
        and add defaults values
        """
        # read the caddyfile of the service
        if self._caddy.get(service) is None:
            try:
                name = 'CADDYFILE'
                caddy = self.compose['services'][service]['environment'][name]
            except Exception:
                log.info('No %s environment variable for '
                         'service %s in the compose file of %s',
                         name, service, self.name)
                self._caddy[service] = []
                return self._caddy[service]
            try:
                log.info('Found a %s environment variable for '
                         'service %s in the compose file of %s',
                         name, service, self.name)
                self._caddy[service] = Caddyfile.loads(
                    caddy.replace('$CONTAINER', self.container_name(service)))
            except Exception as e:
                log.info('Invalid %s environment variable for '
                         'service %s in the compose file of %s: %s',
                         name, service, self.name, str(e))

        for host in self._caddy[service]:
            dirs = host['body']
            # default or forced values
            Caddyfile.setdir(dirs, ['gzip'])
            Caddyfile.setdir(dirs, ['timeouts', '300s'])
            Caddyfile.setdir(dirs, ['proxyprotocol', '0.0.0.0/0'])
            Caddyfile.setsubdirs(
                dirs, 'proxy',
                ['transparent', 'websocket', 'insecure_skip_verify'],
                replace=True)
            Caddyfile.setdir(
                dirs,
                ['log', join(CADDYLOGS, self.name + '.access.log'),
                 [['rotate_size', '100'],
                  ['rotate_age', '14'],
                  ['rotate_keep', '10']]],
                replace=True)
        return self._caddy[service] or []

    def ps(self, service):
        ps = do('docker ps -f name=%s --format "table {{.Status}}"'
                % self.container_name(service))
        return ps.split('\n')[-1].strip()

    def register_kv(self, target, slave):
        """register services in the key/value store
        so that consul-template can regenerate the
        caddy and haproxy conf files
        """
        log.info("Registering URLs of %s in the key/value store",
                 self.name)
        for service in self.services:
            caddy = self.caddyfile(service)
            if not caddy:
                continue  # no need?
            value = {
                'caddyfile': Caddyfile.dumps(caddy),
                'repo_url': self.repo_url,
                'branch': self.branch,
                'deploy_date': self._deploy_date,
                'ip': self.members[target]['ip'],
                'master': target,
                'slave': slave,
                'ct': self.container_name(service),
                'volumes': [v.name for v in self.volumes]}

            do("consul kv put app/{} '{}'"
               .format(self.name, json.dumps(value)))
            log.info("Registered %s", self.name)

    def unregister_kv(self):
        do("consul kv delete app/{}".format(self.name))

    def register_consul(self):
        """register a service and check in consul
        """
        urls = reduce(list.__add__,
                      [self.caddyfile(s)['urls'].keys() for s in self.services
                       if self.caddyfile(s)['urls']])
        svc = json.dumps({
            'Name': self.name,
            'Checks': [{
                'HTTP': url,
                'Interval': '60s'} for url in urls if url]})
        url = 'http://localhost:8500/v1/agent/service/register'
        res = requests.post(url, svc)
        if res.status_code != 200:
            msg = 'Consul service register failed: {}'.format(res.reason)
            log.error(msg)
            raise RuntimeError(msg)
        log.info("Registered %s in consul", self.name)

    def unregister_consul(self):
        res = requests.put(
            'http://localhost:8500/v1/agent/service/deregister/{}'
            .format(self.name))
        if res.status_code != 200:
            msg = 'Consul service deregister failed: {}'.format(res.reason)
            log.error(msg)
            raise RuntimeError(msg)
        log.info("Deregistered %s in consul", self.name)

    def enable_snapshot(self, enable):
        """enable or disable scheduled snapshots
        """
        for volume in self.volumes_from_kv:
            volume.schedule_snapshots(60 if enable else 0)

    def enable_replicate(self, enable, ip):
        """enable or disable scheduled replication
        """
        for volume in self.volumes_from_kv:
            volume.schedule_replicate(60 if enable else 0, ip)

    def enable_purge(self, enable):
        for volume in self.volumes_from_kv:
            volume.schedule_purge(1440 if enable else 0, '1h:1d:1w:4w:1y')


class Volume(object):
    """wrapper for buttervolume cli
    """
    def __init__(self, name):
        self.name = name

    def snapshot(self):
        """snapshot the volume
        """
        volumes = [l.split()[1] for l in do(
                   "docker volume ls -f driver=btrfs").splitlines()[1:]]
        if self.name in volumes:
            log.info(u'Snapshotting volume: {}'.format(self.name))
            return do("buttervolume snapshot {}".format(self.name))
        else:
            log.warning('Could not snapshot unexisting volume %s', self.name)

    def schedule_snapshots(self, timer):
        """schedule snapshots of the volume
        """
        do("buttervolume schedule snapshot {} {}"
           .format(timer, self.name))

    def schedule_replicate(self, timer, slavehost):
        """schedule a replication of the volume
        """
        do("buttervolume schedule replicate:{} {} {}"
           .format(slavehost, timer, self.name))

    def schedule_purge(self, timer, pattern):
        """schedule a purge of the snapshots
        """
        do("buttervolume schedule purge:{} {} {}"
           .format(pattern, timer, self.name))

    def delete(self):
        """destroy a volume
        """
        log.info(u'Destroying volume: {}'.format(self.name))
        return do("docker volume rm {}".format(self.name))

    def restore(self, snapshot=None, target=''):
        if snapshot is None:  # use the latest snapshot
            snapshot = self.name
        log.info(u'Restoring snapshot: {}'.format(snapshot))
        restored = do("buttervolume restore {} {}"
                      .format(snapshot, target))
        target = 'as {}'.format(target) if target else ''
        log.info('Restored %s %s (after a backup: %s)',
                 snapshot, target, restored)

    def send(self, snapshot, target):
        log.info(u'Sending snapshot: {}'.format(snapshot))
        do("buttervolume send {} {}".format(target, snapshot))


def handle(events, myself):
    HANDLED = join(DEPLOY, 'events.log')
    if not exists(HANDLED):
        open(HANDLED, 'x')
    for event in json.loads(events):
        event_id = event.get('ID')
        if event_id + '\n' in open(HANDLED, 'r').readlines():
            log.info('Event already handled in the past: %s', event_id)
            continue
        open(HANDLED, 'a').write(event_id + '\n')
        event_name = event.get('Name')
        payload = b64decode(event.get('Payload', '')).decode('utf-8')
        if not payload:
            return
        log.info(u'**** Received event: {} with ID: {} and payload: {}'
                 .format(event_name, event_id, payload))
        try:
            payload = json.loads(payload)
        except Exception as e:
            msg = 'Wrong event payload format. Please provide json: %s'
            log.error(msg, str(e))
            raise

        if event_name == 'deploy':
            deploy(payload, myself)
        elif event_name == 'destroy':
            destroy(payload, myself)
        elif event_name == 'migrate':
            migrate(payload, myself)
        else:
            log.error('Unknown event name: {}'.format(event_name))


def deploy(payload, myself):
    """Keep in mind this is executed in the consul container
    Deployments are done in the DEPLOY folder. Needs:
    {"repo"': <url>, "branch": <branch>, "target": <host>, "slave": <host>}
    """
    repo_url = payload['repo']
    newmaster = payload['target']
    newslave = payload.get('slave')
    if newmaster == newslave:
        msg = "Slave must be different than the target Master"
        log.error(msg)
        raise AssertionError(msg)
    branch = payload.get('branch')
    if not branch:
        msg = "Branch is mandatory"
        log.error(msg)
        raise AssertionError(msg)

    oldapp = Application(repo_url, branch=branch)
    oldmaster = kv(oldapp.name, 'master')
    oldslave = kv(oldapp.name, 'slave')
    newapp = Application(repo_url, branch=branch)
    members = newapp.members

    if oldmaster == myself:  # master ->
        log.info('** I was the master of %s', oldapp.name)
        oldapp.down()
        if oldslave:
            oldapp.enable_replicate(False, members[oldslave]['ip'])
        else:
            oldapp.enable_snapshot(False)
        oldapp.enable_purge(False)
        if newmaster == myself:  # master -> master
            log.info("** I'm still the master of %s", newapp.name)
            for volume in oldapp.volumes_from_kv:
                volume.snapshot()
            newapp.download()
            newapp.check()
            newapp.up()
            if newslave:
                newapp.enable_replicate(True, members[newslave]['ip'])
            else:
                newapp.enable_snapshot(True)
            newapp.enable_purge(True)
            newapp.register_kv(newmaster, newslave)  # for consul-template
            newapp.register_consul()  # for consul check
        elif newslave == myself:  # master -> slave
            log.info("** I'm now the slave of %s", newapp.name)
            with newapp.notify_transfer():
                for volume in newapp.volumes_from_kv:
                    volume.send(volume.snapshot(), members[newmaster]['ip'])
            oldapp.unregister_consul()
            oldapp.down(deletevolumes=True)
            newapp.enable_purge(True)
        else:  # master -> nothing
            log.info("** I'm nothing now for %s", newapp.name)
            with newapp.notify_transfer():
                for volume in newapp.volumes_from_kv:
                    volume.send(volume.snapshot(), members[newmaster]['ip'])
            oldapp.unregister_consul()
            oldapp.down(deletevolumes=True)
        oldapp.clean()

    elif oldslave == myself:  # slave ->
        log.info("** I was the slave of %s", oldapp.name)
        oldapp.enable_purge(False)
        if newmaster == myself:  # slave -> master
            log.info("** I'm now the master of %s", newapp.name)
            newapp.download()
            newapp.check()
            newapp.wait_transfer()  # wait for master notification
            for volume in newapp.volumes_from_kv:
                volume.restore()
            newapp.up()
            if newslave:
                newapp.enable_replicate(True, members[newslave]['ip'])
            else:
                newapp.enable_snapshot(True)
            newapp.enable_purge(True)
            newapp.register_kv(newmaster, newslave)  # for consul-template
            newapp.register_consul()  # for consul check
        elif newslave == myself:  # slave -> slave
            log.info("** I'm still the slave of %s", newapp.name)
            newapp.enable_purge(True)
        else:  # slave -> nothing
            log.info("** I'm nothing now for %s", newapp.name)

    else:  # nothing ->
        log.info("** I was nothing for %s", oldapp.name)
        if newmaster == myself:  # nothing -> master
            log.info("** I'm now the master of %s", newapp.name)
            newapp.download()
            newapp.check()
            if oldslave:
                newapp.wait_transfer()  # wait for master notification
                for volume in newapp.volumes_from_kv:
                    volume.restore()
            newapp.up()
            if newslave:
                newapp.enable_replicate(True, members[newslave]['ip'])
            else:
                newapp.enable_snapshot(True)
            newapp.enable_purge(True)
            newapp.register_kv(newmaster, newslave)  # for consul-template
            newapp.register_consul()  # for consul check
        elif newslave == myself:  # nothing -> slave
            log.info("** I'm now the slave of %s", newapp.name)
            newapp.download()
            newapp.enable_purge(True)
        else:  # nothing -> nothing
            log.info("** I'm still nothing for %s", newapp.name)


def destroy(payload, myself):
    """Destroy containers, unregister, remove schedules and volumes,
    but keep snapshots. Needs:
    {"repo"': <url>, "branch": <branch>}
    """
    repo_url = payload['repo']
    branch = payload.get('branch')
    if not branch:
        msg = "Branch is mandatory"
        log.error(msg)
        raise AssertionError(msg)

    oldapp = Application(repo_url, branch=branch)
    oldmaster = kv(oldapp.name, 'master')
    oldslave = kv(oldapp.name, 'slave')
    members = oldapp.members

    if oldmaster == myself:  # master ->
        log.info('I was the master of %s', oldapp.name)
        oldapp.down()
        oldapp.unregister_consul()
        if oldslave:
            oldapp.enable_replicate(False, members[oldslave]['ip'])
        else:
            oldapp.enable_snapshot(False)
        oldapp.enable_purge(False)
        oldapp.unregister_kv()
        for volume in oldapp.volumes_from_kv:
            volume.snapshot()
        oldapp.down(deletevolumes=True)
        oldapp.clean()
    elif oldslave == myself:  # slave ->
        log.info("I was the slave of %s", oldapp.name)
        oldapp.enable_purge(False)
    else:  # nothing ->
        log.info("I was nothing for %s", oldapp.name)
    log.info("Successfully destroyed")


def migrate(payload, myself):
    """migrate volumes from one app to another. Needs:
    {"repo"': <url>, "branch": <branch>,
     "target": {"repo": <url>, "branch": <branch>}}
    If the "repo" or "branch" of the "target" is not given, it is the same as
    the source
    """
    repo_url = payload['repo']
    branch = payload['branch']
    target = payload['target']
    assert(target.get('repo') or target.get('branch'))

    sourceapp = Application(repo_url, branch=branch)
    targetapp = Application(target.get('repo', repo_url),
                            branch=target.get('branch', branch))
    source_node = kv(sourceapp.name, 'master')
    target_node = kv(targetapp.name, 'master')
    if source_node != myself and target_node != myself:
        log.info('Not concerned by this event')
        return
    source_volumes = []
    target_volumes = []
    # find common volumes
    for source_volume in sourceapp.volumes:
        source_name = source_volume.name.split('_', 1)[1]
        for target_volume in targetapp.volumes:
            target_name = target_volume.name.split('_', 1)[1]
            if source_name == target_name:
                source_volumes.append(source_volume)
                target_volumes.append(target_volume)
            else:
                continue
    log.info('Found %s volumes to restore: %s',
             len(source_volumes), repr([v.name for v in source_volumes]))
    # tranfer and restore volumes
    if source_node != target_node:
        if source_node == myself:
            with sourceapp.notify_transfer():
                for volume in source_volumes:
                    volume.send(
                        volume.snapshot(),
                        targetapp.members[target_node]['ip'])
        if target_node == myself:
            sourceapp.wait_transfer()
    if target_node == myself:
        targetapp.down()
        for source_vol, target_vol in zip(source_volumes, target_volumes):
            source_vol.restore(target=target_vol.name)
        targetapp.up()
    log.info('Restored %s to %s', sourceapp.name, targetapp.name)


class Caddyfile():
    """https://caddyserver.com/docs/caddyfile#format
    """
    @classmethod
    def loads(cls, caddyfile):
        return cls.parse(caddyfile.splitlines(), [])

    @classmethod
    def split(cls, lines, line, substring=False, sep=' '):
        """split the line but take newlines into account in substrings
        line: the line to split
        lines: the remaining lines
        """
        out = []
        for i, c in enumerate(line):
            out = out or ['']
            if c in ('"', "'"):
                substring = not substring
            elif c == sep:
                if not out[-1]:
                    continue
                if substring:
                    out[-1] += c
                else:
                    out.append('')
            else:
                out[-1] += c
        if substring:
            nextsplit = cls.split(lines, lines.pop(0), substring=True)
            out[-1] += '\n' + nextsplit[0]
            out += nextsplit[1:]
        return out

    @classmethod
    def parse(cls, lines, body, level=0):
        """level 0 is the root of the caddyfile
           level 1 is inside the definitions
           level 2 is forbidden
        """
        keys = []
        while True:
            if not lines:
                return body
            line = cls.split(lines, lines.pop(0))
            if not line:
                continue
            if level == 0:
                if keys and keys[-1][-1] == ',':
                    keys += line
                else:
                    keys = line
                if keys[-1][-1] == ',':
                    continue
                keys = [k[:-1] if k[-1] == ',' else k
                        for k in keys if k != ',']
            else:
                keys = line
            if keys[-1] == '{':
                if level == 0:
                    body.append({'keys': keys[:-1],
                                 'body': cls.parse(lines, [], level=level+1)})
                elif level == 1:
                    body.append(
                        keys[:-1] + [cls.parse(lines, [], level=level+1)])
                else:
                    raise Exception('Blocks are not allowed in subdirectives')
            elif keys == ['}']:
                return body
            else:
                body.append(keys)
            keys = []

    @classmethod
    def dumps(cls, caddylist):
        out = ''
        for i, host in enumerate(caddylist):
            out += ', '.join(host['keys']) + ' {\n'
            for directive in host['body']:
                for j, diritem in enumerate(directive):
                    if type(diritem) is list:
                        out += ' {\n'
                        for subdir in diritem:
                            if type(subdir) is list:
                                out += 8*' ' + ' '.join(subdir) + '\n'
                            else:
                                out += subdir + '\n'
                        out += '    }'
                    else:
                        q = '"' if ' ' in diritem or '\n' in diritem else ''
                        out += (4*' ' if j == 0 else ' ') + q + diritem + q
                    out += '\n' if j+1 == len(directive) else ''
            out += '}' + ('\n' if i+1 < len(caddylist) else '')
        return out

    @classmethod
    def setdir(cls, dirs, directive, replace=False):
        """set a default or forced directive """
        key = directive[0]
        if replace:
            dirs = [d for d in dirs if d[0] != key]
        if key not in [i[0] for i in dirs]:
            dirs.append(directive)
        return dirs

    @classmethod
    def setsubdirs(cls, dirs, key, subdirs, replace=False):
        """add or replace subdirectivess in the directive"""
        for d in dirs:
            if d[0] != key:
                continue
            if type(d[-1]) is list:
                if replace:
                    d.pop(-1)
                    d.append(subdirs)
                else:
                    d[-1] = sorted(set(d[-1]).union(set(subdirs)))
            else:
                d.append(subdirs)
        return dirs


class TestCase(unittest.TestCase):
    data = [
        {'caddy':  'foo {\n    root /bar\n}',  # 0
         'json':  '[{"keys":  ["foo"], "body":  [["root", "/bar"]]}]'},
        {'caddy':  'host1, host2 {\n    dir {\n        def\n    }\n}',  # 1
         'json':  '[{"keys":  ["host1", "host2"], '
                  '"body":  [["dir", [["def"]]]]}]'},
        {'caddy':  'host1, host2 {\n    dir abc {\n'
                   '        def ghi\n        jkl\n    }\n}',  # 2
         'json':  '[{"keys": ["host1", "host2"], '
                  '"body": [["dir", "abc", [["def", "ghi"], ["jkl"]]]]}]'},
        {'caddy':  'host1:1234, host2:5678 {\n'
                   '    dir abc {\n    }\n}',  # 3
         'json':  '[{"keys": ["host1:1234", "host2:5678"], '
                  '"body": [["dir", "abc", []]]}]'},
        {'caddy':  'host {\n    foo "bar baz"\n}',  # 4
         'json':  '[{"keys": ["host"], "body": [["foo", "bar baz"]]}]'},
        {'caddy':  'host, host:80 {\n    foo "bar \"baz\"\n}',  # 5
         'json':  '[{"keys": ["host", "host:80"], '
                  '"body": [["foo", "bar \"baz\""]]}]'},
        {'caddy':  'host {\n    foo "bar\nbaz"\n}',  # 6
         'json':  '[{"keys": ["host"], "body": [["foo", "bar\nbaz"]]}]'},
        {'caddy':  'host {\n    dir 123 4.56 true\n}',  # 7
         'json':  '[{"keys": ["host"], '
                  '"body": [["dir", "123", "4.56", "true"]]}]'},
        {'caddy':  'http://host, https://host {\n}',  # 8
         'json':  '[{"keys": ["http://host", "https://host"], "body": []}]'},
        {'caddy':  'host {\n    dir1 a b\n    dir2 c d\n}',  # 9
         'json':  '[{"keys": ["host"], '
                  '"body": [["dir1", "a", "b"], ["dir2", "c", "d"]]}]'},
        {'caddy':  'host {\n    dir a b\n    dir c d\n}',  # 10
         'json':  '[{"keys": ["host"], '
                  '"body": [["dir", "a", "b"], ["dir", "c", "d"]]}]'},
        {'caddy':  'host {\n    dir1 a b\n    '
                   'dir2 {\n        c\n        d\n    }\n}',  # 11
         'json':  '[{"keys": ["host"], '
                  '"body": [["dir1", "a", "b"], ["dir2", [["c"], ["d"]]]]}]'},
        {'caddy':  'host1 {\n    dir1\n}\nhost2 {\n    dir2\n}',  # 12
         'json':  '[{"keys": ["host1"], '
                  '"body": [["dir1"]]}, '
                  '{"keys": ["host2"], "body": [["dir2"]]}]'},
        {'caddy':  '', 'json':  '[]'},  # 13
        ]

    def setUp(self):
        DEPLOY = '/tmp/deploy'
        os.makedirs(DEPLOY, exist_ok=True)

    def tearDown(self):
        if DEPLOY.startswith('/tmp'):
            rmtree(DEPLOY)

    def test_split(self):
        self.assertEqual([], Caddyfile.split([], ''))
        self.assertEqual(['a', 'z', 'e'], Caddyfile.split([], 'a z e'))
        self.assertEqual(['a', 'z e'], Caddyfile.split([], 'a "z e"'))
        self.assertEqual(['a z e'], Caddyfile.split([], '"a z e"'))
        self.assertEqual(['az', 'er ty', 'ui'],
                         Caddyfile.split([], 'az "er ty" ui'))
        self.assertEqual(['az', 'er ty', 'ui'],
                         Caddyfile.split([], "az 'er ty' ui"))
        self.assertEqual(['foo\nbar'],
                         Caddyfile.split(['bar"', 'baz'], '"foo'))

    def test_caddy2json(self):
        for i, d in enumerate(self.data):
            if i == 5:
                print('test # {} skipped, plz help!'.format(i))
                continue
            self.assertEqual(
                json.dumps(json.loads(d['json'], strict=False),
                           sort_keys=True),
                json.dumps(Caddyfile.loads(d['caddy']), sort_keys=True))
            print('test # {} ok'.format(i))

    def test_json2caddy(self):
        for i, d in enumerate(self.data):
            if i == 5:
                print('test # {} skipped, plz help!'.format(i))
                continue
            self.assertEqual(
                d['caddy'],
                Caddyfile.dumps(json.loads(d['json'], strict=False)))
            print('test # {} ok'.format(i))

    def test_reversibility(self):
        for i, d in enumerate(self.data):
            if i == 5:
                print('test # {} skipped, plz help!'.format(i))
                continue
            self.assertEqual(
                d['caddy'],
                Caddyfile.dumps(Caddyfile.loads(d['caddy'])))
            print('test # {} ok'.format(i))

    def test_setdir(self):
        self.assertEqual(
            [['proxy', '/', 'ct:80'], ['other', 'foo']],
            Caddyfile.setdir([['proxy', '/', 'ct:80']], ['other', 'foo']))
        self.assertEqual(
            [['gzip', 'foo']],
            Caddyfile.setdir([['gzip']], ['gzip', 'foo'], replace=True))

    def test_setsubdirs(self):
        self.assertEqual(
            [['proxy', ['subdir1', 'subdir2']]],
            Caddyfile.setsubdirs(
                [['proxy']], 'proxy', ['subdir1', 'subdir2']))
        self.assertEqual(
            [['proxy', ['s1', 's2', 's3']]],
            Caddyfile.setsubdirs(
                [['proxy', ['s1']]], 'proxy', ['s2', 's3']))
        self.assertEqual(
            [['proxy', ['s2', 's3']]],
            Caddyfile.setsubdirs(
                [['proxy', ['s1']]], 'proxy', ['s2', 's3'], replace=True))
        self.assertEqual(
            [['gzip']],  # would need setdir first
            Caddyfile.setsubdirs(
                [['gzip']], 'proxy', ['s2', 's3'], replace=True))

    def test_application_init(self):
        repo_url = 'https://gitlab.example.com/hosting/FooBar '
        app = Application(repo_url, branch='master')
        self.assertEqual(
            app.repo_url,
            'https://gitlab.example.com/hosting/foobar')
        self.assertEqual(app.name, 'foobar_master.ddb14')

    def test_kv(self):
        self.maxDiff = None
        self.assertEqual(
            'http://gitlab.example.com/hosting/foobar',
            kv('foobar_master.ddb14', 'repo_url'))
        self.assertEqual(None, kv('foobar_master.ddb14', 'foobar'))
        self.assertEqual(None, kv('foo', 'bar'))

    def test_check(self):
        app = Application('fake://127.0.0.1/testapp/', 'master')
        app.download()
        self.assertEqual(None, app.check())
        # already deployed
        app._caddy['wordpress'][0]['keys'][0] = 'http://foobar.example.com'
        self.assertRaises(ValueError, app.check)

    def test_volumes(self):
        app = Application('fake://127.0.0.1/testapp/', 'master')
        app.download()
        self.assertEqual(['dbdata', 'socket', 'wwwdata'],
                         sorted(app.compose['volumes'].keys()))

    def test_volumes_from_kv(self):
        repo_url = 'http://gitlab.example.com/hosting/foobar'
        app = Application(repo_url, 'master')
        self.assertEqual(
            ['foobarmasterddb14_dbdata', 'foobarmasterddb14_wwwdata'],
            sorted(v.name for v in app.volumes_from_kv))

    def test_members(self):
        repo_url = 'http://gitlab.example.com/hosting/foobar'
        app = Application(repo_url, 'master')
        members = app.members
        self.assertEqual(['node1', 'node2', 'node3'], sorted(members.keys()))
        self.assertEqual(['ip', 'status'], sorted(members['node1'].keys()))

    def test_register_kv(self):
        app = Application('fake://127.0.0.1/testapp/', 'master')
        app.download()
        self.assertEqual(None, app.register_kv('node1', 'node2'))


class FakeExec(object):
    """fake executables for tests
    """
    faked = ('consul', 'git')
    foobar = (
        '{"name": "foo-bar_master.ddb14", '
        '"repo_url": "http://gitlab.example.com/hosting/foobar", '
        '"branch": "master", '
        '"domain": "foobar.example.com", '
        '"ip": "163.172.4.172", '
        '"master": "bigz", '
        '"caddyfile": "http://foobar.example.com {\n'
        '    proxy / http://foobarmasterddb14_wordpress_1:80\n}",'
        ' "slave": null, '
        '"volumes": '
        '["foobarmasterddb14_wwwdata", "foobarmasterddb14_dbdata"], '
        '"ct": "http://foobarmasterddb14_wordpress_1:80"}')

    @classmethod
    def run(self, cmd):
        if cmd == 'consul kv get app/foobar_master.ddb14':
            return self.foobar
        elif cmd == 'consul kv export app/':
            return ('[{"key": "app/foo-bar_master.ddb14",'
                    '"flags": 0, "value": "%s"}]'
                    % b64encode(self.foobar.encode('utf-8')).decode('utf-8'))
        elif cmd.startswith('git clone --depth 1 -b master '
                            'fake://127.0.0.1/testapp/'):
            checkout = cmd.split()[-1]
            os.mkdir(join(DEPLOY, checkout))
            copy(join(dirname(HERE), 'testapp', 'docker-compose.yml'),
                 join(DEPLOY, checkout))
        elif cmd == 'consul members':
            return (
                'Node   Address            Status  Type       DC\n'
                'node1   10.10.10.11:8301  alive   server     dc1\n'
                'node2   10.10.10.12:8301  alive   server     dc1\n'
                'node3   10.10.10.13:8301  alive   server     dc1')
        elif cmd.startswith('consul kv put'):
            if 'http://testappmasterf4301_wordpress_1:80' not in cmd:
                raise
            return 'ok'
        else:
            raise NotImplementedError


if __name__ == '__main__':
    if len(argv) == 1 or (len(argv) >= 1 and argv[1] in FakeExec.faked):
        DEPLOY = '/tmp/deploy'
        os.makedirs(DEPLOY, exist_ok=True)

    logformat = '{asctime}\t{levelname}\t{message}'
    logging.basicConfig(level=logging.DEBUG,
                        format=logformat,
                        filename=join(DEPLOY, 'handler.log'),
                        style='{')
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter(logformat, style='{'))
    logging.getLogger().addHandler(ch)

    myself = socket.gethostname()
    manual_input = None

    if len(argv) >= 2 and argv[1] in FakeExec.faked:
        # mock consul
        print(FakeExec.run(' '.join(argv[1:])))
    elif len(argv) == 1:
        # run some unittests
        TEST = True
        unittest.main(verbosity=2)
    elif len(argv) >= 3:
        # allow to launch manually inside consul docker
        event = argv[1]
        payload = b64encode(' '.join(argv[2:]).encode('utf-8')).decode('utf-8')
        manual_input = json.dumps([{
            'ID': str(uuid1()), 'Name': event,
            'Payload': payload, 'Version': 1, 'LTime': 1}])
        handle(manual_input, myself)
    else:
        # run what's given by consul watch
        handle(stdin.read(), myself)
