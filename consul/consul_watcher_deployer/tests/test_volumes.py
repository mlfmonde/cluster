from consul_watcher_deployer.handler import Volume, LABEL_NON_MIGRABLE_VOLUME
from unittest.mock import Mock
from unittest import TestCase


class TestVolumes(TestCase):
    def test_volume(self):
        vol = Volume('test')
        self.assertEqual('test', vol.name)

    def test_non_migrable(self):
        vol = Volume('test')
        vol.get_docker_client = Mock(return_value=Mock(
                volumes={
                    'test': Mock(
                        attrs={'Labels': {LABEL_NON_MIGRABLE_VOLUME: "tRue"}}
                    )
                }
            )
        )
        self.assertFalse(vol.migrable_volume)

        vol.get_docker_client = Mock(return_value=Mock(
                volumes={
                    'test': Mock(
                        attrs={'Labels': {LABEL_NON_MIGRABLE_VOLUME: "false"}}
                    )
                }
            )
        )
        self.assertTrue(vol.migrable_volume)

        vol.get_docker_client = Mock(return_value=Mock(
                volumes={
                    'test': Mock(
                        attrs={'Labels': {"test": "fake"}}
                    )
                }
            )
        )

        vol.get_docker_client = Mock(return_value=Mock(
                volumes={
                    'test': Mock(
                        attrs={'Labels': None}
                    )
                }
            )
        )
        self.assertTrue(vol.migrable_volume)
