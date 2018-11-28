import os
import docker

from . import const
from . import base_case
from . import cluster


class WhenDeployingANewServiceMasterSlave(base_case.ClusterTestCase):

    def given_a_cluster_without_test_service(self):
        self.application = cluster.Application(
            'https://github.com/mlfmonde/cluster_lab_test_service',
            #'master'
            'update_script'  # TODO merge update_script to master
                             # and reactive master
        )
        self.cluster.cleanup_application(self.application)
        self.master = 'node1'
        self.slave = 'node2'

    def becauseWeDeployTheServiceWithUpdateScript(self):
        self.cluster.deploy_and_wait(
            master=self.master,
            slave=self.slave,
            application=self.application,
        )
        # give a chance to let anyblok setting up its db
        self.app = self.cluster.get_app_from_kv(self.application.app_key)
        self.cluster.wait_logs(
            self.master, self.app.ct.anyblok, '--wsgi-host 0.0.0.0', timeout=30
        )
        self.cluster.wait_http_code(timeout=10)

    def update_script_should_be_deployed(self):
        # check that update.sh is deployed on master
        path = os.path.join(
            cluster.DEPLOY_ROOT_DIR,
            "{}-{}".format(self.application.name, self.app.deploy_id),
            "update.sh"
        )
        self.test_file(
            self.master,
            const.consul['container'],
            path,
        )

    def update_script_should_be_run(self):
        # check that we pass in update.sh script
        test_file = '/tmp/update.txt'
        test_container = self.cluster.nodes[self.master][
            'docker_cli'].containers.get(self.app.ct.test)

        try:
            res = self.cluster.nodes[self.master][
                'docker_cli'].containers.run(
                    'alpine:latest',
                    "ls {}".format(test_file),
                    volumes_from=[test_container.id],
                    remove=True
                )
        except docker.errors.ContainerError:
            # ls test_file not found exit non-zero
            res = ''
        assert res and res.decode("utf-8").startswith(test_file)

        self.cluster.nodes[self.master][
            'docker_cli'].containers.run(
                'alpine:latest',
                "rm {}".format(test_file),
                volumes_from=[test_container.id],
                remove=True
        )

    def cleanup_destroy_service(self):
        self.cluster.cleanup_application(self.application)
