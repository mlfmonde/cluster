#!/usr/bin/env python3
# coding: utf-8
import argparse
import hashlib
import json
import logging
import os
import re
import requests
import socket
import time
import yaml
from base64 import b64decode
from contextlib import contextmanager
from datetime import datetime
from docker import DockerClient
from functools import reduce
from os.path import basename, join, exists
from subprocess import run, CalledProcessError, PIPE
from sys import stdin, argv
from urllib.parse import urlparse
DTFORMAT = "%Y-%m-%dT%H%M%S.%f"
DEPLOY = '/deploy'
CADDYLOGS = '/var/log'
DOCKER_BASE_URL = "unix:////run/docker.sock"
LABEL_NON_MIGRABLE_VOLUME = 'com.github.mlfmonde.cluster.nonmigrable'
TEST = False
log = logging.getLogger()
BTRFSDRIVER = os.environ.get('BTRFSDRIVER', 'anybox/buttervolume:latest')
POST_MIGRATE_SCRIPT_NAME = 'post_migrate.sh'
UPDATE_SCRIPT_NAME = 'update.sh'


def concat(l):
    return reduce(list.__add__, l, [])


def do(cmd, cwd=None):
    """ Run a command"""
    cmd = argv[0] + ' ' + cmd if TEST else cmd
    try:
        log.info('Running: ' + cmd)
        res = run(cmd, shell=True, check=True,
                  stdout=PIPE, stderr=PIPE, cwd=cwd)
        return res.stdout.decode().strip()
    except CalledProcessError as e:
        log.error("Failed to run %s: return code = %s, %s",
                  e.cmd, e.returncode, e.stderr.decode())
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
    def __init__(
        self, repo_url, branch, deploy_id=None, current_deploy_id=None
    ):
        """Init application object

        :param repo_url: repo where the docker-compose is stored
        :param branch: the repo branch/tag/ref to use
        :param deploy_id: the consul event id, only use it if it's a new app
                          that is going to be deployed and will be stored in kv
                          store. If it's app alredy deployed you must leave it
                          to None, it will get information from the k/v store
        :param current_deploy_id: the current event id which we are handling,
                                  the intent is to manage weired case where
                                  an old app object may be instanciate after
                                  the new master already save values in k/v
                                  store. This could happen when deploy using
                                  sames master/slave and slave were busy while
                                  master handling the event. if deploy_id is
                                  define this value is ignored. If this value
                                  is set you should not save in k/v store.
        """

        self.repo_url, self.branch = repo_url.strip(), branch.strip()
        if self.repo_url.endswith('.git'):
            self.repo_url = self.repo_url[:-4]
        md5 = hashlib.md5(urlparse(self.repo_url.lower()).path.encode('utf-8')
                          ).hexdigest()
        repo_name = basename(self.repo_url.strip('/').lower())
        self.name = repo_name + ('_' + self.branch if self.branch else ''
                                 ) + '.' + md5[:5]  # don't need full md5
        self._services = None
        self._kv_volumes = None
        self._volumes = None
        self._compose = None
        self._deploy_date = None
        self._caddy = {}
        self._previous_deploy_id = None
        self._deploy_id = None
        self._current_deploy_id = current_deploy_id
        if deploy_id:
            self._previous_deploy_id = self.deploy_id
            self._deploy_id = deploy_id

    @property
    def previous_deploy_id(self):
        """date of the last deployment"""
        if self._previous_deploy_id is None:
            self._previous_deploy_id = kv(self.name, 'previous_deploy_id')
        return self._previous_deploy_id

    @property
    def deploy_id(self):
        """date of the last deployment"""
        if self._deploy_id is None:
            kv_deploy_id = self._deploy_id = kv(self.name, 'deploy_id')
            if self._current_deploy_id == kv_deploy_id:
                self._deploy_id = self.previous_deploy_id
            else:
                self._deploy_id = kv_deploy_id
        return self._deploy_id

    @property
    def deploy_date(self):
        """date of the last deployment"""
        if self._deploy_date is None:
            self._deploy_date = kv(self.name, 'deploy_date')
        return self._deploy_date

    def _path(self, deploy_date=None, deploy_id=None):
        """path of the deployment checkout"""
        deploy_id = deploy_id or self.deploy_id
        if deploy_id:
            return join(DEPLOY, self.name + '-' + deploy_id)
        deploy_date = deploy_date or self.deploy_date
        if deploy_date:
            return join(DEPLOY, self.name + '@' + deploy_date)
        return None

    @property
    def path(self):
        return self._path()

    def check(self, master):
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
            caddy_urls = concat([c['keys'] for c in caddy])
            if len(set(caddy_urls)) != len(caddy_urls):
                msg = 'Aborting! Duplicate URL in caddyfile'
                log.error(msg)
                raise ValueError(msg)
            caddy_domains = {urlparse(u).netloc for u in caddy_urls}
            for appname, appconf in all_apps.items():
                app_urls = concat(
                    [c['keys'] for c in
                     Caddyfile.loads(
                        appconf.get('caddyfile', {'caddyfile': []}))])
                app_master = appconf['master']
                app_domains = appconf['domains']
                if appname.split('/')[1] == self.name:
                    continue
                for url in caddy_urls:
                    if url in app_urls:
                        msg = ('Aborting! URL {} is already deployed by {}'
                               .format(url, appname))
                        log.error(msg)
                        raise ValueError(msg)
                if any([d in caddy_domains for d in app_domains]
                       ) and app_master != master:
                    msg = ('Warning! A domain of this app is '
                           'already routed to {}! Also move the other app!'
                           .format(master))
                    log.warning(msg)

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
            log.error('Volume migration FAILED! : %s', str(e))
            do('consul kv put migrate/{}/failure'.format(self.name))
            self.up()  # TODO move in the deploy
            self.maintenance(enable=False)  # TODO move
            raise
        log.info('Volume migration SUCCEEDED!')

    def clean_notif(self):
        do('consul kv delete -recurse migrate/{}/'.format(self.name))

    def wait_transfer(self):
        for loop in range(1200):
            log.info('Waiting migrate notification for %s', self.name)
            res = do('consul kv get -keys migrate/{}/'.format(self.name))
            if res:
                status = res.split('/')[-1]
                do('consul kv delete -recurse migrate/{}/'
                   .format(self.name))
                log.info('Transfer notification status: %s', status)
                return status
            time.sleep(1)
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
        if self._kv_volumes is None:
            try:
                self._kv_volumes = [
                    Volume(v) for v in kv(self.name, 'volumes')]
            except:
                log.info("No volumes found in the kv")
                # if kv is not present in the store, get a chance to get info
                # from compose
                self._kv_volumes = self.volumes
            self._kv_volumes = self._kv_volumes or []
        return self._kv_volumes

    @property
    def volumes(self):
        """btrfs volumes defined in the compose
        """
        if not self._volumes:
            try:
                self._volumes = [
                    Volume(self.project + '_' + v[0])
                    for v in self.compose.get('volumes', {}).items()
                    if v[1] and v[1].get('driver') == BTRFSDRIVER]
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
            path = self._path(deploy_date=deploy_date)
            do('git clone --depth 1 {} "{}" "{}"'
               .format('-b "%s"' % self.branch if self.branch else '',
                       self.repo_url, path),
               cwd=DEPLOY)
            with open(join(path, '.env'), 'a') as env:
                # to ease manual management without '-p'
                env.write('COMPOSE_PROJECT_NAME={}\n'.format(self.project))
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

    def maintenance(self, enable):
        """maintenance page"""
        if enable:
            do('consul kv put maintenance/{}'.format(self.name))
        else:
            do('consul kv delete maintenance/{}'.format(self.name))

    def pull(self, ignorefailures=False):
        """pull images delcare in docker-compose.yml file

        :param ignorefailures: Pull what it can and ignores images with pull
                               failures.
        """
        if self.path and exists(self.path):
            log.info("Pulling images %s", self.name)
            ignore = '--ignore-pull-failures' if ignorefailures else ''
            do('docker-compose -p "{}" pull {}'
               .format(self.project, ignore),
               cwd=self.path)
        else:
            log.warning("No deployment, cannot pull %s", self.name)

    def build(self, pull=True, nocache=False, forecerm=False):
        """Build images declare in docker-compose.yml file

        :param nocache: Do not use cache when building the image.
        :param forecerm: Always remove intermediate containers.
        :return:
        """
        if self.path and exists(self.path):
            log.info("Building %s", self.name)
            pull = '--pull' if pull else ''
            cache = '--no-cache' if nocache else ''
            rm = '--force-rm' if forecerm else ''
            do('docker-compose -p "{}" build {} {} {}'
               .format(self.project, pull, cache, rm),
               cwd=self.path)
        else:
            log.warning("No deployment, cannot build %s", self.name)

    def run_post_migrate(self, from_app):
        script_path = join(self.path, POST_MIGRATE_SCRIPT_NAME)
        if exists(script_path):
            log.info("running migrate script {}".format(script_path))
            do(
                '{} -R {} -B {} -r {} -b {}'.format(
                    script_path,
                    from_app.repo_url,
                    from_app.branch,
                    self.repo_url,
                    self.branch
                ),
                cwd=self.path
            )

    def deploy_pre_up(self, run_update_script=False):
        if run_update_script:
            script_path = join(self.path, UPDATE_SCRIPT_NAME)
            if exists(script_path):
                log.info("running preup script {}".format(script_path))
                # TODO: a snapshot to prevent any loss of data since last one
                do(
                    'sh {} -r {} -b {}'.format(
                        script_path,
                        self.repo_url,
                        self.branch
                    ),
                    cwd=self.path
                )

    def up(self):
        if self.path and exists(self.path):
            log.info("Starting %s", self.name)
            do('docker-compose -p "{}" up -d'
               .format(self.project),
               cwd=self.path)
        else:
            log.warning("No deployment, cannot start %s", self.name)

    def down(self, deletevolumes=False):
        if self.path and exists(self.path):
            log.info("Stopping %s", self.name)
            v = '-v' if deletevolumes else ''
            do('docker-compose -p "{}" down {}'.format(self.project, v),
               cwd=self.path)
        else:
            log.warning("Cannot stop %s", self.name)

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
            dirs = Caddyfile.setdir(dirs, ['gzip'])
            dirs = Caddyfile.setdir(dirs, ['timeouts', '300s'])
            proxy_config = ['websocket', 'insecure_skip_verify']
            if host['keys'][0].startswith('https://'):
                proxy_config.append('transparent')
                dirs = Caddyfile.setdir(
                    dirs,
                    ['log', '/', 'stdout', '{hostonly} - {combined}'],
                    replace=True
                )
            else:
                proxy_config.append('header_upstream Host {host}')
                proxy_config.append('header_upstream X-Real-IP {remote}')
                proxy_config.append(
                    'header_upstream X-Forwarded-Proto {scheme}'
                )
                dirs = Caddyfile.setdir(
                    dirs,
                    [
                        'log',
                        '/',
                        'stdout',
                        '{hostonly} - {>X-Forwarded-For} - {user} [{when}] '
                        '\\"{method} {uri} {proto}\\" '
                        '{status} {size} '
                        '\\"{>Referer}\\" \\"{>User-Agent}\\"'
                    ],
                    replace=True
                )

            Caddyfile.setsubdirs(
                dirs, 'proxy',
                proxy_config,
                replace=True)
            host['body'] = dirs
        return self._caddy[service] or []

    def ps(self, service):
        ps = do('docker ps -f name=%s --format "table {{.Status}}"'
                % self.container_name(service))
        return ps.split('\n')[-1].strip()

    def haproxy(self, services):
        result = {}
        name = 'HAPROXY'
        for service in services:
            try:
                env = self.compose['services'][service]['environment']
                haproxy = env[name]
            except Exception:
                log.debug(
                    'No %s environment variable for '
                    'service %s in the compose file of %s',
                    name, service, self.name
                )
                continue
            try:
                log.info('Found a %s environment variable for '
                         'service %s in the compose file of %s',
                         name, service, self.name)
                hapx = yaml.load(haproxy)
            except Exception as e:
                log.warning(
                    'Invalid %s environment variable for '
                    'service %s in the compose file of %s: %s. \nCaused by '
                    'the following configuration wich will be ignored, '
                    'make sure it\'s a valid json/yaml: ',
                    name, service, self.name, str(e)
                )
                continue
            for key, conf in hapx.items():
                for backend in conf['backends']:
                    backend['ct'] = self.container_name(service)
                if key in result:
                    bind = conf.get('frontend', {}).get('bind', [])
                    bind.extend(
                        result[key].get('frontend', {}).get('bind', [])
                    )
                    if bind:
                        result[key]['frontend']["bind"] = list(set(bind))

                    options = conf.get('frontend', {}).get('options', [])
                    options.extend(
                        result[key].get('frontend', {}).get('options', [])
                    )
                    if options:
                        result[key]['frontend']['options'] = list(set(options))
                    result[key]['backends'].extend(conf['backends'])
                else:
                    result[key] = conf
        return result

    def consul_extra_check_urls(self, services):
        """urls to use in default consul checks were add by introspecting
         caddyfile, this offer the capabilities to add extra urls or in case
         using only HAPROXY config by using CONSUL_CHECK_URLS.
        """
        name = 'CONSUL_CHECK_URLS'
        extra_urls = []
        for service in services:
            try:
                env = self.compose['services'][service]['environment']
                urls = env[name]
            except Exception:
                log.debug(
                    'No %s environment variable for '
                    'service %s in the compose file of %s',
                    name, service, self.name
                )
                continue
            try:
                log.info('Found a %s environment variable for '
                         'service %s in the compose file of %s',
                         name, service, self.name)
                urls_list = yaml.load(urls)
            except Exception as e:
                log.warning(
                    'Invalid %s environment variable for '
                    'service %s in the compose file of %s: %s. \nCaused by '
                    'the following configuration wich will be ignored, '
                    'make sure it\'s a valid json/yaml: ',
                    name, service, self.name, str(e)
                )
                continue
            extra_urls.extend(urls_list)
        return extra_urls

    def register_kv(self, master, slave):
        """register services in the key/value store
        so that consul-template can regenerate the
        caddy and haproxy conf files
        """
        log.info("Registering URLs of %s in the key/value store",
                 self.name)
        caddyfiles = concat([self.caddyfile(s) for s in self.services])
        caddyfiles = [c for c in caddyfiles if c]
        urls = concat([c['keys'] for c in caddyfiles])
        value = {
            'haproxy': self.haproxy(self.services),
            'caddyfile': Caddyfile.dumps(caddyfiles) if caddyfiles else "",
            'repo_url': self.repo_url,
            'branch': self.branch,
            'deploy_date': self._deploy_date,
            'deploy_id': self.deploy_id,
            'previous_deploy_id': self.previous_deploy_id,
            'domains': list({urlparse(u).netloc for u in urls}),
            'urls': ', '.join(urls),
            'ip': self.members[master]['ip'],
            'master': master,
            'slave': slave,
            'ct': {s: self.container_name(s) for s in self.services},
            'volumes': [v.name for v in self.volumes]}

        do("consul kv put app/{} '{}'"
           .format(self.name, json.dumps(value, indent=2)))
        log.info("Registered %s", self.name)

    def unregister_kv(self):
        do("consul kv delete app/{}".format(self.name))

    def register_consul(self):
        """register a service and check in consul
        """
        urls = concat([c['keys'] for c in
                       concat([self.caddyfile(s) for s in self.services])])
        urls.extend(self.consul_extra_check_urls(self.services))
        # default for most cases
        svc = json.dumps({
            'Name': self.name,
            'Checks': [{
                'HTTP': url,
                'Interval': '60s'} for url in urls if url]})

        # use a file if provided
        path = '{}/service.json'.format(self.path)
        if exists(path):
            with open(path) as f:
                svc = json.dumps(json.loads(f.read()))

        url = 'http://localhost:8500/v1/agent/service/register'
        res = requests.put(url, svc)
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

    def enable_snapshot(self, enable, from_compose=False):
        """enable or disable scheduled snapshots
        """
        volumes = self.volumes if from_compose else self.volumes_from_kv
        for volume in volumes:
            volume.schedule_snapshots(60 if enable else 0)

    def enable_replicate(self, enable, ip, from_compose=False):
        """enable or disable scheduled replication
        """
        volumes = self.volumes if from_compose else self.volumes_from_kv
        for volume in volumes:
            volume.schedule_replicate(60 if enable else 0, ip)

    def enable_purge(self, enable, from_compose=False):
        volumes = self.volumes if from_compose else self.volumes_from_kv
        for volume in volumes:
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
                   "docker volume ls -f driver={}".format(BTRFSDRIVER)
                   ).splitlines()[1:]]
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

    def get_docker_client(self):
        return DockerClient(base_url=DOCKER_BASE_URL)

    @property
    def migrable_volume(self):
        dc = self.get_docker_client()
        labels = dc.volumes.get(self.name).attrs.get('Labels', {})
        if not labels:
            labels = {}
        non_migrable = labels.get(
            LABEL_NON_MIGRABLE_VOLUME, 'false'
        )
        return not non_migrable.lower() in ['true', '1']


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
            deploy(payload, myself, event_id)
        elif event_name == 'destroy':
            destroy(payload, myself)
        elif event_name == 'migrate':
            migrate(payload, myself)
        else:
            log.error('Unknown event name: {}'.format(event_name))


def deploy(payload, myself, deploy_id):
    """Keep in mind this is executed in the consul container
    Deployments are done in the DEPLOY folder. Needs:
    {"repo"': <url>, "branch": <branch>, "master": <host>, "slave": <host>}
    """
    repo_url = payload['repo']
    newmaster = payload['master']
    newslave = payload.get('slave')
    if newmaster == newslave:
        msg = "Slave must be different than the Master"
        log.error(msg)
        raise AssertionError(msg)
    branch = payload.get('branch')
    if not branch:
        msg = "Branch is mandatory"
        log.error(msg)
        raise AssertionError(msg)
    run_update_script = payload.get('update', False)

    oldapp = Application(repo_url, branch=branch, current_deploy_id=deploy_id)
    oldmaster = kv(oldapp.name, 'master')
    oldslave = kv(oldapp.name, 'slave')
    newapp = Application(repo_url, branch=branch, deploy_id=deploy_id)
    members = newapp.members
    log.info('oldapp={}, oldmaster={}, oldslave={}, '
             'newapp={}, newmaster={}, newslave={}'
             .format(oldapp.name, oldmaster, oldslave,
                     newapp.name, newmaster, newslave))

    if oldmaster == myself:  # master ->
        log.info('** I was the master of %s', oldapp.name)
        if newmaster != myself:
            for volume in oldapp.volumes_from_kv:
                volume.send(volume.snapshot(), members[newmaster]['ip'])
        oldapp.maintenance(enable=True)
        oldapp.down()
        if oldslave:
            oldapp.enable_replicate(False, members[oldslave]['ip'])
        else:
            oldapp.enable_snapshot(False)
        oldapp.enable_purge(False)
        newapp.clean_notif()
        if newmaster == myself:  # master -> master
            log.info("** I'm still the master of %s", newapp.name)
            for volume in oldapp.volumes_from_kv:
                volume.snapshot()
            newapp.download()
            newapp.check(newmaster)
            newapp.pull()
            newapp.build()
            newapp.deploy_pre_up(run_update_script)
            newapp.up()
            if newslave:
                newapp.enable_replicate(
                    True, members[newslave]['ip'], from_compose=True
                )
            else:
                newapp.enable_snapshot(True, from_compose=True)
            newapp.enable_purge(True, from_compose=True)
            newapp.register_kv(newmaster, newslave)  # for consul-template
            newapp.register_consul()  # for consul check
            newapp.maintenance(enable=False)
        elif newslave == myself:  # master -> slave
            log.info("** I'm now the slave of %s", newapp.name)
            with newapp.notify_transfer():
                for volume in newapp.volumes_from_kv:
                    volume.send(volume.snapshot(), members[newmaster]['ip'])
            oldapp.unregister_consul()
            oldapp.down(deletevolumes=True)
            newapp.download()
            newapp.enable_purge(True, from_compose=True)
        else:  # master -> nothing
            log.info("** I'm nothing now for %s", newapp.name)
            with newapp.notify_transfer():
                for volume in oldapp.volumes_from_kv:
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
            newapp.check(newmaster)
            newapp.pull()
            newapp.build()
            newapp.wait_transfer()  # wait for master notification
            oldvolumes = set([v.name for v in oldapp.volumes_from_kv])
            common_volumes = [
                v for v in newapp.volumes if v.name in oldvolumes
            ]
            for volume in common_volumes:
                volume.restore()
            newapp.deploy_pre_up(run_update_script)
            newapp.up()
            if newslave:
                newapp.enable_replicate(
                    True, members[newslave]['ip'], from_compose=True
                )
            else:
                newapp.enable_snapshot(True, from_compose=True)
            newapp.enable_purge(True, from_compose=True)
            newapp.register_kv(newmaster, newslave)  # for consul-template
            newapp.register_consul()  # for consul check
            newapp.maintenance(enable=False)
        elif newslave == myself:  # slave -> slave
            log.info("** I'm still the slave of %s", newapp.name)
            newapp.download()
            newapp.enable_purge(True, from_compose=True)
        else:  # slave -> nothing
            log.info("** I'm nothing now for %s", newapp.name)
        oldapp.clean()

    else:  # nothing ->
        log.info("** I was nothing for %s", oldapp.name)
        if newmaster == myself:  # nothing -> master
            log.info("** I'm now the master of %s", newapp.name)
            newapp.download()
            newapp.check(newmaster)
            newapp.pull()
            newapp.build()
            if oldmaster:
                newapp.wait_transfer()  # wait for master notification
                oldvolumes = set([v.name for v in oldapp.volumes_from_kv])
                common_volumes = [
                    v for v in newapp.volumes if v.name in oldvolumes
                ]
                for volume in common_volumes:
                    volume.restore()
            newapp.deploy_pre_up(run_update_script)
            newapp.up()
            if newslave:
                newapp.enable_replicate(
                    True, members[newslave]['ip'], from_compose=True
                )
            else:
                newapp.enable_snapshot(True, from_compose=True)
            newapp.enable_purge(True, from_compose=True)
            newapp.register_kv(newmaster, newslave)  # for consul-template
            newapp.register_consul()  # for consul check
            newapp.maintenance(enable=False)
        elif newslave == myself:  # nothing -> slave
            log.info("** I'm now the slave of %s", newapp.name)
            newapp.download()
            newapp.enable_purge(True, from_compose=True)
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
        oldapp.clean()
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
    for source_volume in sourceapp.volumes_from_kv:
        source_name = source_volume.name.split('_', 1)[1]
        for target_volume in targetapp.volumes_from_kv:
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
        targetapp.maintenance(enable=True)
        targetapp.down()
        for source_vol, target_vol in zip(source_volumes, target_volumes):
            if target_vol.migrable_volume:
                source_vol.restore(target=target_vol.name)
        targetapp.run_post_migrate(sourceapp)
        targetapp.up()
        targetapp.maintenance(enable=False)
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
        line = line.strip()
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
            if not isinstance(host, dict):
                raise Exception(
                    "Your CADDYFILE env is malformated, "
                    "you may have missed a space or a bracket.\n"
                    "current host: %r" % host
                )
            out += ', '.join(host['keys']) + ' {\n'
            for directive in host['body']:
                for j, diritem in enumerate(directive):
                    if type(diritem) is list:
                        out += ' {\n'
                        for subdir in diritem:
                            if type(subdir) is list:
                                out += 8*' ' + ' '.join(subdir) + '\n'
                            else:
                                out += 8*' ' + subdir + '\n'
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


def deploy_handler():

    parser = argparse.ArgumentParser(
        description="Consul watcher deploy handler",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    logging_group = parser.add_argument_group(
        'Logging params'
    )
    logging_group.add_argument(
        '-l', '--logging-level', default='DEBUG'
    )
    logging_group.add_argument(
        '--logging-format',
        default='{asctime}\t{levelname}\t{message}'
    )
    logging_group.add_argument(
        '--logging-file',
        help="Logging handler file output",
        default=join(DEPLOY, 'handler.log')
    )
    arguments = parser.parse_args()
    do("mkdir -p {}".format(os.path.dirname(arguments.logging_file)))
    logging.basicConfig(
        level=getattr(logging, arguments.logging_level.upper()),
        format=arguments.logging_format,
        filename=arguments.logging_file,
        style='{'
    )
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter(arguments.logging_format, style='{'))
    logging.getLogger().addHandler(ch)

    myself = socket.gethostname()
    handle(stdin.read(), myself)
