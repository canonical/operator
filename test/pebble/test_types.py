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
import unittest

from ops import pebble
from ops._private import yaml

from .common import datetime_nzdt, datetime_utc


class TestTypes(unittest.TestCase):
    maxDiff = None

    def test_error(self):
        error = pebble.Error('error')
        self.assertIsInstance(error, Exception)

    def test_timeout_error(self):
        error = pebble.TimeoutError('timeout!')
        self.assertIsInstance(error, pebble.Error)
        self.assertIsInstance(error, TimeoutError)
        self.assertEqual(str(error), 'timeout!')

    def test_connection_error(self):
        error = pebble.ConnectionError('connerr!')
        self.assertIsInstance(error, pebble.Error)
        self.assertEqual(str(error), 'connerr!')

    def test_protocol_error(self):
        error = pebble.ProtocolError('protoerr!')
        self.assertIsInstance(error, pebble.Error)
        self.assertEqual(str(error), 'protoerr!')

    def test_path_error(self):
        error = pebble.PathError('not-found', 'thing not found')
        self.assertIsInstance(error, pebble.Error)
        self.assertEqual(error.kind, 'not-found')
        self.assertEqual(error.message, 'thing not found')
        self.assertEqual(str(error), 'not-found - thing not found')

    def test_api_error(self):
        body = {
            "result": {
                "message": "no services to start provided"
            },
            "status": "Bad Request",
            "status-code": 400,
            "type": "error"
        }
        error = pebble.APIError(body, 400, "Bad Request", "no services")
        self.assertIsInstance(error, pebble.Error)
        self.assertEqual(error.body, body)
        self.assertEqual(error.code, 400)
        self.assertEqual(error.status, 'Bad Request')
        self.assertEqual(error.message, 'no services')
        self.assertEqual(str(error), 'no services')

    def test_change_error(self):
        change = pebble.Change(
            id=pebble.ChangeID('1234'),
            kind='start',
            summary='Start service "foo"',
            status='Done',
            tasks=[],
            ready=True,
            err='Some error',
            spawn_time=datetime.datetime.now(),
            ready_time=datetime.datetime.now(),
        )
        error = pebble.ChangeError(change.err, change)
        self.assertIsInstance(error, pebble.Error)
        self.assertEqual(error.err, 'Some error')
        self.assertEqual(error.change, change)
        self.assertEqual(str(error), 'Some error')

    def test_change_error_with_task_logs(self):
        change = pebble.Change(
            id=pebble.ChangeID('1234'),
            kind='start',
            summary='Start service "foo"',
            status='Done',
            tasks=[
                pebble.Task(
                    id=pebble.TaskID('12345'),
                    kind='start',
                    summary='Start service "foo"',
                    status='Error',
                    log=['LINE1', 'LINE2'],
                    progress=pebble.TaskProgress(label='foo', done=3, total=7),
                    spawn_time=datetime_nzdt(2021, 1, 28, 14, 37, 3, 270218),
                    ready_time=datetime_nzdt(2021, 1, 28, 14, 37, 2, 247158),
                ),
                pebble.Task(
                    id=pebble.TaskID('12346'),
                    kind='start',
                    summary='Start service "bar"',
                    status='Error',
                    log=[],
                    progress=pebble.TaskProgress(label='foo', done=3, total=7),
                    spawn_time=datetime_nzdt(2021, 1, 28, 14, 37, 3, 270218),
                    ready_time=datetime_nzdt(2021, 1, 28, 14, 37, 2, 247158),
                ),
                pebble.Task(
                    id=pebble.TaskID('12347'),
                    kind='start',
                    summary='Start service "bazz"',
                    status='Error',
                    log=['single log'],
                    progress=pebble.TaskProgress(label='foo', done=3, total=7),
                    spawn_time=datetime_nzdt(2021, 1, 28, 14, 37, 3, 270218),
                    ready_time=datetime_nzdt(2021, 1, 28, 14, 37, 2, 247158),
                ),
            ],
            ready=True,
            err='Some error',
            spawn_time=datetime.datetime.now(),
            ready_time=datetime.datetime.now(),
        )
        error = pebble.ChangeError(change.err, change)
        self.assertIsInstance(error, pebble.Error)
        self.assertEqual(error.err, 'Some error')
        self.assertEqual(error.change, change)
        self.assertEqual(str(error), """Some error
----- Logs from task 0 -----
LINE1
LINE2
----- Logs from task 2 -----
single log
-----""")

    def test_warning_state(self):
        self.assertEqual(list(pebble.WarningState), [
            pebble.WarningState.ALL,
            pebble.WarningState.PENDING,
        ])
        self.assertEqual(pebble.WarningState.ALL.value, 'all')
        self.assertEqual(pebble.WarningState.PENDING.value, 'pending')

    def test_change_state(self):
        self.assertEqual(list(pebble.ChangeState), [
            pebble.ChangeState.ALL,
            pebble.ChangeState.IN_PROGRESS,
            pebble.ChangeState.READY,
        ])
        self.assertEqual(pebble.ChangeState.ALL.value, 'all')
        self.assertEqual(pebble.ChangeState.IN_PROGRESS.value, 'in-progress')
        self.assertEqual(pebble.ChangeState.READY.value, 'ready')

    def test_system_info_init(self):
        info = pebble.SystemInfo(version='1.2.3')
        self.assertEqual(info.version, '1.2.3')

    def test_system_info_from_dict(self):
        info = pebble.SystemInfo.from_dict({'version': '3.2.1'})
        self.assertEqual(info.version, '3.2.1')

    def test_warning_init(self):
        warning = pebble.Warning(
            message='Beware!',
            first_added=datetime_utc(2021, 1, 1, 1, 1, 1),
            last_added=datetime_utc(2021, 1, 26, 2, 3, 4),
            last_shown=None,
            expire_after='1s',
            repeat_after='2s',
        )
        self.assertEqual(warning.message, 'Beware!')
        self.assertEqual(warning.first_added, datetime_utc(2021, 1, 1, 1, 1, 1))
        self.assertEqual(warning.last_added, datetime_utc(2021, 1, 26, 2, 3, 4))
        self.assertEqual(warning.last_shown, None)
        self.assertEqual(warning.expire_after, '1s')
        self.assertEqual(warning.repeat_after, '2s')

    def test_warning_from_dict(self):
        d = {
            'message': 'Look out...',
            'first-added': '2020-12-25T17:18:54.016273778+13:00',
            'last-added': '2021-01-26T17:01:02.12345+13:00',
            'expire-after': '1s',
            'repeat-after': '2s',
        }
        warning = pebble.Warning.from_dict(d)
        self.assertEqual(warning.message, 'Look out...')
        self.assertEqual(warning.first_added, datetime_nzdt(2020, 12, 25, 17, 18, 54, 16274))
        self.assertEqual(warning.last_added, datetime_nzdt(2021, 1, 26, 17, 1, 2, 123450))
        self.assertEqual(warning.last_shown, None)
        self.assertEqual(warning.expire_after, '1s')
        self.assertEqual(warning.repeat_after, '2s')

        d['last-shown'] = None
        warning = pebble.Warning.from_dict(d)
        self.assertEqual(warning.last_shown, None)

        d['last-shown'] = '2021-08-04T03:02:01.000000000+13:00'
        warning = pebble.Warning.from_dict(d)
        self.assertEqual(warning.last_shown, datetime_nzdt(2021, 8, 4, 3, 2, 1))

        d['first-added'] = '2020-02-03T02:00:40.000000+00:00'
        d['last-added'] = '2021-03-04T03:01:41.100000+00:00'
        d['last-shown'] = '2022-04-05T06:02:42.200000+00:00'
        warning = pebble.Warning.from_dict(d)
        self.assertEqual(warning.first_added, datetime_utc(2020, 2, 3, 2, 0, 40, 0))
        self.assertEqual(warning.last_added, datetime_utc(2021, 3, 4, 3, 1, 41, 100000))
        self.assertEqual(warning.last_shown, datetime_utc(2022, 4, 5, 6, 2, 42, 200000))

    def test_task_progress_init(self):
        tp = pebble.TaskProgress(label='foo', done=3, total=7)
        self.assertEqual(tp.label, 'foo')
        self.assertEqual(tp.done, 3)
        self.assertEqual(tp.total, 7)

    def test_task_progress_from_dict(self):
        tp = pebble.TaskProgress.from_dict({
            'label': 'foo',
            'done': 3,
            'total': 7,
        })
        self.assertEqual(tp.label, 'foo')
        self.assertEqual(tp.done, 3)
        self.assertEqual(tp.total, 7)

    def test_task_id(self):
        task_id = pebble.TaskID('1234')
        self.assertEqual(task_id, '1234')

    def test_task_init(self):
        task = pebble.Task(
            id=pebble.TaskID('42'),
            kind='start',
            summary='Start service "svc"',
            status='Done',
            log=[],
            progress=pebble.TaskProgress(label='foo', done=3, total=7),
            spawn_time=datetime_nzdt(2021, 1, 28, 14, 37, 3, 270218),
            ready_time=datetime_nzdt(2021, 1, 28, 14, 37, 2, 247158),
        )
        self.assertEqual(task.id, '42')
        self.assertEqual(task.kind, 'start')
        self.assertEqual(task.summary, 'Start service "svc"')
        self.assertEqual(task.status, 'Done')
        self.assertEqual(task.log, [])
        self.assertEqual(task.progress.label, 'foo')
        self.assertEqual(task.progress.done, 3)
        self.assertEqual(task.progress.total, 7)
        self.assertEqual(task.spawn_time, datetime_nzdt(2021, 1, 28, 14, 37, 3, 270218))
        self.assertEqual(task.ready_time, datetime_nzdt(2021, 1, 28, 14, 37, 2, 247158))
        self.assertEqual(task.data, {})

    def test_task_from_dict(self):
        d = {
            "id": "78",
            "kind": "start",
            "progress": {
                "done": 1,
                "label": "",
                "total": 1,
            },
            "ready-time": "2021-01-28T14:37:03.270218778+13:00",
            "spawn-time": "2021-01-28T14:37:02.247158162+13:00",
            "status": "Done",
            "summary": 'Start service "svc"',
            "data": {"exit-code": 42},
        }
        task = pebble.Task.from_dict(d)
        self.assertEqual(task.id, '78')
        self.assertEqual(task.kind, 'start')
        self.assertEqual(task.summary, 'Start service "svc"')
        self.assertEqual(task.status, 'Done')
        self.assertEqual(task.log, [])
        self.assertEqual(task.progress.label, '')
        self.assertEqual(task.progress.done, 1)
        self.assertEqual(task.progress.total, 1)
        self.assertEqual(task.ready_time, datetime_nzdt(2021, 1, 28, 14, 37, 3, 270219))
        self.assertEqual(task.spawn_time, datetime_nzdt(2021, 1, 28, 14, 37, 2, 247158))
        self.assertEqual(task.data, {'exit-code': 42})

        d['ready-time'] = '2021-01-28T14:37:03.270218778+00:00'
        d['spawn-time'] = '2021-01-28T14:37:02.247158162+00:00'
        task = pebble.Task.from_dict(d)
        self.assertEqual(task.ready_time, datetime_utc(2021, 1, 28, 14, 37, 3, 270219))
        self.assertEqual(task.spawn_time, datetime_utc(2021, 1, 28, 14, 37, 2, 247158))

    def test_change_id(self):
        change_id = pebble.ChangeID('1234')
        self.assertEqual(change_id, '1234')

    def test_change_init(self):
        change = pebble.Change(
            id=pebble.ChangeID('70'),
            kind='autostart',
            err='SILLY',
            ready=True,
            ready_time=datetime_nzdt(2021, 1, 28, 14, 37, 4, 291517),
            spawn_time=datetime_nzdt(2021, 1, 28, 14, 37, 2, 247202),
            status='Done',
            summary='Autostart service "svc"',
            tasks=[],
        )
        self.assertEqual(change.id, '70')
        self.assertEqual(change.kind, 'autostart')
        self.assertEqual(change.err, 'SILLY')
        self.assertEqual(change.ready, True)
        self.assertEqual(change.ready_time, datetime_nzdt(2021, 1, 28, 14, 37, 4, 291517))
        self.assertEqual(change.spawn_time, datetime_nzdt(2021, 1, 28, 14, 37, 2, 247202))
        self.assertEqual(change.status, 'Done')
        self.assertEqual(change.summary, 'Autostart service "svc"')
        self.assertEqual(change.tasks, [])
        self.assertEqual(change.data, {})

    def test_change_from_dict(self):
        d = {
            "id": "70",
            "kind": "autostart",
            "err": "SILLY",
            "ready": True,
            "ready-time": "2021-01-28T14:37:04.291517768+13:00",
            "spawn-time": "2021-01-28T14:37:02.247202105+13:00",
            "status": "Done",
            "summary": 'Autostart service "svc"',
            "tasks": [],
            "data": {"exit-code": 42},
        }
        change = pebble.Change.from_dict(d)
        self.assertEqual(change.id, '70')
        self.assertEqual(change.kind, 'autostart')
        self.assertEqual(change.err, 'SILLY')
        self.assertEqual(change.ready, True)
        self.assertEqual(change.ready_time, datetime_nzdt(2021, 1, 28, 14, 37, 4, 291518))
        self.assertEqual(change.spawn_time, datetime_nzdt(2021, 1, 28, 14, 37, 2, 247202))
        self.assertEqual(change.status, 'Done')
        self.assertEqual(change.summary, 'Autostart service "svc"')
        self.assertEqual(change.tasks, [])
        self.assertEqual(change.data, {'exit-code': 42})

        d['ready-time'] = '2021-01-28T14:37:04.291517768+00:00'
        d['spawn-time'] = '2021-01-28T14:37:02.247202105+00:00'
        change = pebble.Change.from_dict(d)
        self.assertEqual(change.ready_time, datetime_utc(2021, 1, 28, 14, 37, 4, 291518))
        self.assertEqual(change.spawn_time, datetime_utc(2021, 1, 28, 14, 37, 2, 247202))

    def test_file_type(self):
        self.assertEqual(list(pebble.FileType), [
            pebble.FileType.FILE,
            pebble.FileType.DIRECTORY,
            pebble.FileType.SYMLINK,
            pebble.FileType.SOCKET,
            pebble.FileType.NAMED_PIPE,
            pebble.FileType.DEVICE,
            pebble.FileType.UNKNOWN,
        ])
        self.assertEqual(pebble.FileType.FILE.value, 'file')
        self.assertEqual(pebble.FileType.DIRECTORY.value, 'directory')
        self.assertEqual(pebble.FileType.SYMLINK.value, 'symlink')
        self.assertEqual(pebble.FileType.SOCKET.value, 'socket')
        self.assertEqual(pebble.FileType.NAMED_PIPE.value, 'named-pipe')
        self.assertEqual(pebble.FileType.DEVICE.value, 'device')
        self.assertEqual(pebble.FileType.UNKNOWN.value, 'unknown')

    def test_file_info_init(self):
        info = pebble.FileInfo('/etc/hosts', 'hosts', pebble.FileType.FILE, 123, 0o644,
                               datetime_nzdt(2021, 1, 28, 14, 37, 4, 291518),
                               12, 'bob', 34, 'staff')
        self.assertEqual(info.path, '/etc/hosts')
        self.assertEqual(info.name, 'hosts')
        self.assertEqual(info.type, pebble.FileType.FILE)
        self.assertEqual(info.size, 123)
        self.assertEqual(info.permissions, 0o644)
        self.assertEqual(info.last_modified, datetime_nzdt(2021, 1, 28, 14, 37, 4, 291518))
        self.assertEqual(info.user_id, 12)
        self.assertEqual(info.user, 'bob')
        self.assertEqual(info.group_id, 34)
        self.assertEqual(info.group, 'staff')

    def test_file_info_from_dict(self):
        d = {
            'path': '/etc',
            'name': 'etc',
            'type': 'directory',
            'permissions': '644',
            'last-modified': '2021-01-28T14:37:04.291517768+13:00',
        }
        info = pebble.FileInfo.from_dict(d)
        self.assertEqual(info.path, '/etc')
        self.assertEqual(info.name, 'etc')
        self.assertEqual(info.type, pebble.FileType.DIRECTORY)
        self.assertEqual(info.permissions, 0o644)
        self.assertEqual(info.last_modified, datetime_nzdt(2021, 1, 28, 14, 37, 4, 291518))
        self.assertIs(info.user_id, None)
        self.assertIs(info.user, None)
        self.assertIs(info.group_id, None)
        self.assertIs(info.group, None)

        d['type'] = 'foobar'
        d['size'] = 123
        d['user-id'] = 12
        d['user'] = 'bob'
        d['group-id'] = 34
        d['group'] = 'staff'
        info = pebble.FileInfo.from_dict(d)
        self.assertEqual(info.type, 'foobar')
        self.assertEqual(info.size, 123)
        self.assertEqual(info.user_id, 12)
        self.assertEqual(info.user, 'bob')
        self.assertEqual(info.group_id, 34)
        self.assertEqual(info.group, 'staff')


class TestPlan(unittest.TestCase):
    def test_no_args(self):
        with self.assertRaises(TypeError):
            pebble.Plan()

    def test_services(self):
        plan = pebble.Plan('')
        self.assertEqual(plan.services, {})

        plan = pebble.Plan('services:\n foo:\n  override: replace\n  command: echo foo')

        self.assertEqual(len(plan.services), 1)
        self.assertEqual(plan.services['foo'].name, 'foo')
        self.assertEqual(plan.services['foo'].override, 'replace')
        self.assertEqual(plan.services['foo'].command, 'echo foo')

        # Should be read-only ("can't set attribute")
        with self.assertRaises(AttributeError):
            plan.services = {}

    def test_checks(self):
        plan = pebble.Plan('')
        self.assertEqual(plan.checks, {})

        plan = pebble.Plan(
            'checks:\n bar:\n  override: replace\n  http:\n   url: https://example.com/')

        self.assertEqual(len(plan.checks), 1)
        self.assertEqual(plan.checks['bar'].name, 'bar')
        self.assertEqual(plan.checks['bar'].override, 'replace')
        self.assertEqual(plan.checks['bar'].http, {'url': 'https://example.com/'})

        # Should be read-only ("can't set attribute")
        with self.assertRaises(AttributeError):
            plan.checks = {}

    def test_yaml(self):
        # Starting with nothing, we get the empty result
        plan = pebble.Plan('')
        self.assertEqual(plan.to_yaml(), '{}\n')
        self.assertEqual(str(plan), '{}\n')

        # With a service, we return validated yaml content.
        raw = '''\
services:
 foo:
  override: replace
  command: echo foo

checks:
 bar:
  http:
   https://example.com/
'''
        plan = pebble.Plan(raw)
        reformed = yaml.safe_dump(yaml.safe_load(raw))
        self.assertEqual(plan.to_yaml(), reformed)
        self.assertEqual(str(plan), reformed)

    def test_service_equality(self):
        plan = pebble.Plan('services:\n foo:\n  override: replace\n  command: echo foo')

        old_service = pebble.Service(name="foo",
                                     raw={
                                         "override": "replace",
                                         "command": "echo foo"
                                     })
        old_services = {"foo": old_service}
        self.assertEqual(plan.services, old_services)

        services_as_dict = {
            "foo": {"override": "replace", "command": "echo foo"}
        }
        self.assertEqual(plan.services, services_as_dict)


class TestLayer(unittest.TestCase):
    def _assert_empty(self, layer):
        self.assertEqual(layer.summary, '')
        self.assertEqual(layer.description, '')
        self.assertEqual(layer.services, {})
        self.assertEqual(layer.to_dict(), {})

    def test_no_args(self):
        s = pebble.Layer()
        self._assert_empty(s)

    def test_dict(self):
        s = pebble.Layer({})
        self._assert_empty(s)

        d = {
            'summary': 'Sum Mary',
            'description': 'The quick brown fox!',
            'services': {
                'foo': {
                    'summary': 'Foo',
                    'command': 'echo foo',
                },
                'bar': {
                    'summary': 'Bar',
                    'command': 'echo bar',
                },
            }
        }
        s = pebble.Layer(d)
        self.assertEqual(s.summary, 'Sum Mary')
        self.assertEqual(s.description, 'The quick brown fox!')
        self.assertEqual(s.services['foo'].name, 'foo')
        self.assertEqual(s.services['foo'].summary, 'Foo')
        self.assertEqual(s.services['foo'].command, 'echo foo')
        self.assertEqual(s.services['bar'].name, 'bar')
        self.assertEqual(s.services['bar'].summary, 'Bar')
        self.assertEqual(s.services['bar'].command, 'echo bar')

        self.assertEqual(s.to_dict(), d)

    def test_yaml(self):
        s = pebble.Layer('')
        self._assert_empty(s)

        yaml = """checks:
  chk:
    http:
      url: https://example.com/
description: The quick brown fox!
services:
  bar:
    command: echo bar
    environment:
      ENV1: value1
      ENV2: value2
    group: staff
    group-id: 2000
    summary: Bar
    user: bob
    user-id: 1000
  foo:
    command: echo foo
    summary: Foo
summary: Sum Mary
"""
        s = pebble.Layer(yaml)
        self.assertEqual(s.summary, 'Sum Mary')
        self.assertEqual(s.description, 'The quick brown fox!')
        self.assertEqual(s.services['foo'].name, 'foo')
        self.assertEqual(s.services['foo'].summary, 'Foo')
        self.assertEqual(s.services['foo'].command, 'echo foo')
        self.assertEqual(s.services['bar'].name, 'bar')
        self.assertEqual(s.services['bar'].summary, 'Bar')
        self.assertEqual(s.services['bar'].command, 'echo bar')
        self.assertEqual(s.services['bar'].environment,
                         {'ENV1': 'value1', 'ENV2': 'value2'})
        self.assertEqual(s.services['bar'].user, 'bob')
        self.assertEqual(s.services['bar'].user_id, 1000)
        self.assertEqual(s.services['bar'].group, 'staff')
        self.assertEqual(s.services['bar'].group_id, 2000)

        self.assertEqual(s.checks['chk'].name, 'chk')
        self.assertEqual(s.checks['chk'].http, {'url': 'https://example.com/'})

        self.assertEqual(s.to_yaml(), yaml)
        self.assertEqual(str(s), yaml)

    def test_layer_service_equality(self):
        s = pebble.Layer({})
        self._assert_empty(s)

        d = {
            'summary': 'Sum Mary',
            'description': 'The quick brown fox!',
            'services': {
                'foo': {
                    'summary': 'Foo',
                    'command': 'echo foo',
                },
                'bar': {
                    'summary': 'Bar',
                    'command': 'echo bar',
                },
            }
        }
        s = pebble.Layer(d)
        t = pebble.Layer(d)

        self.assertEqual(s.services, t.services)


class TestService(unittest.TestCase):
    def _assert_empty(self, service, name):
        self.assertEqual(service.name, name)
        self.assertEqual(service.summary, '')
        self.assertEqual(service.description, '')
        self.assertEqual(service.startup, '')
        self.assertEqual(service.override, '')
        self.assertEqual(service.command, '')
        self.assertEqual(service.after, [])
        self.assertEqual(service.before, [])
        self.assertEqual(service.requires, [])
        self.assertEqual(service.environment, {})
        self.assertEqual(service.user, '')
        self.assertIs(service.user_id, None)
        self.assertEqual(service.group, '')
        self.assertIs(service.group_id, None)
        self.assertEqual(service.on_success, '')
        self.assertEqual(service.on_failure, '')
        self.assertEqual(service.on_check_failure, {})
        self.assertEqual(service.backoff_delay, '')
        self.assertIs(service.backoff_factor, None)
        self.assertEqual(service.backoff_limit, '')
        self.assertEqual(service.to_dict(), {})

    def test_name_only(self):
        s = pebble.Service('Name 0')
        self._assert_empty(s, 'Name 0')

    def test_dict(self):
        s = pebble.Service('Name 1', {})
        self._assert_empty(s, 'Name 1')

        d = {
            'summary': 'Sum Mary',
            'description': 'The lazy quick brown',
            'startup': 'Start Up',
            'override': 'override',
            'command': 'echo sum mary',
            'after': ['a1', 'a2'],
            'before': ['b1', 'b2'],
            'requires': ['r1', 'r2'],
            'environment': {'k1': 'v1', 'k2': 'v2'},
            'user': 'bob',
            'user-id': 1000,
            'group': 'staff',
            'group-id': 2000,
            'on-success': 'restart',
            'on-failure': 'ignore',
            'on-check-failure': {'chk1': 'halt'},
            'backoff-delay': '1s',
            'backoff-factor': 4,
            'backoff-limit': '10s',
        }
        s = pebble.Service('Name 2', d)
        self.assertEqual(s.name, 'Name 2')
        self.assertEqual(s.description, 'The lazy quick brown')
        self.assertEqual(s.startup, 'Start Up')
        self.assertEqual(s.override, 'override')
        self.assertEqual(s.command, 'echo sum mary')
        self.assertEqual(s.after, ['a1', 'a2'])
        self.assertEqual(s.before, ['b1', 'b2'])
        self.assertEqual(s.requires, ['r1', 'r2'])
        self.assertEqual(s.environment, {'k1': 'v1', 'k2': 'v2'})
        self.assertEqual(s.user, 'bob')
        self.assertEqual(s.user_id, 1000)
        self.assertEqual(s.group, 'staff')
        self.assertEqual(s.group_id, 2000)
        self.assertEqual(s.on_success, 'restart')
        self.assertEqual(s.on_failure, 'ignore')
        self.assertEqual(s.on_check_failure, {'chk1': 'halt'})
        self.assertEqual(s.backoff_delay, '1s')
        self.assertEqual(s.backoff_factor, 4)
        self.assertEqual(s.backoff_limit, '10s')

        self.assertEqual(s.to_dict(), d)

        # Ensure pebble.Service has made copies of mutable objects
        s.after.append('a3')
        s.before.append('b3')
        s.requires.append('r3')
        s.environment['k3'] = 'v3'
        s.on_check_failure['chk2'] = 'ignore'
        self.assertEqual(s.after, ['a1', 'a2', 'a3'])
        self.assertEqual(s.before, ['b1', 'b2', 'b3'])
        self.assertEqual(s.requires, ['r1', 'r2', 'r3'])
        self.assertEqual(s.environment, {'k1': 'v1', 'k2': 'v2', 'k3': 'v3'})
        self.assertEqual(d['after'], ['a1', 'a2'])
        self.assertEqual(d['before'], ['b1', 'b2'])
        self.assertEqual(d['requires'], ['r1', 'r2'])
        self.assertEqual(d['environment'], {'k1': 'v1', 'k2': 'v2'})
        self.assertEqual(d['on-check-failure'], {'chk1': 'halt'})

    def test_equality(self):
        d = {
            'summary': 'Sum Mary',
            'description': 'The lazy quick brown',
            'startup': 'Start Up',
            'override': 'override',
            'command': 'echo sum mary',
            'after': ['a1', 'a2'],
            'before': ['b1', 'b2'],
            'requires': ['r1', 'r2'],
            'environment': {'k1': 'v1', 'k2': 'v2'},
            'user': 'bob',
            'user-id': 1000,
            'group': 'staff',
            'group-id': 2000,
        }
        one = pebble.Service("Name 1", d)
        two = pebble.Service("Name 1", d)
        self.assertEqual(one, two)

        as_dict = {
            'summary': 'Sum Mary',
            'description': 'The lazy quick brown',
            'startup': 'Start Up',
            'override': 'override',
            'command': 'echo sum mary',
            'after': ['a1', 'a2'],
            'before': ['b1', 'b2'],
            'requires': ['r1', 'r2'],
            'environment': {'k1': 'v1', 'k2': 'v2'},
            'user': 'bob',
            'user-id': 1000,
            'group': 'staff',
            'group-id': 2000,
        }
        self.assertEqual(one, as_dict)

        with self.assertRaises(ValueError):
            self.assertEqual(one, 5)


class TestCheck(unittest.TestCase):
    def _assert_empty(self, check, name):
        self.assertEqual(check.name, name)
        self.assertEqual(check.override, '')
        self.assertEqual(check.level, pebble.CheckLevel.UNSET)
        self.assertEqual(check.period, '')
        self.assertEqual(check.timeout, '')
        self.assertIs(check.threshold, None)
        self.assertIs(check.http, None)
        self.assertIs(check.tcp, None)
        self.assertIs(check.exec, None)

    def test_name_only(self):
        check = pebble.Check('chk')
        self._assert_empty(check, 'chk')

    def test_dict(self):
        d = {
            'override': 'replace',
            'level': 'alive',
            'period': '10s',
            'timeout': '3s',
            'threshold': 5,
            # Not valid for Pebble to have more than one of http, tcp, and exec,
            # but it makes things simpler for the unit tests.
            'http': {'url': 'https://example.com/'},
            'tcp': {'port': 80},
            'exec': {'command': 'echo foo'},
        }
        check = pebble.Check('chk-http', d)
        self.assertEqual(check.name, 'chk-http')
        self.assertEqual(check.override, 'replace')
        self.assertEqual(check.level, pebble.CheckLevel.ALIVE)
        self.assertEqual(check.period, '10s')
        self.assertEqual(check.timeout, '3s')
        self.assertEqual(check.threshold, 5)
        self.assertEqual(check.http, {'url': 'https://example.com/'})
        self.assertEqual(check.tcp, {'port': 80})
        self.assertEqual(check.exec, {'command': 'echo foo'})

        self.assertEqual(check.to_dict(), d)

        # Ensure pebble.Check has made copies of mutable objects
        check.http['url'] = 'https://www.google.com'
        self.assertEqual(d['http'], {'url': 'https://example.com/'})
        check.tcp['port'] = 81
        self.assertEqual(d['tcp'], {'port': 80})
        check.exec['command'] = 'foo'
        self.assertEqual(d['exec'], {'command': 'echo foo'})

    def test_level_raw(self):
        d = {
            'override': 'replace',
            'level': 'foobar!',
            'period': '10s',
            'timeout': '3s',
            'threshold': 5,
            'http': {'url': 'https://example.com/'},
        }
        check = pebble.Check('chk-http', d)
        self.assertEqual(check.level, 'foobar!')  # remains a string

    def test_equality(self):
        d = {
            'override': 'replace',
            'level': 'alive',
            'period': '10s',
            'timeout': '3s',
            'threshold': 5,
            'http': {'url': 'https://example.com/'},
        }
        one = pebble.Check('one', d)
        two = pebble.Check('two', d)
        self.assertEqual(one, two)
        self.assertEqual(one, d)
        self.assertEqual(two, d)
        self.assertEqual(one, one.to_dict())
        self.assertEqual(two, two.to_dict())
        d['level'] = 'ready'
        self.assertNotEqual(one, d)

        with self.assertRaises(ValueError):
            self.assertEqual(one, 5)


class TestServiceInfo(unittest.TestCase):
    def test_service_startup(self):
        self.assertEqual(list(pebble.ServiceStartup), [
            pebble.ServiceStartup.ENABLED,
            pebble.ServiceStartup.DISABLED,
        ])
        self.assertEqual(pebble.ServiceStartup.ENABLED.value, 'enabled')
        self.assertEqual(pebble.ServiceStartup.DISABLED.value, 'disabled')

    def test_service_status(self):
        self.assertEqual(list(pebble.ServiceStatus), [
            pebble.ServiceStatus.ACTIVE,
            pebble.ServiceStatus.INACTIVE,
            pebble.ServiceStatus.ERROR,
        ])
        self.assertEqual(pebble.ServiceStatus.ACTIVE.value, 'active')
        self.assertEqual(pebble.ServiceStatus.INACTIVE.value, 'inactive')
        self.assertEqual(pebble.ServiceStatus.ERROR.value, 'error')

    def test_service_info(self):
        s = pebble.ServiceInfo('svc1', pebble.ServiceStartup.ENABLED, pebble.ServiceStatus.ACTIVE)
        self.assertEqual(s.name, 'svc1')
        self.assertEqual(s.startup, pebble.ServiceStartup.ENABLED)
        self.assertEqual(s.current, pebble.ServiceStatus.ACTIVE)

        s = pebble.ServiceInfo(
            'svc1',
            pebble.ServiceStartup.ENABLED,
            pebble.ServiceStatus.ACTIVE)
        self.assertEqual(s.name, 'svc1')
        self.assertEqual(s.startup, pebble.ServiceStartup.ENABLED)
        self.assertEqual(s.current, pebble.ServiceStatus.ACTIVE)

        s = pebble.ServiceInfo.from_dict({
            'name': 'svc2',
            'startup': 'disabled',
            'current': 'inactive',
        })
        self.assertEqual(s.name, 'svc2')
        self.assertEqual(s.startup, pebble.ServiceStartup.DISABLED)
        self.assertEqual(s.current, pebble.ServiceStatus.INACTIVE)

        s = pebble.ServiceInfo.from_dict({
            'name': 'svc2',
            'startup': 'thingy',
            'current': 'bob',
        })
        self.assertEqual(s.name, 'svc2')
        self.assertEqual(s.startup, 'thingy')
        self.assertEqual(s.current, 'bob')

    def test_is_running(self):
        s = pebble.ServiceInfo('s', pebble.ServiceStartup.ENABLED, pebble.ServiceStatus.ACTIVE)
        self.assertTrue(s.is_running())
        for current in [pebble.ServiceStatus.INACTIVE, pebble.ServiceStatus.ERROR, 'other']:
            s = pebble.ServiceInfo('s', pebble.ServiceStartup.ENABLED, current)
            self.assertFalse(s.is_running())


class TestCheckInfo(unittest.TestCase):
    def test_check_level(self):
        self.assertEqual(list(pebble.CheckLevel), [
            pebble.CheckLevel.UNSET,
            pebble.CheckLevel.ALIVE,
            pebble.CheckLevel.READY,
        ])
        self.assertEqual(pebble.CheckLevel.UNSET.value, '')
        self.assertEqual(pebble.CheckLevel.ALIVE.value, 'alive')
        self.assertEqual(pebble.CheckLevel.READY.value, 'ready')

    def test_check_status(self):
        self.assertEqual(list(pebble.CheckStatus), [
            pebble.CheckStatus.UP,
            pebble.CheckStatus.DOWN,
        ])
        self.assertEqual(pebble.CheckStatus.UP.value, 'up')
        self.assertEqual(pebble.CheckStatus.DOWN.value, 'down')

    def test_check_info(self):
        check = pebble.CheckInfo(
            name='chk1',
            level=pebble.CheckLevel.READY,
            status=pebble.CheckStatus.UP,
            threshold=3,
        )
        self.assertEqual(check.name, 'chk1')
        self.assertEqual(check.level, pebble.CheckLevel.READY)
        self.assertEqual(check.status, pebble.CheckStatus.UP)
        self.assertEqual(check.failures, 0)
        self.assertEqual(check.threshold, 3)

        check = pebble.CheckInfo(
            name='chk2',
            level=pebble.CheckLevel.ALIVE,
            status=pebble.CheckStatus.DOWN,
            failures=5,
            threshold=3,
        )
        self.assertEqual(check.name, 'chk2')
        self.assertEqual(check.level, pebble.CheckLevel.ALIVE)
        self.assertEqual(check.status, pebble.CheckStatus.DOWN)
        self.assertEqual(check.failures, 5)
        self.assertEqual(check.threshold, 3)

        check = pebble.CheckInfo.from_dict({
            'name': 'chk3',
            'status': 'up',
            'threshold': 3,
        })
        self.assertEqual(check.name, 'chk3')
        self.assertEqual(check.level, pebble.CheckLevel.UNSET)
        self.assertEqual(check.status, pebble.CheckStatus.UP)
        self.assertEqual(check.failures, 0)
        self.assertEqual(check.threshold, 3)

        check = pebble.CheckInfo.from_dict({
            'name': 'chk4',
            'level': pebble.CheckLevel.UNSET,
            'status': pebble.CheckStatus.DOWN,
            'failures': 3,
            'threshold': 3,
        })
        self.assertEqual(check.name, 'chk4')
        self.assertEqual(check.level, pebble.CheckLevel.UNSET)
        self.assertEqual(check.status, pebble.CheckStatus.DOWN)
        self.assertEqual(check.failures, 3)
        self.assertEqual(check.threshold, 3)
