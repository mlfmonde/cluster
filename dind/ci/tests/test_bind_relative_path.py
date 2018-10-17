"""This make sure default cluster configuration allow to deploy service that
bind a volume using a relative path likes::

    volumes:
      - ./test:/tmp/test

At some point we use to get 2 issues while deploying this kind of services:

* path in consul docker container and on the host machine mismatched
* the consul handler add columns ":" while cloning project service definition
  which breaks docker binding as it use columns as separator between
  source (on the host machine) and targe (in the container)
"""
import requests

from . import base_case
from . import cluster


class WhenDeployingAServiceThatBindARelativePath(
    base_case.ClusterTestCase
):

    def given_a_cluster_without_test_service(self):
        self.application = cluster.Application(
            'https://github.com/mlfmonde/cluster_lab_test_service',
            'bind_relative_path'
        )
        self.cluster.cleanup_application(self.application)
        self.master = 'core1'

    def becauseWeDeployTheService(self):
        self.cluster.deploy_and_wait(
            master=self.master,
            application=self.application,
        )
        self.app = self.cluster.get_app_from_kv(self.application.app_key)
        self.cluster.wait_logs(
            self.master, self.app.ct.anyblok, '--wsgi-host 0.0.0.0', timeout=30
        )
        self.cluster.wait_http_code('http://service.cluster.lab', timeout=10)

    def service_should_return_HTTP_code_200(self):
        '''we may add a dns server (bind9?) at some point to manage DNS'''
        session = requests.Session()
        response = session.get('http://service.cluster.lab')
        assert 200 == response.status_code
        session.close()

    def service_should_be_clone_in_the_expected_directory(self):
        self.assert_project_cloned(
            self.application,
            self.app.deploy_id,
            nodes=[self.master]
        )

    def bind_file_should_be_availaible_in_container(self):
        self.assert_file(
            self.master,
            self.app.ct.anyblok,
            "/tmp/test_bind_file",
            "bind file content\n"
        )

    def bind_directory_should_be_availaible_in_container(self):
        self.assert_file(
            self.master,
            self.app.ct.anyblok,
            "/tmp/test_bind_directory/test_bind_directory",
            "bind directory content\n"
        )

    def cleanup_destroy_service(self):
        self.cluster.cleanup_application(self.application)
