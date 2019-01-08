"""Base case, provide cluster specific assertion and cluster
facilities to make test easy to read.
"""
import os
import string

from docker import errors
from random import choice, randint

from . import const
from . import cluster


class ClusterTestCase:

    def __init__(self):
        self.cluster = cluster.Cluster()

    def assert_key_exists(self, key):
        """Make sure a key exists in the consul k/v store"""
        assert key in self.cluster.consul.kv

    def assert_volume_exists_only_on(self, volume, node_name, kind='local'):
        for name, node in self.cluster.nodes.items():
            volumes = node['docker_cli'].volumes.list(
                filters=dict(name=volume)
            )
            if node_name == name:
                assert len(volumes) == 1, \
                    "We expect 1 volume named {} on node {}, " \
                    "found {} volumes {}".format(
                        volume, node_name, len(volumes),
                        [v.name for v in volumes]
                    )
                assert volumes[0].attrs['Driver'] == kind,\
                    "Volume {} on node {} use {} driver, {} was " \
                    "expected".format(
                        volume, node_name, volumes[0].attrs['Driver'], kind
                    )
            else:
                assert len(volumes) == 0, \
                    "We expect 0 volume called {} on node {}, " \
                    "found {} volumes {}".format(
                        volume, name, len(volumes),
                        [v.name for v in volumes]
                    )

    def assert_consul_service_on_node(self, service_id, node):
        assert self.cluster.consul.catalog.service(
            service_id
        )[0]['Node'] == node

    def assert_project_cloned(self, application, deploy_id, nodes=None):
        if not nodes or not isinstance(nodes, list):
            nodes = []
        path = os.path.join(
            cluster.DEPLOY_ROOT_DIR,
            "{}-{}".format(application.name, deploy_id),
            ".env"
        )
        expected_content = "COMPOSE_PROJECT_NAME={}\n".format(
            application.compose_project_name
        )
        for name, _ in self.cluster.nodes.items():
            if name in nodes:
                self.assert_file(
                    name, const.consul['container'], path, expected_content
                )
            else:
                self.assert_file(
                    name,
                    const.consul['container'],
                    path,
                    "cat: can't open '{}': No such file or "
                    "directory\n".format(path),
                )

    def assert_btrfs_scheduled(self, kind, volume, nodes):
        """Assert btrfs scheduled are present on given nodes and absent on
        others"""

        def filter_schedule(schedule, kind, volume):
            if schedule.volume == volume and schedule.kind == kind:
                return True

        for name, node in self.cluster.nodes.items():
            container = node['docker_cli'].containers.get(
                const.consul['container']
            )
            scheduled = self.cluster.get_scheduled(
                container, filter_schedule, kind, volume
            )
            if name in nodes:
                assert len(scheduled) == 1, \
                    "We expected 1 schedul {} on node {} for {} volume, " \
                    "but {} were found.".format(
                        kind, name, volume, len(scheduled)
                    )
            else:
                assert len(scheduled) == 0, \
                    "We expected 0 schedul {} on node {} for {} volume, " \
                    "but {} were found.".format(
                        kind, name, volume, len(scheduled)
                    )

    def assert_container_running_on(self, containers, nodes):
        for name, node in self.cluster.nodes.items():
            for container_name in containers:
                try:
                    container = node['docker_cli'].containers.get(
                        container_name
                    )
                except errors.NotFound:
                    container = None
                    pass

            if name in nodes:
                assert container.status == 'running'
            else:
                assert container is None

    def _get_file_content(self, node, container, path):
        return self.cluster.nodes.get(node)['docker_cli'].containers.get(
            container
        ).exec_run(
            'sh -c "sleep 0.1; cat {}"'.format(path)
        ).output.decode('utf-8')

    def assert_file(self, node, container, path, expected_content):
        """Make sure expected content is present in a container:

        :param node     : node where service is running
        :param container: container name
        :param path     : path to the file (inside the docker container) to
                          assert content
        :param expected_content: content to assert
        """
        content = self._get_file_content(node, container, path)
        assert expected_content.strip() == content.strip(), \
            "Content not matched, expected: {} - got {}".format(
                expected_content, content
            )

    def test_file(self, node, container, path):
        """Make sure not empty file present in a container:

        :param node     : node where service is running
        :param container: container name
        :param path     : path to the file (inside the docker container) to
                          assert content
        """
        content = self._get_file_content(node, container, path)
        assert content

    def generate_run_id(self):
        allowedchars = string.ascii_lowercase + string.digits
        # do not use uuid to avoid length exceeded limitation
        return "".join(
            choice(allowedchars) for x in range(randint(3, 5))
        )
