import os
import docker

from . import const
from . import base_case
from . import cluster


class UpdateScriptBase(base_case.ClusterTestCase):
    update_script_name = 'update.sh'
    migrate_script_name = 'post_migrate.sh'

    update_test_file_path = '/tmp/update.txt'
    migrate_test_file_path = '/tmp/migrate.txt'

    def _is_file_deployed(self, file_name):
        """
        check that given file is deployed
        :param file_name: file name (no path)
        """
        file_path = os.path.join(
            cluster.DEPLOY_ROOT_DIR,
            "{app_id}-{deploy_id}".format(
                app_id=self.application.name,
                deploy_id=self.app.deploy_id
            ),
            file_name
        )
        self.test_file(
            self.master,
            const.consul['container'],
            file_path
        )

    def _get_test_file_content(self, file_path, clean_up_after=True):
        """
        get content of a given test file
        :param file_path: absolute path
        :param clean_up_after: True to immediatly clean file after check
        :return file content
        :rtype utf-8 str
        """
        test_container = self.cluster.nodes[self.master][
            'docker_cli'
        ].containers.get(self.app.ct.test)
        if not test_container:
            return ''

        try:
            res = self.cluster.nodes[self.master][
                'docker_cli'].containers.run(
                    'alpine:latest',
                    "ls {file_path}".format(file_path=file_path),
                    volumes_from=[test_container.id],
                    remove=True
                )
        except docker.errors.ContainerError:
            # ls test_file not found exit non-zero
            res = ''
            clean_up_after = False

        if clean_up_after:
            self._clean_up_test_file(
                file_path,
                test_container=test_container
            )
        if res and not isinstance(res, str):
            res = res.decode("utf-8")
        return res or ''

    def _clean_up_test_file(self, file_path, test_container=None):
        """
        delete given test file
        :param file_path: absolute path
        :param test_container: optional test container, else will be
            determined
        """
        test_container = test_container or self.cluster.nodes[self.master][
            'docker_cli'
        ].containers.get(self.app.ct.test)

        if test_container:
            self.cluster.nodes[self.master][
                'docker_cli'].containers.run(
                    'alpine:latest',
                    "rm {file_path}".format(file_path=file_path),
                    volumes_from=[test_container.id],
                    remove=True
            )


class WhenDeployingANewServiceMasterSlaveWithNotAnyUpdate(UpdateScriptBase):
    """deploy new service with NOT any update asked in payload"""
    def given_a_cluster_without_test_service(self):
        self.application = cluster.Application(
            'https://github.com/mlfmonde/cluster_lab_test_service',
            'update_script'  # testing through specific branch
                             # with dedicated post migrate script
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
            self.master,
            self.app.ct.anyblok,
            '--wsgi-host 0.0.0.0',
            timeout=30
        )
        self.cluster.wait_http_code(timeout=10)

    def post_migrate_script_should_be_deployed(self):
        self._is_file_deployed(self.__class__.migrate_script_name)

    def but_post_migrate_script_should_not_be_run(self):
        assert self._get_test_file_content(
            self.__class__.migrate_test_file_path
        ) == ''

    def update_script_should_be_deployed(self):
        self._is_file_deployed(self.__class__.update_script_name)

    def but_update_script_should_not_be_run(self):
        assert self._get_test_file_content(
            self.__class__.update_test_file_path
        ) == ''

    def cleanup_destroy_service(self):
        self.cluster.cleanup_application(self.application)


class WhenDeployingANewServiceMasterSlaveWithUpdate(UpdateScriptBase):
    """deploy new service WITH an update asked in payload"""
    def given_a_cluster_without_test_service(self):
        self.application = cluster.Application(
            'https://github.com/mlfmonde/cluster_lab_test_service',
            'update_script'  # testing through specific branch
                             # with dedicated post migrate script
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
            self.master,
            self.app.ct.anyblok,
            '--wsgi-host 0.0.0.0',
            timeout=30
        )
        self.cluster.wait_http_code(timeout=10)

    def post_migrate_script_should_be_deployed(self):
        # post_migrate should be deployed
        self._is_file_deployed(self.__class__.migrate_script_name)

    def and_post_migrate_script_should_be_run(self):
        # post_migrate should be applied before update script
        assert self._get_test_file_content(
            self.__class__.migrate_test_file_path
        ) != ''

    def update_script_should_be_deployed(self):
        self._is_file_deployed(self.__class__.update_script_name)

    def and_update_script_should_be_run(self):
        assert self._get_test_file_content(
            self.__class__.update_test_file_path
        ).startswith(self.__class__.update_test_file_path)

    def cleanup_destroy_service(self):
        self.cluster.cleanup_application(self.application)
