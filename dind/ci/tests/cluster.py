import consulate
import docker
import hashlib
import json
import logging
import requests
import time
import uuid

from collections import namedtuple
from datetime import datetime
from os import path
from urllib import parse

from . import const

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)
DEFAULT_TIMEOUT = const.timeout
DEPLOY_ROOT_DIR = '/deploy'


class Cluster:
    # static IPs and ports bindings from dind/docker-compose.yml
    base_url_pattern = "tcp://10.10.77.6{index}:2375"  # through network ip
    #base_url_pattern = "tcp://127.0.0.1:500{index}"  # through port forwarding
    client_default_kwargs = dict()
    if const.docker['version']:
        client_default_kwargs['version'] = const.docker['version']

    def __init__(self):
        self.consul = consulate.Consul(host=const.host, port=const.consul['port'])
        self.nodes = dict(
            node1=dict(
                docker_cli=docker.DockerClient(
                    base_url=self.__class__.base_url_pattern.format(index=1),
                    **self.__class__.client_default_kwargs
                ),
            ),
            node2=dict(
                docker_cli=docker.DockerClient(
                    base_url=self.__class__.base_url_pattern.format(index=2),
                    **self.__class__.client_default_kwargs
                ),
            ),
            node3=dict(
                docker_cli=docker.DockerClient(
                    base_url=self.__class__.base_url_pattern.format(index=3),
                    **self.__class__.client_default_kwargs
                ),
            ),
            node4=dict(
                docker_cli=docker.DockerClient(
                    base_url=self.__class__.base_url_pattern.format(index=4),
                    **self.__class__.client_default_kwargs
                ),
            ),
        )

    # communicate with consul
    def deploy_and_wait(
        self,
        master=None,
        slave=None,
        application=None,
        timeout=DEFAULT_TIMEOUT,
        event_consumed=None
    ):
        """Deploy a service waiting the end end of deployment before carry on
        """
        def deploy_finished(kv_app_before, kv_app_after, *args, **kwargs):
            if kv_app_before and kv_app_after:
                if kv_app_after.deploy_date > kv_app_before.deploy_date:
                    return True
                else:
                    return False
            else:
                if not kv_app_before:
                    if kv_app_after:
                        return True
                    else:
                        return False
                else:
                    return False

        if not event_consumed:
            event_consumed = deploy_finished

        self.fire_event_and_wait(
            application,
            'deploy',
            json.dumps(
                {
                    'repo': application.repo_url,
                    'branch': application.branch,
                    'master': master,
                    'slave': slave,
                }
            ),
            event_consumed,
            timeout
        )

    def destroy_and_wait(
        self, application, timeout=DEFAULT_TIMEOUT, event_consumed=None
    ):
        def deploy_finished(kv_app_before, kv_app_after, *args, **kwargs):
            if not kv_app_after:
                return True
            else:
                return False

        if not event_consumed:
            event_consumed = deploy_finished

        self.fire_event_and_wait(
            application,
            'destroy',
            json.dumps(
                {
                    'repo': application.repo_url,
                    'branch': application.branch,
                }
            ),
            event_consumed,
            timeout
        )

    def migrate_and_wait(
        self, source_app, target_app, timeout=DEFAULT_TIMEOUT
    ):

        self.was_maintenance = False

        def migrate_finished(
            kv_app_before, kv_app_after, maintenance=None, self=None, **kwargs
        ):
            if maintenance:
                self.was_maintenance = True
            if self.was_maintenance and not maintenance:
                return True
            return False

        self.fire_event_and_wait(
            target_app,
            'migrate',
            json.dumps(
                {
                    'repo': source_app.repo_url,
                    'branch': source_app.branch,
                    'target': {
                        'repo': target_app.repo_url,
                        'branch': target_app.branch
                    }
                }
            ),
            migrate_finished,
            timeout
        )

    def fire_event_and_wait(
        self, application, event_name, payload, event_consumed, timeout
    ):
        app_before = self.get_app_from_kv(application.app_key)
        logger.info(
            "Emit %s event for ref/branch: %s with following payload: %r",
            event_name, application.branch, payload
        )
        event_id = self.consul.event.fire(
            event_name, payload
        )
        start_date = datetime.now()
        while not event_consumed(
                app_before,
                self.get_app_from_kv(application.app_key),
                maintenance=self.consul.kv.get_record(
                    application.maintenance_key
                ),
                self=self
        ):
            time.sleep(1)
            if (datetime.now() - start_date).seconds > timeout:
                raise TimeoutError(
                    "Event (id: {}) was not processed in the expected time"
                    " ({}s),".format(event_id, timeout)
                )
        # Make sure caddy and happroxy are reload and service registered
        time.sleep(1)
        logger.info(
            "Event %s takes %ss to consume",
            event_name, (datetime.now() - start_date).seconds
        )
        return event_id

    def get_app_from_kv(self, key):
        return json2obj(self.consul.kv.get(key))

    def wait_http_code(self, uri='', http_code=200, timeout=DEFAULT_TIMEOUT):
        """Loop until expected http code in the timeout allowed time"""
        uri = uri or const.url

        start_date = datetime.now()
        carry_on = True

        session = requests.Session()
        while carry_on:
            response = session.get(uri)
            if response.status_code == http_code:
                logging.info(
                    "uri %s gets expected http code %s (in %s s)",
                    uri, http_code, (datetime.now() - start_date).seconds
                )
                carry_on = False
                break
            if (datetime.now() - start_date).seconds > timeout:
                # we could add a setting to raise an Error, don't needs now
                logging.warning(
                    "Uri %s do not responds with http code %s in the given "
                    "time %ss",
                    uri,
                    http_code,
                    timeout
                )
                carry_on = False
                break
            time.sleep(0.1)
        session.close()

    def wait_logs(
        self, node_name, container_name, message, timeout=DEFAULT_TIMEOUT
    ):
        node = self.nodes.get(node_name)

        start_date = datetime.now()
        carry_on = True
        while carry_on:
            container = node['docker_cli'].containers.get(
                container_name
            )
            for line in container.logs(stream=True):
                if message in line.decode('utf-8'):
                    logging.info(
                        "%s where found in line %s (in %s s)",
                        message, line, (datetime.now() - start_date).seconds
                    )
                    carry_on = False
                    break

                if (datetime.now() - start_date).seconds > timeout:
                    # we could add a setting to raise an Error, don't needs now
                    logging.warning(
                        "We haven't found %s in the given time (%s s)",
                        message,
                        timeout
                    )
                    carry_on = False
                    break

    def cleanup_application(self, application):
        logging.info("start cleanup applications")
        if self.get_app_from_kv(application.app_key):
            self.destroy_and_wait(application)
        services = self.consul.catalog.service(
            application.name
        )
        if len(services) > 0:
            for service in services:
                self.consul.catalog.deregister(
                    service['Node'],
                    service_id=application.name
                )

        if self.consul.kv.get(
            'maintenance/{}'.format(application.name), default="default123"
        ) != "default123":
            self.consul.kv.delete(
                'maintenance/{}'.format(application.name)
            )
        if self.consul.kv.get(
            'migrate/{}'.format(application.name), default="default123"
        ) != "default123":
            self.consul.kv.delete(
                'migrate/{}'.format(application.name), recurse=True
            )
        # remove containers, old volumes and snapshots
        for name, node in self.nodes.items():
            cts = node['docker_cli'].containers.list(
                all=True,
                filters=dict(
                    name="{}*".format(application.volume_prefix),
                )
            )
            for ct in cts:
                ct.remove(v=True, force=True)
            volumes = node['docker_cli'].volumes.list(
                filters=dict(
                    name="{}*".format(application.volume_prefix),
                )
            )
            for volume in volumes:
                volume.remove(force=True)

            container = node['docker_cli'].containers.get(const.consul['container'])

            def filter_schedule(schedule):
                if schedule.volume.startswith("clusterlabtestservice"):
                    return True

            scheduled_to_cleanup = self.get_scheduled(
                container, filter_schedule
            )

            for schedule in scheduled_to_cleanup:
                schedule.minutes = 0
                container.exec_run('buttervolume schedule {}'.format(
                    str(schedule))
                )
            self.cleanup_snapshots(
                name, node['docker_cli'], application.volume_prefix
            )
            container.exec_run(
                'bash -c "rm -rf /deploy/{}*"'.format(
                    "cluster_lab_test_service"
                )
            )

    def cleanup_snapshots(
        self, node_name, docker_cli, volume_prefix
    ):
        try:
            docker_cli.images.get("integration_testing/btrfs_cleanup:latest")
        except docker.errors.ImageNotFound:
            docker_cli.images.pull('alpine', tag='latest')
            build = docker_cli.containers.create(
                'alpine:latest',
                command="sh -c 'apk update; apk add btrfs-progs'",
            )
            build.start()
            build.wait()
            build.commit(
                repository="integration_testing/btrfs_cleanup",
                tag='latest'
            )
            build.remove()
        try:
            docker_cli.containers.run(
                "integration_testing/btrfs_cleanup:latest",
                volumes={
                    '/var/lib/buttervolume/': {
                        'bind': '/var/lib/buttervolume',
                        'mode': 'rw'
                    },
                },
                command='sh -c "btrfs subvolume delete '
                        '/var/lib/buttervolume/snapshots/{}*"'.format(
                            volume_prefix
                        ),
                remove=True,
                privileged=True
            )
        except docker.errors.ContainerError as err:
            logger.debug(
                "Cleanup snapshots failed (or probably no snapshot "
                "were found) on node %s using: "
                "'btrfs subvolume delete /var/lib/buttervolume/snapshots/%s*' "
                "with following err:\n %r",
                node_name, volume_prefix, err
            )

    def get_scheduled(self, container, scheduled_filter, *args, **kwargs):
        """Get scheduled given a buttervolume container

        :param container: buttervolume container (docker api)
        :param scheduled_filter: a method to filter schedule, which must
                                 return ``True`` to add the schedul to the
                                 list and ``False`` to ignore it::

            def allow_all_filter(schedule, *args, **kwargs):
                '''In this example no thing filtered, all schedul will be
                in the returned list'''
                return True

        :param args: args that are forward to the filtered method
        :param kwargs: kwargs forwared to the filterd method
        :return: a list of schedule
        """
        if not scheduled_filter:
            def default_filter(schedule, *args, **kwargs):
                return True
            scheduled_filter = default_filter
        return [
            s for s in [
                Scheduled.from_str(s) for s in container.exec_run(
                    'buttervolume scheduled'
                ).output.decode('utf-8').split('\n') if s
            ] if scheduled_filter(s, *args, **kwargs)
        ]

    def create_service_data(self, domain=None):
        if not domain:
            domain = 'service.cluster.lab'
        session = requests.Session()
        name = str(uuid.uuid4())
        content = str(uuid.uuid4())
        response = session.post(
            'http://{}/example?name={}&content={}'.format(
                domain, name, content
            )
        )
        assert 201 == response.status_code
        location = response.headers['Location']
        id = response.json()['id']
        session.close()
        return (id, location, name, content)


def _json_object_hook(data):
    keys = [k.replace('-', '_') for k in data.keys()]
    return namedtuple('X', keys)(*data.values())


def json2obj(data):
    if not data:
        return None
    return json.loads(data, object_hook=_json_object_hook)


class Scheduled(object):
    """
    """

    _kind = None
    _kind_params = None
    _volume = None
    _minutes = None

    def __init__(self, kind, kind_params, volume, minutes):
        self._kind = kind
        self._kind_params = kind_params
        self._volume = volume
        self._minutes = minutes

    @property
    def kind(self):
        return self._kind

    @property
    def kind_params(self):
        return self._kind_params

    @property
    def minutes(self):
        return self._mintes

    @minutes.setter
    def minutes(self, value):
        self._mintes = value

    @property
    def volume(self):
        return self._volume

    @staticmethod
    def from_str(scheduled):
        schedule = scheduled.split(" ")
        if ':' in schedule[0]:
            kind_and_params = schedule[0].split(":")
            kind = kind_and_params[0]
            params = ":".join([str(s) for s in kind_and_params[1:]])
        else:
            kind, params = schedule[0], None
        return Scheduled(kind, params, schedule[2], schedule[1])

    def __str__(self):
        if self._kind_params:
            kind = ":".join([self._kind, self._kind_params])
        else:
            kind = self._kind
        return "{} {} {}".format(kind, self._minutes, self._volume)


class Application(object):
    """ class almost copied from cluster/consul/handler.py to generate
    service name
    """

    def __init__(self, repo_url, branch):
        self.repo_url, self.branch = repo_url.strip(), branch.strip()
        if self.repo_url.endswith('.git'):
            self.repo_url = self.repo_url[:-4]
        md5 = hashlib.md5(
            parse.urlparse(self.repo_url.lower()).path.encode('utf-8')
        ).hexdigest()
        repo_name = path.basename(self.repo_url.strip('/').lower())
        self.name = repo_name + (
            '_' + self.branch if self.branch else ''
        ) + '.' + md5[:5]  # don't need full md5

    @property
    def app_key(self):
        return 'app/{}'.format(self.name)

    @property
    def maintenance_key(self):
        return 'maintenance/{}'.format(self.name)

    @property
    def volume_prefix(self):
        return self.compose_project_name + '_'

    @property
    def compose_project_name(self):
        return self.name.replace('.', '').replace('_', '')
