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
            repo = repo.replace('git@github.com:', 'https://github.com/').replace('.git', '')

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
