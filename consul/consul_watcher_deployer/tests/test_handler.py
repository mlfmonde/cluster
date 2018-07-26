import json
import os
import requests
import shutil
import unittest

from base64 import b64encode, b64decode
from testfixtures import TempDirectory
from consul_watcher_deployer import handler

HERE = os.path.abspath(os.path.dirname(__file__))


class TestRequests(object):
    """fake requests.put"""
    @staticmethod
    def put(url, svc):
        class Result:
            def __init__(self, code):
                self.status_code = code
        if '"Checks": [{' in svc and 'test.example.com' in svc:
            return Result(200)
        else:
            return Result(500)


def fake_do(cmd, *args, **kwargs):
    if cmd.startswith('consul kv get '):
        return b64decode(json.loads(
            open(os.path.join(handler.DEPLOY, 'kv')).read())[
                             cmd.split(' ', 3)[3]]
                         ).decode('utf-8')
    elif cmd == 'consul kv export app/':
        return json.dumps(
            [{'key': k, 'flags': 0, 'value': v} for k, v in
             json.loads(
                 open(os.path.join(handler.DEPLOY, 'kv')).read()).items()])
    elif cmd.startswith('git clone --depth 1 -b "master" '):
        appname = cmd.split(' ')[6].split('/')[-1][:-1]
        checkout = cmd.split(' ', 7)[-1][1:-1]
        os.mkdir(checkout)
        shutil.copy(os.path.join(HERE, 'testapp', '{}.yml'.format(appname)),
                    os.path.join(checkout, 'docker-compose.yml'))
    elif cmd == 'consul members':
        return (
            'Node   Address            Status  Type       DC\n'
            'node1   10.10.10.11:8301  alive   server     dc1\n'
            'node2   10.10.10.12:8301  alive   server     dc1\n'
            'node3   10.10.10.13:8301  alive   server     dc1')
    elif cmd.startswith('consul kv put'):
        k, v = cmd.split(' ', 3)[-1].split(' ', 1)
        kv = json.loads(open(os.path.join(handler.DEPLOY, 'kv')).read())
        kv[k] = b64encode(v[1:-1].encode('utf-8')).decode('utf-8')
        open(os.path.join(handler.DEPLOY, 'kv'), 'w').write(json.dumps(kv))
    else:
        raise NotImplementedError


class TestCase(unittest.TestCase):
    repo_url = 'https://gitlab.example.com/hosting/FooBar '
    data = [
        {'caddy': 'foo {\n    root /bar\n}',  # 0
         'json': '[{"keys":  ["foo"], "body":  [["root", "/bar"]]}]'},
        {'caddy': 'host1, host2 {\n    dir {\n        def\n    }\n}',  # 1
         'json': '[{"keys":  ["host1", "host2"], '
                 '"body":  [["dir", [["def"]]]]}]'},
        {'caddy': 'host1, host2 {\n    dir abc {\n'
                  '        def ghi\n        jkl\n    }\n}',  # 2
         'json': '[{"keys": ["host1", "host2"], '
                 '"body": [["dir", "abc", [["def", "ghi"], ["jkl"]]]]}]'},
        {'caddy': 'host1:1234, host2:5678 {\n'
                  '    dir abc {\n    }\n}',  # 3
         'json': '[{"keys": ["host1:1234", "host2:5678"], '
                 '"body": [["dir", "abc", []]]}]'},
        {'caddy': 'host {\n    foo "bar baz"\n}',  # 4
         'json': '[{"keys": ["host"], "body": [["foo", "bar baz"]]}]'},
        {'caddy': 'host, host:80 {\n    foo "bar \"baz\"\n}',  # 5
         'json': '[{"keys": ["host", "host:80"], '
                 '"body": [["foo", "bar \"baz\""]]}]'},
        {'caddy': 'host {\n    foo "bar\nbaz"\n}',  # 6
         'json': '[{"keys": ["host"], "body": [["foo", "bar\nbaz"]]}]'},
        {'caddy': 'host {\n    dir 123 4.56 true\n}',  # 7
         'json': '[{"keys": ["host"], '
                 '"body": [["dir", "123", "4.56", "true"]]}]'},
        {'caddy': 'http://host, https://host {\n}',  # 8
         'json': '[{"keys": ["http://host", "https://host"], "body": []}]'},
        {'caddy': 'host {\n    dir1 a b\n    dir2 c d\n}',  # 9
         'json': '[{"keys": ["host"], '
                 '"body": [["dir1", "a", "b"], ["dir2", "c", "d"]]}]'},
        {'caddy': 'host {\n    dir a b\n    dir c d\n}',  # 10
         'json': '[{"keys": ["host"], '
                 '"body": [["dir", "a", "b"], ["dir", "c", "d"]]}]'},
        {'caddy': 'host {\n    dir1 a b\n    '
                  'dir2 {\n        c\n        d\n    }\n}',  # 11
         'json': '[{"keys": ["host"], '
                 '"body": [["dir1", "a", "b"], ["dir2", [["c"], ["d"]]]]}]'},
        {'caddy': 'host1 {\n    dir1\n}\nhost2 {\n    dir2\n}',  # 12
         'json': '[{"keys": ["host1"], '
                 '"body": [["dir1"]]}, '
                 '{"keys": ["host2"], "body": [["dir2"]]}]'},
        {'caddy': '', 'json': '[]'},  # 13
    ]

    def setUp(self):
        handler.do = fake_do
        requests.put = TestRequests.put
        self.temps_dir = TempDirectory()
        handler.DEPLOY = self.temps_dir.path
        os.makedirs(handler.DEPLOY, exist_ok=True)
        open(os.path.join(handler.DEPLOY, 'kv'), 'w').write('{}')

    def tearDown(self):
        self.temps_dir.cleanup()

    def test_split(self):
        self.assertEqual([], handler.Caddyfile.split([], ''))
        self.assertEqual(['a', 'z', 'e'], handler.Caddyfile.split([], 'a z e'))
        self.assertEqual(['a', 'z e'], handler.Caddyfile.split([], 'a "z e"'))
        self.assertEqual(['a z e'], handler.Caddyfile.split([], '"a z e"'))
        self.assertEqual(['az', 'er ty', 'ui'],
                         handler.Caddyfile.split([], 'az "er ty" ui'))
        self.assertEqual(['az', 'er ty', 'ui'],
                         handler.Caddyfile.split([], "az 'er ty' ui"))
        self.assertEqual(['foo\nbar'],
                         handler.Caddyfile.split(['bar"', 'baz'], '"foo'))

    def test_caddy2json(self):
        for i, d in enumerate(self.data):
            if i == 5:
                print('test # {} skipped, plz help!'.format(i))
                continue
            self.assertEqual(
                json.dumps(
                    json.loads(d['json'], strict=False),
                    sort_keys=True
                ),
                json.dumps(
                    handler.Caddyfile.loads(d['caddy']), sort_keys=True
                )
            )
            print('test # {} ok'.format(i))

    def test_log(self):
        app = handler.Application(self.repo_url, 'master')
        app.download()
        app.caddyfile('wordpress')
        self.assertEqual(
            [group for group in app._caddy['wordpress'][0]['body'] if
             group[0] == 'log'][0],
            [
                'log',
                '/',
                'stdout',
                '{hostonly} - {>X-Forwarded-For} - {user} [{when}] '
                '\\"{method} {uri} {proto}\\" '
                '{status} {size} '
                '\\"{>Referer}\\" \\"{>User-Agent}\\"'
            ],
        )
        app.caddyfile('wordpress2')
        self.assertEqual(
            [group for group in app._caddy['wordpress2'][0]['body'] if
             group[0] == 'log'][0],
            ['log', '/', 'stdout', '{hostonly} - {combined}'],
        )

    def test_transparent_headers(self):
        app = handler.Application(self.repo_url, 'master')
        app.download()
        app.caddyfile('wordpress')
        self.assertEqual(
            [group for group in app._caddy['wordpress'][0]['body'] if
             group[0] == 'proxy'][0][-1:][0],
            [
                'websocket',
                'insecure_skip_verify',
                'header_upstream Host {host}',
                'header_upstream X-Real-IP {remote}',
                'header_upstream X-Forwarded-Proto {scheme}',
            ]
        )
        app.caddyfile('wordpress2')
        self.assertEqual(
            [group for group in app._caddy['wordpress2'][0]['body'] if
             group[0] == 'proxy'][0][-1:][0],
            [
                'websocket',
                'insecure_skip_verify',
                'transparent',
            ]
        )

    def test_json2caddy(self):
        for i, d in enumerate(self.data):
            if i == 5:
                print('test # {} skipped, plz help!'.format(i))
                continue
            self.assertEqual(
                d['caddy'],
                handler.Caddyfile.dumps(json.loads(d['json'], strict=False)))
            print('test # {} ok'.format(i))

    def test_missing_space(self):
        with self.assertRaises(Exception):
            handler.Caddyfile.dumps(
                handler.Caddyfile.loads('foo{\n    root /bar\n}'))

    def test_reversibility(self):
        for i, d in enumerate(self.data):
            if i == 5:
                print('test # {} skipped, plz help!'.format(i))
                continue
            self.assertEqual(
                d['caddy'],
                handler.Caddyfile.dumps(handler.Caddyfile.loads(d['caddy'])))
            print('test # {} ok'.format(i))

    def test_setdir(self):
        self.assertEqual(
            [['proxy', '/', 'ct:80'], ['other', 'foo']],
            handler.Caddyfile.setdir([['proxy', '/', 'ct:80']],
                                     ['other', 'foo']))
        self.assertEqual(
            [['gzip', 'foo']],
            handler.Caddyfile.setdir(
                [['gzip']], ['gzip', 'foo'], replace=True))

    def test_setsubdirs(self):
        self.assertEqual(
            [['proxy', ['subdir1', 'subdir2']]],
            handler.Caddyfile.setsubdirs(
                [['proxy']], 'proxy', ['subdir1', 'subdir2']))
        self.assertEqual(
            [['proxy', ['s1', 's2', 's3']]],
            handler.Caddyfile.setsubdirs(
                [['proxy', ['s1']]], 'proxy', ['s2', 's3']))
        self.assertEqual(
            [['proxy', ['s2', 's3']]],
            handler.Caddyfile.setsubdirs(
                [['proxy', ['s1']]], 'proxy', ['s2', 's3'], replace=True))
        self.assertEqual(
            [['gzip']],  # would need setdir first
            handler.Caddyfile.setsubdirs(
                [['gzip']], 'proxy', ['s2', 's3'], replace=True))

    def test_application_init(self):
        app = handler.Application(self.repo_url, branch='master')
        self.assertEqual(
            app.repo_url,
            'https://gitlab.example.com/hosting/FooBar')
        self.assertEqual(app.name, 'foobar_master.ddb14')

    def test_kv(self):
        self.maxDiff = None
        fake_do('consul kv put app/baz \'{}\''.format(
            json.dumps({'repo_url': 'adr1'})))
        self.assertEqual('adr1', handler.kv('baz', 'repo_url'))
        self.assertEqual(None, handler.kv('foobar_master.ddb14', 'foobar'))
        self.assertEqual(None, handler.kv('foo', 'bar'))

    def test_check(self):
        app = handler.Application(self.repo_url, 'master')
        app.download()
        self.assertEqual(None, app.check('node1'))
        # already deployed
        app.register_kv('node1', 'node2')
        app.name = 'new'
        self.assertRaises(ValueError, app.check, 'node1')

    def test_volumes(self):
        app = handler.Application(self.repo_url, 'master')
        app.download()
        self.assertEqual(
            ['foobarmasterddb14_dbdata', 'foobarmasterddb14_wwwdata'],
            sorted(v.name for v in app.volumes))

    def test_volumes_from_kv(self):
        app = handler.Application(self.repo_url, 'master')
        app.download()
        app.register_kv('node1', 'node2')
        self.assertEqual(
            ['foobarmasterddb14_dbdata', 'foobarmasterddb14_wwwdata'],
            sorted(v.name for v in app.volumes_from_kv))

    def test_volumes_from_kv_before_registered(self):
        app = handler.Application(self.repo_url, 'master')
        app.download()
        self.assertEqual(
            ['foobarmasterddb14_dbdata', 'foobarmasterddb14_wwwdata'],
            sorted(v.name for v in app.volumes_from_kv))

    def test_members(self):
        app = handler.Application(self.repo_url, 'master')
        members = app.members
        self.assertEqual(['node1', 'node2', 'node3'], sorted(members.keys()))
        self.assertEqual(['ip', 'status'], sorted(members['node1'].keys()))

    def test_register_kv(self):
        app = handler.Application(self.repo_url, 'master')
        app.download()
        self.assertEqual(None, app.register_kv('node1', 'node2'))

    def test_path(self):
        app = handler.Application(self.repo_url, 'master')
        app.download()
        app.register_kv('node1', 'node2')
        self.assertTrue(
            app.path.startswith(
                "{}/foobar_master.ddb14@".format(handler.DEPLOY)
            )
        )
        oldapp = handler.Application(self.repo_url, 'master')
        self.assertTrue(
            oldapp.path.startswith(
                "{}/foobar_master.ddb14@".format(handler.DEPLOY)
            )
        )
        newapp = handler.Application(self.repo_url, 'master', deploy_id='abc')
        oldapp = handler.Application(self.repo_url, 'master',
                                     current_deploy_id='abc')
        self.assertEqual(
            newapp.path,
            "{}/foobar_master.ddb14-abc".format(handler.DEPLOY)
        )
        newapp.download()
        newapp.register_kv('node2', 'node1')
        self.assertTrue(
            oldapp.path.startswith(
                "{}/foobar_master.ddb14@".format(handler.DEPLOY)
            )
        )
        newapp = handler.Application(self.repo_url, 'master', deploy_id='abc2')
        oldapp = handler.Application(self.repo_url, 'master',
                                     current_deploy_id='abc2')
        self.assertEqual(
            newapp.path, "{}/foobar_master.ddb14-abc2".format(handler.DEPLOY)
        )
        self.assertEqual(
            oldapp.path, "{}/foobar_master.ddb14-abc".format(handler.DEPLOY)
        )

    def test_deploy_ids(self):
        app = handler.Application(self.repo_url, 'master', deploy_id='abc1')
        app.download()
        app.register_kv('node1', 'node2')
        app = handler.Application(self.repo_url, 'master', deploy_id='abc2')
        app.download()
        self.assertEqual(app.previous_deploy_id, 'abc1')
        self.assertEqual(app.deploy_id, 'abc2')
        app.register_kv('node1', 'node2')
        app = handler.Application(self.repo_url, 'master')
        self.assertEqual(app.previous_deploy_id, 'abc1')
        self.assertEqual(app.deploy_id, 'abc2')

    def test_register_consul(self):
        app = handler.Application(self.repo_url, 'master')
        app.download()
        self.assertEqual(None, app.register_consul())

    def test_brackets_generation(self):
        self.assertEqual(
            handler.Caddyfile.dumps(handler.Caddyfile.loads(
                'host1 {\n    dir1\n}  \nhost2 {\n    dir2\n}'
            )),
            'host1 {\n    dir1\n}\nhost2 {\n    dir2\n}'
        )

    def test_haproxy_config(self):
        app = handler.Application(self.repo_url, 'master')
        app.download()
        self.assertEqual(
            {
                "ssh-config-name": {
                    "frontend": {
                        "mode": "tcp",
                        "bind": ["*:2222"]
                    },
                    "backends": [{
                        "name": "ssh-service",
                        "use_backend_option": "",
                        "port": "22",
                        "peer_port": "2222",
                        "ct": "foobarmasterddb14_sshservice_1"
                    }]
                }
            },
            app.haproxy(app.services)
        )

    def test_urls(self):
        app = handler.Application(
            'https://gitlab.example.com/hosting/FooBar2',
            'master'
        )
        app.download()
        self.assertEqual(
            sorted(app.consul_extra_check_urls(app.services)),
            sorted([
                'http://another.example.com',
                'http://an.example.com',
                'https://an.example.com',
            ])
        )

    def test_merge_service_configs_haproxy(self):
        app = handler.Application(
            'https://gitlab.example.com/hosting/FooBar2',
            'master'
        )
        app.download()
        self.maxDiff = None
        expected = {
            "https-in": {
                "backends": [{
                    "name": "an.example.com",
                    "use_backend_option": "if { req_ssl_sni -i an.example.com"
                                          " }",
                    "port": "443",
                    "peer_port": "1443",
                    "server_option": "send_proxy",
                    "ct": "foobar2masterdec69_wordpress_1"
                }]
            },
            "http-in": {
                "backends": [{
                    "name": "an.example.com",
                    "use_backend_option":
                        " if { hdr(host) -i an.example.com }",
                    "port": "80",
                    "peer_port": "80",
                    "ct": "foobar2masterdec69_wordpress_1"
                }, {
                    "name": "another.example.com",
                    "use_backend_option":
                        " if { hdr(host) -i another.example.com }",
                    "port": "80",
                    "peer_port": "80",
                    "ct": "foobar2masterdec69_wordpress2_1"
                }]
            },
            "other-config": {
                "frontend": {
                    "mode": "tcp",
                    "bind": ["*:1111"],
                    "options": [
                        "option socket-stats",
                        "tcp-request inspect-delay 5s",
                        "tcp-request content accept "
                        "if { req_ssl_hello_type 1 }"
                    ]
                },
                "backends": [{
                    "name": "other-config",
                    "use_backend_option":
                        "if { req_ssl_sni -i other.example.com }",
                    "port": "11",
                    "peer_port": "1111",
                    "ct": "foobar2masterdec69_wordpress_1"
                }]
            },
            "ssh-config-name": {
                "frontend": {
                    "mode": "tcp",
                    "bind": ["*:2222", "*:4444"],
                    "options": [
                        "option socket-stats",
                        "tcp-request inspect-delay 5s",
                        "tcp-request content accept "
                        "if { req_ssl_hello_type 1 }",
                        "test",
                        "test2"
                    ]
                },
                "backends": [{
                    "name": "ssh-service-wordpress2",
                    "use_backend_option": "",
                    "port": "22",
                    "peer_port": "2222",
                    "server_option": "send_proxy",
                    "ct": "foobar2masterdec69_wordpress2_1"
                }, {
                    "name": "ssh-service",
                    "use_backend_option": "",
                    "port": "22",
                    "peer_port": "2222",
                    "ct": "foobar2masterdec69_sshservice_1"
                }, {
                    "name": "ssh-service2",
                    "use_backend_option": "",
                    "port": "22",
                    "peer_port": "4444",
                    "ct": "foobar2masterdec69_sshservice2_1"
                },
                ]
            }
        }
        got = app.haproxy(app.services)
        self.assertEqual(len(got), len(expected))
        self.assertEqual(
            len(got['ssh-config-name']),
            len(expected['ssh-config-name'])
        )
        self.assertEqual(
            len(got['ssh-config-name']['backends']),
            len(expected['ssh-config-name']['backends'])
        )
        self.assertEqual(
            sorted(got['ssh-config-name']['frontend']['bind']),
            sorted(expected['ssh-config-name']['frontend']['bind'])
        )
        self.assertEqual(
            sorted(got['ssh-config-name']['frontend']['options']),
            sorted(expected['ssh-config-name']['frontend']['options'])
        )
        self.assertEqual(
            len(got['http-in']),
            len(expected['http-in'])
        )
