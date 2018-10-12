import os
import requests

from . import const
from . import base_case
from . import cluster


class WhenMigrateDataBetweenServices(
    base_case.ClusterTestCase
):

    def given_two_services(self):
        self.prod = cluster.Application(
            'https://github.com/mlfmonde/cluster_lab_test_service',
            'without_caddyfile'
        )
        self.qualif = cluster.Application(
            'https://github.com/mlfmonde/cluster_lab_test_service',
            'qualif'
        )
        self.cluster.cleanup_application(self.prod)
        self.cluster.cleanup_application(self.qualif)
        self.cluster.deploy_and_wait(
            master='node3',
            slave='node4',
            application=self.prod,
        )
        self.cluster.deploy_and_wait(
            master='node1',
            slave='node2',
            application=self.qualif,
        )

        prod = self.cluster.get_app_from_kv(self.prod.app_key)
        self.cluster.wait_logs(
            prod.master, prod.ct.anyblok, '--wsgi-host 0.0.0.0', timeout=30
        )
        self.cluster.wait_http_code(timeout=10)
        qualif = self.cluster.get_app_from_kv(self.qualif.app_key)
        self.cluster.wait_logs(
            qualif.master, qualif.ct.anyblok, '--wsgi-host 0.0.0.0', timeout=30
        )
        self.cluster.wait_http_code(
            'http://service.qualif.cluster.lab', timeout=10
        )
        (
            self.prod_rec_id,
            self.prod_rec_loc,
            self.prod_rec_name,
            self.prod_rec_content
        ) = self.cluster.create_service_data()
        (
            self.qualif_rec_id,
            self.qualif_rec_loc,
            self.qualif_rec_name,
            self.qualif_rec_content
        ) = self.cluster.create_service_data(
            domain='service.qualif.cluster.lab'
        )

    def becauseWeMigrate(self):
        self.cluster.migrate_and_wait(self.prod, self.qualif)
        self.kvqualif = self.cluster.get_app_from_kv(self.qualif.app_key)
        self.kvprod = self.cluster.get_app_from_kv(self.prod.app_key)
        self.cluster.wait_http_code(
            'http://service.qualif.cluster.lab', timeout=60
        )

    def prod_service_should_return_created_prod_db_record(self):
        session = requests.Session()
        response = session.get(
            '{url}/example/{id}'.format(url=const.url, id=self.prod_rec_id)
        )
        assert self.prod_rec_name == response.text
        session.close()

    def qualif_service_should_return_created_prod_db_record(self):
        session = requests.Session()
        response = session.get(
            'http://service.qualif.cluster.lab/example/{}'.format(
                self.prod_rec_id
            )
        )
        assert self.prod_rec_name == response.text
        session.close()

    def prod_service_should_not_return_qualif_db_record(self):
        session = requests.Session()
        response = session.get(
            '{url}/example/{}'.format(url=const.url, id=self.qualif_rec_id)
        )
        assert response.text != self.qualif_rec_name
        session.close()

    def qualif_service_should_not_return_qualif_db_record(self):
        session = requests.Session()
        response = session.get(
            'http://service.qualif.cluster.lab/example/{}'.format(
                self.qualif_rec_id
            )
        )
        assert response.text != self.qualif_rec_name
        session.close()

    def prod_fsdata_should_return_prod_content(self):
        self.assert_file(
            'node3',
            self.kvprod.ct.anyblok,
            os.path.join("/var/test_service/", self.prod_rec_name),
            self.prod_rec_content
        )

    def prod_fsdata_should_not_return_qualif_content(self):
        file_path = os.path.join("/var/test_service/", self.qualif_rec_name)
        self.assert_file(
            'node3',
            self.kvprod.ct.anyblok,
            file_path,
            'cat: {}: No such file or directory\n'.format(file_path)
        )

    def qualif_fsdata_using_non_migrable_volume_should_return_qualif_content(
        self
    ):
        file_path = os.path.join("/var/test_service/", self.qualif_rec_name)
        self.assert_file(
            'node1',
            self.kvqualif.ct.anyblok,
            file_path,
            self.qualif_rec_content
        )

    def qualif_fsdata_should_not_return_prod_content(self):
        file_path = os.path.join("/var/test_service/", self.prod_rec_name)
        self.assert_file(
            'node1',
            self.kvqualif.ct.anyblok,
            file_path,
            'cat: {}: No such file or directory\n'.format(file_path)
        )

    def qualif_fsdata_should_return_migrate_content(self):
        self.assert_file(
            'node1',
            self.kvqualif.ct.anyblok,
            os.path.join("/var/test_service/", "migrate"),
            "migrate data from "
            "https://github.com/mlfmonde/cluster_lab_test_service "
            "branch: without_caddyfile "
            "to https://github.com/mlfmonde/cluster_lab_test_service "
            "branch: qualif"
        )

    def prod_fsdata_should_not_return_migrate_content(self):
        file_path = os.path.join("/var/test_service/", "migrate")
        self.assert_file(
            'node3',
            self.kvprod.ct.anyblok,
            file_path,
            'cat: {}: No such file or directory\n'.format(file_path)
        )

    def prod_cache_directory_should_not_return_qualif_content(self):
        file_path = os.path.join("/var/cache/", self.qualif_rec_name)
        self.assert_file(
            'node3',
            self.kvprod.ct.anyblok,
            file_path,
            'cat: {}: No such file or directory\n'.format(file_path)
        )

    def prod_cache_directory_should_return_prod_content(self):
        file_path = os.path.join("/var/cache/", self.prod_rec_name)
        self.assert_file(
            'node3',
            self.kvprod.ct.anyblok,
            file_path,
            self.prod_rec_content
        )

    def qualif_cache_directory_should_return_qualif_content(self):
        file_path = os.path.join("/var/cache/", self.qualif_rec_name)
        self.assert_file(
            'node1',
            self.kvqualif.ct.anyblok,
            file_path,
            self.qualif_rec_content
            # 'cat: {}: No such file or directory\n'.format(file_path),
        )

    def qualif_cache_directory_should_not_return_prod_content(self):
        file_path = os.path.join("/var/cache/", self.prod_rec_name)
        self.assert_file(
            'node1',
            self.kvqualif.ct.anyblok,
            file_path,
            'cat: {}: No such file or directory\n'.format(file_path),
        )

    def test_qualif_containers_should_run(self):
        self.assert_container_running_on(
            [self.kvqualif.ct.anyblok, self.kvqualif.ct.dbserver, ],
            ['node1', ]
        )

    def cleanup_destroy_service(self):
        self.cluster.cleanup_application(self.prod)
        self.cluster.cleanup_application(self.qualif)
