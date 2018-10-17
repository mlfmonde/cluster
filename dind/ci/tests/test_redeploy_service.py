import os
import requests
import subprocess

from . import base_case
from . import cluster


class WhenDeployingServiceWithSameSlaveMaster(
    base_case.ClusterTestCase
):

    def given_a_cluster_with_running_service(self):
        self.application = cluster.Application(
            'https://github.com/mlfmonde/cluster_lab_test_service',
            'master'
        )
        self.cluster.cleanup_application(self.application)
        self.cluster.deploy_and_wait(
            master='node2',
            slave='node3',
            application=self.application,
        )
        app = self.cluster.get_app_from_kv(self.application.app_key)
        self.cluster.wait_logs(
            app.master, app.ct.anyblok, '--wsgi-host 0.0.0.0', timeout=30
        )
        self.cluster.wait_http_code('http://service.cluster.lab', timeout=10)
        (
            self.record_id,
            self.record_location,
            self.record_name,
            self.record_content
        ) = self.cluster.create_service_data()

        self.master = 'node2'
        self.slave = 'node3'

    def becauseWeDeployTheService(self):
        self.cluster.deploy_and_wait(
            master=self.master,
            slave=self.slave,
            application=self.application,
        )
        self.app = self.cluster.get_app_from_kv(self.application.app_key)
        self.cluster.wait_logs(
            self.master, self.app.ct.anyblok, '--wsgi-host 0.0.0.0', timeout=30
        )
        self.cluster.wait_http_code('http://service.cluster.lab', timeout=10)

    def a_key_must_be_in_the_kv_store(self):
        self.assert_key_exists(self.application.app_key)

    def service_should_be_clone_in_the_expected_directory(self):
        self.assert_project_cloned(
            self.application,
            self.app.deploy_id,
            nodes=[self.master, self.slave]
        )

    def master_salve_should_be_correct_in_kv_store(self):
        assert (self.master, self.slave) == (self.app.master, self.app.slave)

    def kv_must_know_2_btrfs_volumes(self):
        assert len(self.app.volumes) == 2

    def btrfs_pg_volume_should_exists_only_on_master(self):
        self.assert_volume_exists_only_on(
            self.application.volume_prefix + 'dbdata',
            self.master,
            kind='anybox/buttervolume:latest'
        )

    def btrfs_anyblok_volume_should_exists_on_master(self):
        self.assert_volume_exists_only_on(
            self.application.volume_prefix + 'anyblok_data',
            self.master,
            kind='anybox/buttervolume:latest'
        )

    def cache_volume_must_exists_on_master(self):
        self.assert_volume_exists_only_on(
            self.application.volume_prefix + 'cache_data',
            self.master,
            kind='local'
        )

    def service_should_return_freshly_created_db_record(self):
        session = requests.Session()
        response = session.get(
            'http://service.cluster.lab/example/{}'.format(self.record_id)
        )
        assert self.record_name == response.text
        session.close()

    def anyblok_ssh_should_be_accessible(self):
        assert subprocess.check_output([
            'ssh',
            'root@{}'.format("service.cluster.lab"),
            '-p',
            '2244',
            '-i',
            os.path.join(os.path.dirname(__file__), 'id_rsa_anyblok_ssh'),
            '-o',
            'StrictHostKeyChecking=no',
            '-o',
            'UserKnownHostsFile=/dev/null',
            '-o',
            'IdentitiesOnly=yes',
            '-C',
            'cat /anyblok_data/{}'.format(self.record_name)
        ]).decode('utf-8') == self.record_content

    def anyblok_fsdata_should_be_there(self):
        self.assert_file(
            self.master,
            self.app.ct.anyblok,
            os.path.join("/var/test_service/", self.record_name),
            self.record_content
        )

    def purge_pg_volume_must_be_scheduled(self):
        self.assert_btrfs_scheduled(
            'purge',
            self.application.volume_prefix + 'dbdata',
            [self.master, self.slave],
        )

    def purge_anyblok_volume_must_be_scheduled(self):
        self.assert_btrfs_scheduled(
            'purge',
            self.application.volume_prefix + 'anyblok_data',
            [self.master, self.slave],
        )

    def replicate_pg_volume_must_be_scheduled(self):
        self.assert_btrfs_scheduled(
            'replicate',
            self.application.volume_prefix + 'dbdata',
            [self.master],
        )

    def replicate_anyblok_volume_must_be_scheduled(self):
        self.assert_btrfs_scheduled(
            'replicate',
            self.application.volume_prefix + 'anyblok_data',
            [self.master],
        )

    def non_btrfs_volume_should_not_get_schedule(self):
        self.assert_btrfs_scheduled(
            '',
            self.application.volume_prefix + 'cache_data',
            [],
        )

    def consul_service_should_be_registered_on_the_master_node(self):
        self.assert_consul_service_on_node(
            self.application.name,
            self.master
        )

    def test_service_containers_should_run(self):
        self.assert_container_running_on(
            [self.app.ct.anyblok, self.app.ct.dbserver, ],
            [self.master]
        )

    def cleanup_destroy_service(self):
        self.cluster.cleanup_application(self.application)
