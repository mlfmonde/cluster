import os
import docker

from . import const
from . import base_case
from . import cluster


class UpdateScriptBase(base_case.ClusterTestCase):
    script_name = 'update.sh'
    test_file_path = '/tmp/update.txt'

    def _is_script_deployed(self):
        # check that update.sh is deployed on master
        path = os.path.join(
            cluster.DEPLOY_ROOT_DIR,
            "{}-{}".format(self.application.name, self.app.deploy_id),
            self.__class__.script_name
        )
        self.test_file(
            self.master,
            const.consul['container'],
            path
        )

    def _get_test_file_content(self):
        """
        check that we pass in update.sh script
        update.sh of cluster_lab_test_service will write in 'test_file_path'
        """
        test_container = self.cluster.nodes[self.master][
            'docker_cli'].containers.get(self.app.ct.test)
        if not test_container:
            return ''

        try:
            res = self.cluster.nodes[self.master][
                'docker_cli'].containers.run(
                    'alpine:latest',
                    "ls {}".format(self.__class__.test_file_path),
                    volumes_from=[test_container.id],
                    remove=True
                )
        except docker.errors.ContainerError:
            # ls test_file not found exit non-zero
            res = ''

        if res and not isinstance(res, str):
            res = res.decode("utf-8")
        return res or ''

    def _clean_up_test_file(self):
        test_container = self.cluster.nodes[self.master][
            'docker_cli'].containers.get(self.app.ct.test)

        if test_container:
            self.cluster.nodes[self.master][
                'docker_cli'].containers.run(
                    'alpine:latest',
                    "rm {}".format(self.__class__.test_file_path),
                    volumes_from=[test_container.id],
                    remove=True
            )


class WhenDeployingANewServiceMasterSlaveWithNotAnyUpdate(UpdateScriptBase):
    """deploy new service with NOT any update asked in payload"""
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

    def becauseWeDeployTheService(self):
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
        self._is_script_deployed()

    def update_script_should_not_be_run(self):
        content = self._get_test_file_content()
        if content:
            self._clean_up_test_file()
        assert content == ''

    def cleanup_destroy_service(self):
        self.cluster.cleanup_application(self.application)


class WhenDeployingANewServiceMasterSlaveWithUpdate(UpdateScriptBase):
    """deploy new service WITH an update asked in payload"""
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

    def becauseWeDeployTheService(self):
        self.cluster.deploy_and_wait(
            master=self.master,
            slave=self.slave,
            application=self.application,
            update=True,  # ask for update script
        )
        # give a chance to let anyblok setting up its db
        self.app = self.cluster.get_app_from_kv(self.application.app_key)
        self.cluster.wait_logs(
            self.master, self.app.ct.anyblok, '--wsgi-host 0.0.0.0', timeout=30
        )
        self.cluster.wait_http_code(timeout=10)

    def update_script_should_be_deployed(self):
        self._is_script_deployed()

    def update_script_should_be_run(self):
        content = self._get_test_file_content()
        if content:
            self._clean_up_test_file()

        assert content.startswith(self.__class__.test_file_path)

    def cleanup_destroy_service(self):
        self.cluster.cleanup_application(self.application)
