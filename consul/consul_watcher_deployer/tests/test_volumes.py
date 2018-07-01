from unittest import TestCase
from consul_watcher_deployer.handler import Volume


class TestVolumes(TestCase):

    def test_volume(self):
        vol = Volume('test')
        self.assertEqual('test', vol.name)
