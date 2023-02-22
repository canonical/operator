# Copyright 2023 Canonical Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import datetime
import os
import pathlib
import tempfile
import unittest

import pytest

import ops
import ops.pebble
from ops._private import yaml
from ops.pebble import APIError, FileInfo, FileType, ServiceInfo, SystemInfo


class PushPullCase:
    """Test case for table-driven tests."""

    def __init__(self, **vals):
        self.pattern = None
        self.dst = None
        self.errors = []
        self.want = set()
        for key, val in vals.items():
            setattr(self, key, val)


recursive_list_cases = [
    PushPullCase(
        name='basic recursive list',
        path='/',
        files=['/foo/bar.txt', '/baz.txt'],
        want={'/foo/bar.txt', '/baz.txt'},
    ),
    PushPullCase(
        name='basic recursive list reverse',
        path='/',
        files=['/baz.txt', '/foo/bar.txt'],
        want={'/foo/bar.txt', '/baz.txt'},
    ),
    PushPullCase(
        name='directly list a (non-directory) file',
        path='/baz.txt',
        files=['/baz.txt'],
        want={'/baz.txt'},
    ),
]


@pytest.mark.parametrize('case', recursive_list_cases)
def test_recursive_list(case):
    def list_func_gen(file_list):
        args = {
            'last_modified': datetime.time(),
            'permissions': 0o777,
            'size': 42,
            'user_id': 0,
            'user': 'foo',
            'group_id': 1024,
            'group': 'bar',
        }
        file_infos, dirs = [], set()
        for f in file_list:
            file_infos.append(
                FileInfo(
                    path=f,
                    name=os.path.basename(f),
                    type=FileType.FILE,
                    **args))

            # collect all the directories for the test case's files
            dirpath = os.path.dirname(f)
            if dirpath != '' and dirpath not in dirs:
                dirs.update(dirpath)
                file_infos.append(
                    FileInfo(
                        path=dirpath,
                        name=os.path.basename(dirpath),
                        type=FileType.DIRECTORY,
                        **args))

        def inner(path):
            path = str(path)
            matches = []
            for info in file_infos:
                # exclude file infos for separate trees and also
                # for the directory we are listing itself - we only want its contents.
                if not info.path.startswith(path) or (
                        info.type == FileType.DIRECTORY and path == info.path):
                    continue
                # exclude file infos for files that are in subdirectories of path.
                # we only want files that are directly in path.
                if info.path[len(path):].find('/') > 0:
                    continue
                matches.append(info)
            return matches
        return inner

    # test raw business logic for recursion and dest path construction
    files = set()
    case.path = os.path.normpath(case.path)
    case.files = [os.path.normpath(f) for f in case.files]
    case.want = {os.path.normpath(f) for f in case.want}
    for f in ops.model.Container._list_recursive(
            list_func_gen(
                case.files), pathlib.Path(
                case.path)):
        path = f.path
        if case.dst is not None:
            # test destination path construction
            _, path = f.path, ops.model.Container._build_destpath(
                f.path, case.path, case.dst)
        files.add(path)
    assert case.want == files, f'case {case.name!r} has wrong files: want {case.want}, got {files}'


recursive_push_pull_cases = [
    PushPullCase(
        name='basic push/pull',
        path='/foo',
        dst='/baz',
        files=['/foo/bar.txt'],
        want={'/baz/foo/bar.txt'},
    ),
    PushPullCase(
        name='push/pull - trailing slash',
        path='/foo/',
        dst='/baz',
        files=['/foo/bar.txt'],
        want={'/baz/foo/bar.txt'},
    ),
    PushPullCase(
        name='basic push/pull - root',
        path='/',
        dst='/baz',
        files=['/foo/bar.txt'],
        want={'/baz/foo/bar.txt'},
    ),
    PushPullCase(
        name='basic push/pull - multicomponent path',
        path='/foo/bar',
        dst='/baz',
        files=['/foo/bar/baz.txt'],
        want={'/baz/bar/baz.txt'},
    ),
    PushPullCase(
        name='push/pull contents',
        path='/foo/*',
        dst='/baz',
        files=['/foo/bar.txt'],
        want={'/baz/bar.txt'},
    ),
    PushPullCase(
        name='directly push/pull a specific file',
        path='/foo/bar.txt',
        dst='/baz',
        files=['/foo/bar.txt'],
        want={'/baz/bar.txt'},
    ),
    PushPullCase(
        name='error on push/pull non-existing file',
        path='/foo/bar.txt',
        dst='/baz',
        files=[],
        errors={'/foo/bar.txt'},
    ),
    PushPullCase(
        name='push/pull multiple non-existing files',
        path=['/foo/bar.txt', '/boo/far.txt'],
        dst='/baz',
        files=[],
        errors={'/foo/bar.txt', '/boo/far.txt'},
    ),
    PushPullCase(
        name='push/pull file and dir combo',
        path=['/foo/foobar.txt', '/foo/bar'],
        dst='/baz',
        files=['/foo/bar/baz.txt', '/foo/foobar.txt', '/quux.txt'],
        want={'/baz/foobar.txt', '/baz/bar/baz.txt'},
    ),
]


@pytest.mark.parametrize('case', recursive_push_pull_cases)
def test_recursive_push_and_pull(case):
    # full "integration" test of push+pull
    harness = ops.testing.Harness(ops.charm.CharmBase, meta='''
        name: test-app
        containers:
          foo:
            resource: foo-image
        ''')
    harness.begin()
    harness.set_can_connect('foo', True)
    c = harness.model.unit.containers['foo']

    # create push test case filesystem structure
    push_src = tempfile.TemporaryDirectory()
    for file in case.files:
        fpath = os.path.join(push_src.name, file[1:])
        os.makedirs(os.path.dirname(fpath), exist_ok=True)
        with open(fpath, 'w') as f:
            f.write('hello')

    # test push
    if isinstance(case.path, list):
        # swap slash for dummy dir on root dir so Path.parent doesn't return tmpdir path component
        # otherwise remove leading slash so we can do the path join properly.
        push_path = [os.path.join(push_src.name, p[1:] if len(p) > 1 else 'foo')
                     for p in case.path]
    else:
        # swap slash for dummy dir on root dir so Path.parent doesn't return tmpdir path component
        # otherwise remove leading slash so we can do the path join properly.
        push_path = os.path.join(push_src.name, case.path[1:] if len(case.path) > 1 else 'foo')

    errors = []
    try:
        c.push_path(push_path, case.dst)
    except ops.model.MultiPushPullError as err:
        if not case.errors:
            raise
        errors = {src[len(push_src.name):] for src, _ in err.errors}

    assert case.errors == errors, \
        f'push_path gave wrong expected errors: want {case.errors}, got {errors}'
    for fpath in case.want:
        assert c.exists(fpath), f'push_path failed: file {fpath} missing at destination'

    # create pull test case filesystem structure
    pull_dst = tempfile.TemporaryDirectory()
    for fpath in case.files:
        c.push(fpath, 'hello', make_dirs=True)

    # test pull
    errors = []
    try:
        c.pull_path(case.path, os.path.join(pull_dst.name, case.dst[1:]))
    except ops.model.MultiPushPullError as err:
        if not case.errors:
            raise
        errors = {src for src, _ in err.errors}

    assert case.errors == errors, \
        f'pull_path gave wrong expected errors: want {case.errors}, got {errors}'
    for fpath in case.want:
        assert c.exists(fpath), f'pull_path failed: file {fpath} missing at destination'


class TestContainerPebble(unittest.TestCase):
    def setUp(self):
        meta = ops.charm.CharmMeta.from_yaml("""
name: k8s-charm
containers:
  c1:
    k: v
""")
        backend = MockPebbleBackend('myapp/0')
        self.model = ops.model.Model(meta, backend)
        self.container = self.model.unit.containers['c1']
        self.pebble = self.container.pebble

    def test_socket_path(self):
        self.assertEqual(self.pebble.socket_path, '/charm/containers/c1/pebble.socket')

    def test_autostart(self):
        self.container.autostart()
        self.assertEqual(self.pebble.requests, [('autostart',)])

    def test_replan(self):
        self.container.replan()
        self.assertEqual(self.pebble.requests, [('replan',)])

    def test_can_connect(self):
        self.pebble.responses.append(SystemInfo.from_dict({'version': '1.0.0'}))
        self.assertTrue(self.container.can_connect())
        self.assertEqual(self.pebble.requests, [('get_system_info',)])

    def test_start(self):
        self.container.start('foo')
        self.container.start('foo', 'bar')
        self.assertEqual(self.pebble.requests, [
            ('start', ('foo',)),
            ('start', ('foo', 'bar')),
        ])

    def test_start_no_arguments(self):
        with self.assertRaises(TypeError):
            self.container.start()

    def test_stop(self):
        self.container.stop('foo')
        self.container.stop('foo', 'bar')
        self.assertEqual(self.pebble.requests, [
            ('stop', ('foo',)),
            ('stop', ('foo', 'bar')),
        ])

    def test_stop_no_arguments(self):
        with self.assertRaises(TypeError):
            self.container.stop()

    def test_restart(self):
        self.container.restart('foo')
        self.container.restart('foo', 'bar')
        self.assertEqual(self.pebble.requests, [
            ('restart', ('foo',)),
            ('restart', ('foo', 'bar')),
        ])

    def test_restart_fallback(self):
        def restart_services(services):
            self.pebble.requests.append(('restart', services))
            raise APIError({}, 400, "", "")

        self.pebble.restart_services = restart_services
        # Setup the Pebble client to respond to a call to get_services()
        self.pebble.responses.append([
            ServiceInfo.from_dict({'name': 'foo', 'startup': 'enabled', 'current': 'active'}),
            ServiceInfo.from_dict({'name': 'bar', 'startup': 'enabled', 'current': 'inactive'}),
        ])

        self.container.restart('foo', 'bar')
        self.assertEqual(self.pebble.requests, [
            # This is the first request, which in real life fails with APIError on older versions
            ('restart', ('foo', 'bar')),
            # Next the code should loop over the started services, and stop them
            ('get_services', ('foo', 'bar')),
            ('stop', ('foo',)),
            # Then start all the specified services
            ('start', ('foo', 'bar'))
        ])

    def test_restart_fallback_non_400_error(self):
        def restart_services(services):
            raise APIError({}, 500, "", "")

        self.pebble.restart_services = restart_services
        with self.assertRaises(ops.pebble.APIError) as cm:
            self.container.restart('foo')
        self.assertEqual(cm.exception.code, 500)

    def test_restart_no_arguments(self):
        with self.assertRaises(TypeError):
            self.container.restart()

    def test_type_errors(self):
        meta = ops.charm.CharmMeta.from_yaml("""
name: k8s-charm
containers:
  c1:
    k: v
""")
        # Only the real pebble Client checks types, so use actual backend class
        backend = ops.model._ModelBackend('myapp/0')
        model = ops.model.Model(meta, backend)
        container = model.unit.containers['c1']

        with self.assertRaises(TypeError):
            container.start(['foo'])

        with self.assertRaises(TypeError):
            container.stop(['foo'])

    def test_add_layer(self):
        self.container.add_layer('a', 'summary: str\n')
        self.container.add_layer('b', {'summary': 'dict'})
        self.container.add_layer('c', ops.pebble.Layer('summary: Layer'))
        self.container.add_layer('d', 'summary: str\n', combine=True)
        self.assertEqual(self.pebble.requests, [
            ('add_layer', 'a', 'summary: str\n', False),
            ('add_layer', 'b', 'summary: dict\n', False),
            ('add_layer', 'c', 'summary: Layer\n', False),
            ('add_layer', 'd', 'summary: str\n', True),
        ])

        # combine is a keyword-only arg (should be combine=True)
        with self.assertRaises(TypeError):
            self.container.add_layer('x', {}, True)

    def test_get_plan(self):
        plan_yaml = 'services:\n foo:\n  override: replace\n  command: bar'
        self.pebble.responses.append(ops.pebble.Plan(plan_yaml))
        plan = self.container.get_plan()
        self.assertEqual(self.pebble.requests, [('get_plan',)])
        self.assertIsInstance(plan, ops.pebble.Plan)
        self.assertEqual(plan.to_yaml(), yaml.safe_dump(yaml.safe_load(plan_yaml)))

    @staticmethod
    def _make_service(name, startup, current):
        return ops.pebble.ServiceInfo.from_dict(
            {'name': name, 'startup': startup, 'current': current})

    def test_get_services(self):
        two_services = [
            self._make_service('s1', 'enabled', 'active'),
            self._make_service('s2', 'disabled', 'inactive'),
        ]
        self.pebble.responses.append(two_services)
        services = self.container.get_services()
        self.assertEqual(len(services), 2)
        self.assertEqual(set(services), {'s1', 's2'})
        self.assertEqual(services['s1'].name, 's1')
        self.assertEqual(services['s1'].startup, ops.pebble.ServiceStartup.ENABLED)
        self.assertEqual(services['s1'].current, ops.pebble.ServiceStatus.ACTIVE)
        self.assertEqual(services['s2'].name, 's2')
        self.assertEqual(services['s2'].startup, ops.pebble.ServiceStartup.DISABLED)
        self.assertEqual(services['s2'].current, ops.pebble.ServiceStatus.INACTIVE)

        self.pebble.responses.append(two_services)
        services = self.container.get_services('s1', 's2')
        self.assertEqual(len(services), 2)
        self.assertEqual(set(services), {'s1', 's2'})
        self.assertEqual(services['s1'].name, 's1')
        self.assertEqual(services['s1'].startup, ops.pebble.ServiceStartup.ENABLED)
        self.assertEqual(services['s1'].current, ops.pebble.ServiceStatus.ACTIVE)
        self.assertEqual(services['s2'].name, 's2')
        self.assertEqual(services['s2'].startup, ops.pebble.ServiceStartup.DISABLED)
        self.assertEqual(services['s2'].current, ops.pebble.ServiceStatus.INACTIVE)

        self.assertEqual(self.pebble.requests, [
            ('get_services', None),
            ('get_services', ('s1', 's2')),
        ])

    def test_get_service(self):
        # Single service returned successfully
        self.pebble.responses.append([self._make_service('s1', 'enabled', 'active')])
        s = self.container.get_service('s1')
        self.assertEqual(self.pebble.requests, [('get_services', ('s1', ))])
        self.assertEqual(s.name, 's1')
        self.assertEqual(s.startup, ops.pebble.ServiceStartup.ENABLED)
        self.assertEqual(s.current, ops.pebble.ServiceStatus.ACTIVE)

        # If Pebble returns no services, should be a ModelError
        self.pebble.responses.append([])
        with self.assertRaises(ops.model.ModelError) as cm:
            self.container.get_service('s2')
        self.assertEqual(str(cm.exception), "service 's2' not found")

        # If Pebble returns more than one service, RuntimeError is raised
        self.pebble.responses.append([
            self._make_service('s1', 'enabled', 'active'),
            self._make_service('s2', 'disabled', 'inactive'),
        ])
        with self.assertRaises(RuntimeError):
            self.container.get_service('s1')

    def test_get_checks(self):
        response_checks = [
            ops.pebble.CheckInfo.from_dict({
                'name': 'c1',
                'status': 'up',
                'failures': 0,
                'threshold': 3,
            }),
            ops.pebble.CheckInfo.from_dict({
                'name': 'c2',
                'level': 'alive',
                'status': 'down',
                'failures': 2,
                'threshold': 2,
            }),
        ]

        self.pebble.responses.append(response_checks)
        checks = self.container.get_checks()
        self.assertEqual(len(checks), 2)
        self.assertEqual(checks['c1'].name, 'c1')
        self.assertEqual(checks['c1'].level, ops.pebble.CheckLevel.UNSET)
        self.assertEqual(checks['c1'].status, ops.pebble.CheckStatus.UP)
        self.assertEqual(checks['c1'].failures, 0)
        self.assertEqual(checks['c1'].threshold, 3)
        self.assertEqual(checks['c2'].name, 'c2')
        self.assertEqual(checks['c2'].level, ops.pebble.CheckLevel.ALIVE)
        self.assertEqual(checks['c2'].status, ops.pebble.CheckStatus.DOWN)
        self.assertEqual(checks['c2'].failures, 2)
        self.assertEqual(checks['c2'].threshold, 2)

        self.pebble.responses.append(response_checks[1:2])
        checks = self.container.get_checks('c1', 'c2', level=ops.pebble.CheckLevel.ALIVE)
        self.assertEqual(len(checks), 1)
        self.assertEqual(checks['c2'].name, 'c2')
        self.assertEqual(checks['c2'].level, ops.pebble.CheckLevel.ALIVE)
        self.assertEqual(checks['c2'].status, ops.pebble.CheckStatus.DOWN)
        self.assertEqual(checks['c2'].failures, 2)
        self.assertEqual(checks['c2'].threshold, 2)

        self.assertEqual(self.pebble.requests, [
            ('get_checks', None, None),
            ('get_checks', ops.pebble.CheckLevel.ALIVE, ('c1', 'c2')),
        ])

    def test_get_check(self):
        # Single check returned successfully
        self.pebble.responses.append([
            ops.pebble.CheckInfo.from_dict({
                'name': 'c1',
                'status': 'up',
                'failures': 0,
                'threshold': 3,
            })
        ])
        c = self.container.get_check('c1')
        self.assertEqual(self.pebble.requests, [('get_checks', None, ('c1', ))])
        self.assertEqual(c.name, 'c1')
        self.assertEqual(c.level, ops.pebble.CheckLevel.UNSET)
        self.assertEqual(c.status, ops.pebble.CheckStatus.UP)
        self.assertEqual(c.failures, 0)
        self.assertEqual(c.threshold, 3)

        # If Pebble returns no checks, should be a ModelError
        self.pebble.responses.append([])
        with self.assertRaises(ops.model.ModelError) as cm:
            self.container.get_check('c2')
        self.assertEqual(str(cm.exception), "check 'c2' not found")

        # If Pebble returns more than one check, RuntimeError is raised
        self.pebble.responses.append([
            ops.pebble.CheckInfo.from_dict({
                'name': 'c1',
                'status': 'up',
                'failures': 0,
                'threshold': 3,
            }),
            ops.pebble.CheckInfo.from_dict({
                'name': 'c2',
                'level': 'alive',
                'status': 'down',
                'failures': 2,
                'threshold': 2,
            }),
        ])
        with self.assertRaises(RuntimeError):
            self.container.get_check('c1')

    def test_pull(self):
        self.pebble.responses.append('dummy1')
        got = self.container.pull('/path/1')
        self.assertEqual(got, 'dummy1')
        self.assertEqual(self.pebble.requests, [
            ('pull', '/path/1', 'utf-8'),
        ])
        self.pebble.requests = []

        self.pebble.responses.append(b'dummy2')
        got = self.container.pull('/path/2', encoding=None)
        self.assertEqual(got, b'dummy2')
        self.assertEqual(self.pebble.requests, [
            ('pull', '/path/2', None),
        ])

    def test_push(self):
        self.container.push('/path/1', 'content1')
        self.assertEqual(self.pebble.requests, [
            ('push', '/path/1', 'content1', 'utf-8', False, None,
             None, None, None, None),
        ])
        self.pebble.requests = []

        self.container.push('/path/2', b'content2', encoding=None, make_dirs=True,
                            permissions=0o600, user_id=12, user='bob', group_id=34, group='staff')
        self.assertEqual(self.pebble.requests, [
            ('push', '/path/2', b'content2', None, True, 0o600, 12, 'bob', 34, 'staff'),
        ])

    def test_list_files(self):
        self.pebble.responses.append('dummy1')
        ret = self.container.list_files('/path/1')
        self.assertEqual(ret, 'dummy1')
        self.assertEqual(self.pebble.requests, [
            ('list_files', '/path/1', None, False),
        ])
        self.pebble.requests = []

        self.pebble.responses.append('dummy2')
        ret = self.container.list_files('/path/2', pattern='*.txt', itself=True)
        self.assertEqual(ret, 'dummy2')
        self.assertEqual(self.pebble.requests, [
            ('list_files', '/path/2', '*.txt', True),
        ])

    def test_make_dir(self):
        self.container.make_dir('/path/1')
        self.assertEqual(self.pebble.requests, [
            ('make_dir', '/path/1', False, None, None, None, None, None),
        ])
        self.pebble.requests = []

        self.container.make_dir('/path/2', make_parents=True, permissions=0o700,
                                user_id=12, user='bob', group_id=34, group='staff')
        self.assertEqual(self.pebble.requests, [
            ('make_dir', '/path/2', True, 0o700, 12, 'bob', 34, 'staff'),
        ])

    def test_remove_path(self):
        self.container.remove_path('/path/1')
        self.assertEqual(self.pebble.requests, [
            ('remove_path', '/path/1', False),
        ])
        self.pebble.requests = []

        self.container.remove_path('/path/2', recursive=True)
        self.assertEqual(self.pebble.requests, [
            ('remove_path', '/path/2', True),
        ])

    def test_can_connect_simple(self):
        self.pebble.responses.append(SystemInfo.from_dict({'version': '1.0.0'}))
        self.assertTrue(self.container.can_connect())

    def test_can_connect_connection_error(self):
        def raise_error():
            raise ops.pebble.ConnectionError('connection error!')
        self.pebble.get_system_info = raise_error
        with self.assertLogs('ops.model', level='DEBUG') as cm:
            self.assertFalse(self.container.can_connect())
        self.assertEqual(len(cm.output), 1)
        self.assertRegex(cm.output[0], r'DEBUG:ops.model:.*: connection error!')

    def test_can_connect_file_not_found_error(self):
        def raise_error():
            raise FileNotFoundError('file not found!')
        self.pebble.get_system_info = raise_error
        with self.assertLogs('ops.model', level='DEBUG') as cm:
            self.assertFalse(self.container.can_connect())
        self.assertEqual(len(cm.output), 1)
        self.assertRegex(cm.output[0], r'DEBUG:ops.model:.*: file not found!')

    def test_can_connect_api_error(self):
        def raise_error():
            raise APIError('body', 404, 'status', 'api error!')
        self.pebble.get_system_info = raise_error
        with self.assertLogs('ops.model') as cm:
            self.assertFalse(self.container.can_connect())
        self.assertEqual(len(cm.output), 1)
        self.assertRegex(cm.output[0], r'WARNING:ops.model:.*: api error!')

    def test_exec(self):
        self.pebble.responses.append('fake_exec_process')
        p = self.container.exec(
            ['echo', 'foo'],
            environment={'K1': 'V1', 'K2': 'V2'},
            working_dir='WD',
            timeout=10.5,
            user_id=1000,
            user='bob',
            group_id=1000,
            group='staff',
            stdin='STDIN',
            stdout='STDOUT',
            stderr='STDERR',
            encoding=None,
            combine_stderr=True,
        )
        self.assertEqual(self.pebble.requests, [
            ('exec', ['echo', 'foo'], dict(
                environment={'K1': 'V1', 'K2': 'V2'},
                working_dir='WD',
                timeout=10.5,
                user_id=1000,
                user='bob',
                group_id=1000,
                group='staff',
                stdin='STDIN',
                stdout='STDOUT',
                stderr='STDERR',
                encoding=None,
                combine_stderr=True,
            ))
        ])
        self.assertEqual(p, 'fake_exec_process')

    def test_send_signal(self):
        with self.assertRaises(TypeError):
            self.container.send_signal('SIGHUP')

        self.container.send_signal('SIGHUP', 's1')
        self.assertEqual(self.pebble.requests, [
            ('send_signal', 'SIGHUP', ('s1',)),
        ])
        self.pebble.requests = []

        self.container.send_signal('SIGHUP', 's1', 's2')
        self.assertEqual(self.pebble.requests, [
            ('send_signal', 'SIGHUP', ('s1', 's2')),
        ])
        self.pebble.requests = []


class MockPebbleBackend(ops.model._ModelBackend):
    def get_pebble(self, socket_path):
        return MockPebbleClient(socket_path)


class MockPebbleClient:
    def __init__(self, socket_path):
        self.socket_path = socket_path
        self.requests = []
        self.responses = []

    def autostart_services(self):
        self.requests.append(('autostart',))

    def get_system_info(self):
        self.requests.append(('get_system_info',))
        return self.responses.pop(0)

    def replan_services(self):
        self.requests.append(('replan',))

    def start_services(self, service_names):
        self.requests.append(('start', service_names))

    def stop_services(self, service_names):
        self.requests.append(('stop', service_names))

    def restart_services(self, service_names):
        self.requests.append(('restart', service_names))

    def add_layer(self, label, layer, combine=False):
        if isinstance(layer, dict):
            layer = ops.pebble.Layer(layer).to_yaml()
        elif isinstance(layer, ops.pebble.Layer):
            layer = layer.to_yaml()
        self.requests.append(('add_layer', label, layer, combine))

    def get_plan(self):
        self.requests.append(('get_plan',))
        return self.responses.pop(0)

    def get_services(self, names=None):
        self.requests.append(('get_services', names))
        return self.responses.pop(0)

    def get_checks(self, level=None, names=None):
        self.requests.append(('get_checks', level, names))
        return self.responses.pop(0)

    def pull(self, path, *, encoding='utf-8'):
        self.requests.append(('pull', path, encoding))
        return self.responses.pop(0)

    def push(self, path, source, *, encoding='utf-8', make_dirs=False, permissions=None,
             user_id=None, user=None, group_id=None, group=None):
        self.requests.append(('push', path, source, encoding, make_dirs, permissions,
                              user_id, user, group_id, group))

    def list_files(self, path, *, pattern=None, itself=False):
        self.requests.append(('list_files', path, pattern, itself))
        return self.responses.pop(0)

    def make_dir(self, path, *, make_parents=False, permissions=None, user_id=None, user=None,
                 group_id=None, group=None):
        self.requests.append(('make_dir', path, make_parents, permissions, user_id, user,
                              group_id, group))

    def remove_path(self, path, *, recursive=False):
        self.requests.append(('remove_path', path, recursive))

    def exec(self, command, **kwargs):
        self.requests.append(('exec', command, kwargs))
        return self.responses.pop(0)

    def send_signal(self, signal, service_names):
        self.requests.append(('send_signal', signal, service_names))
