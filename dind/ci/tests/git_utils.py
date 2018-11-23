import os
import subprocess
import tempfile

from . import const


class Git:

    @classmethod
    def tag_and_push(
        cls,
        repo='git@github.com:mlfmonde/cluster_lab_test_service',
        ref=None,
        tagname=None
    ):
        if const.git['force_https']:
            # use case of no ssh credentials
            https_repo = 'https://{}@github.com/'.format(
                os.getenv('GITHUB_API_TOKEN')
            )
            repo = repo.replace('git@github.com:', https_repo).replace(
                '.git', ''
            )

        with tempfile.TemporaryDirectory() as tmpDir:
            subprocess.check_output(
                [
                    'git',
                    'clone',
                    repo,
                    '-b',
                    ref,
                    tmpDir
                ]
            )
            subprocess.check_output(
                [
                    'git',
                    '-c',
                    'user.name="test Bot"',
                    '-c',
                    'user.email="mlf-adminsys@anybox.fr"',
                    '-C',
                    tmpDir,
                    'tag',
                    '-a',
                    '-f',
                    '-m',
                    tagname,
                    tagname
                ]
            )
            subprocess.check_output(
                [
                    'git',
                    '-C',
                    tmpDir,
                    'push',
                    'origin',
                    '-f',
                    tagname
                ]
            )

    @classmethod
    def remove_remote_tag(
        cls,
        repo='git@github.com:mlfmonde/cluster_lab_test_service',
        tagname=None
    ):
        if const.git['force_https']:
            # use case of no ssh credentials
            https_repo = 'https://{}@github.com/'.format(
                os.getenv('GITHUB_API_TOKEN')
            )
            repo = repo.replace('git@github.com:', https_repo).replace(
                '.git', ''
            )

        with tempfile.TemporaryDirectory() as tmpDir:
            subprocess.check_output(
                [
                    'git',
                    'clone',
                    repo,
                    tmpDir
                ]
            )
            subprocess.check_output(
                [
                    'git',
                    '-C',
                    tmpDir,
                    'push',
                    '--delete',
                    'origin',
                    tagname
                ]
            )
