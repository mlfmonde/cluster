import os
import requests
import subprocess
import time

from . import base_case
from . import cluster


class WhenSwitchToMaintenanceHapxConfigIsDisabled(base_case.ClusterTestCase):

    def given_a_cluster_with_a_test_service(self):
        self.application = cluster.Application(
            'https://github.com/mlfmonde/cluster_lab_test_service',
            'master'
        )
        self.cluster.cleanup_application(self.application)
        self.cluster.deploy_and_wait(
            master='node2',
            slave='node1',
            application=self.application,
        )
        app = self.cluster.get_app_from_kv(self.application.app_key)
        self.cluster.wait_logs(
            app.master, app.ct.anyblok, '--wsgi-host 0.0.0.0', timeout=30
        )
        self.cluster.wait_http_code('http://service.cluster.lab', timeout=10)
        session = requests.Session()
        response = session.get('http://service.cluster.lab')
        assert 200 == response.status_code
        session.close()

    def becauseWeAddMaintenanceKey(self):
        self.cluster.consul.kv.set(
            'maintenance/{}'.format(self.application.name), ""
        )
        # let haproxy reload its config
        time.sleep(1)

    def anyblok_ssh_should_be_inaccessible(self):
        try:
            subprocess.check_output(
                [
                    'ssh',
                    'root@{}'.format("service.cluster.lab"),
                    '-p',
                    '2244',
                    '-i',
                    os.path.join(
                        os.path.dirname(__file__), 'id_rsa_anyblok_ssh'
                    ),
                    '-o',
                    'StrictHostKeyChecking=no',
                    '-o',
                    'UserKnownHostsFile=/dev/null',
                    '-o',
                    'IdentitiesOnly=yes',
                    '-C',
                    'echo "test ssh"'
                ]
            )
        except subprocess.CalledProcessError:
            assert True
            return
        assert False

    def cleanup_destroy_service(self):
        self.cluster.cleanup_application(self.application)
