import subprocess
import tempfile


class Git:

    @classmethod
    def tag_and_push(
        cls,
        repo='git@github.com:mlfmonde/cluster_lab_test_service',
        ref=None,
        tagname=None
    ):
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
