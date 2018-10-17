"""This test make sure docker-compose install in consul is consistent with
docker in the host machine.

We had an issue while building a Dockerfile which copy a symlink working
in the container but not on the host machine was failing.

Si if the service is properly working on this dedicated branch that should
be fine
"""
import requests

from . import base_case
from . import cluster


class WhenDeployingAServiceThatCopySymlinkWhileBuildingImage(
    base_case.ClusterTestCase
):

    def given_a_cluster_without_test_service(self):
        self.application = cluster.Application(
            'https://github.com/mlfmonde/cluster_lab_test_service',
            'build_copy_symlink'
        )
        self.cluster.cleanup_application(self.application)
        self.master = 'node1'

    def becauseWeDeployTheService(self):
        self.cluster.deploy_and_wait(
            master=self.master,
            application=self.application,
        )
        # give a chance to initialized anyblok db
        self.app = self.cluster.get_app_from_kv(self.application.app_key)
        self.cluster.wait_logs(
            self.master, self.app.ct.anyblok, '--wsgi-host 0.0.0.0', timeout=30
        )
        self.cluster.wait_http_code('http://service.cluster.lab', timeout=10)

    def service_should_be_clone_in_the_expected_directory(self):
        self.assert_project_cloned(
            self.application,
            self.app.deploy_id,
            nodes=[self.master]
        )

    def service_should_return_HTTP_code_200(self):
        '''we may add a dns server (bind9?) at some point to manage DNS'''
        session = requests.Session()
        response = session.get('http://service.cluster.lab')
        assert 200 == response.status_code
        session.close()

    def cleanup_destroy_service(self):
        self.cluster.cleanup_application(self.application)
