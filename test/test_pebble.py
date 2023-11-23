# Copyright 2021 Canonical Ltd.
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
import email.message
import email.parser
import io
import json
import signal
import tempfile
import test.fake_pebble as fake_pebble
import typing
import unittest
import unittest.mock
import unittest.util

import pytest
import websocket  # type: ignore

from ops import pebble
from ops._private import yaml

# Ensure unittest diffs don't get truncated like "[17 chars]"
unittest.util._MAX_LENGTH = 1000


def datetime_utc(y: int, m: int, d: int, hour: int, min: int, sec: int, micro: int = 0):
    tz = datetime.timezone.utc
    return datetime.datetime(y, m, d, hour, min, sec, micro, tzinfo=tz)


def datetime_nzdt(y: int, m: int, d: int, hour: int, min: int, sec: int, micro: int = 0):
    tz = datetime.timezone(datetime.timedelta(hours=13))
    return datetime.datetime(y, m, d, hour, min, sec, micro, tzinfo=tz)


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
        assert change.err is not None
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
        assert change.err is not None
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
        d: pebble._WarningDict = {
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
        d: pebble._TaskDict = {
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
        d: 'pebble._ChangeDict' = {
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
        d: pebble._FileInfoDict = {
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
            pebble.Plan()  # type: ignore

    def test_services(self):
        plan = pebble.Plan('')
        self.assertEqual(plan.services, {})

        plan = pebble.Plan("""
services:
  foo:
    override: replace
    command: echo foo
""")

        self.assertEqual(len(plan.services), 1)
        self.assertEqual(plan.services['foo'].name, 'foo')
        self.assertEqual(plan.services['foo'].override, 'replace')
        self.assertEqual(plan.services['foo'].command, 'echo foo')

        # Should be read-only ("can't set attribute")
        with self.assertRaises(AttributeError):
            plan.services = {}  # type: ignore

    def test_checks(self):
        plan = pebble.Plan('')
        self.assertEqual(plan.checks, {})

        plan = pebble.Plan("""
checks:
  bar:
    override: replace
    http:
      url: https://example.com/
""")

        self.assertEqual(len(plan.checks), 1)
        self.assertEqual(plan.checks['bar'].name, 'bar')
        self.assertEqual(plan.checks['bar'].override, 'replace')
        self.assertEqual(plan.checks['bar'].http, {'url': 'https://example.com/'})

        # Should be read-only ("can't set attribute")
        with self.assertRaises(AttributeError):
            plan.checks = {}  # type: ignore

    def test_log_targets(self):
        plan = pebble.Plan('')
        self.assertEqual(plan.log_targets, {})

        location = "https://example.com:3100/loki/api/v1/push"
        plan = pebble.Plan(f"""
log-targets:
  baz:
    override: replace
    type: loki
    location: {location}
""")

        self.assertEqual(len(plan.log_targets), 1)
        self.assertEqual(plan.log_targets['baz'].name, 'baz')
        self.assertEqual(plan.log_targets['baz'].override, 'replace')
        self.assertEqual(plan.log_targets['baz'].type, "loki")
        self.assertEqual(plan.log_targets['baz'].location, location)

        # Should be read-only ("can't set attribute")
        with self.assertRaises(AttributeError):
            plan.log_targets = {}  # type: ignore

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

log-targets:
 baz:
  override: replace
  type: loki
  location: https://example.com:3100/loki/api/v1/push
'''
        plan = pebble.Plan(raw)
        reformed = yaml.safe_dump(yaml.safe_load(raw))
        self.assertEqual(plan.to_yaml(), reformed)
        self.assertEqual(str(plan), reformed)

    def test_service_equality(self):
        plan = pebble.Plan("""
services:
  foo:
    override: replace
    command: echo foo
""")

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
    def _assert_empty(self, layer: pebble.Layer):
        self.assertEqual(layer.summary, '')
        self.assertEqual(layer.description, '')
        self.assertEqual(layer.services, {})
        self.assertEqual(layer.checks, {})
        self.assertEqual(layer.log_targets, {})
        self.assertEqual(layer.to_dict(), {})

    def test_no_args(self):
        s = pebble.Layer()
        self._assert_empty(s)

    def test_dict(self):
        s = pebble.Layer({})
        self._assert_empty(s)

        d: pebble.LayerDict = {
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
            },
            'log-targets': {
                'baz': {
                    'override': 'merge',
                    'type': 'loki',
                    'location': 'https://example.com',
                    'services': ['foo'],
                    'labels': {
                        'key': 'value $VAR',
                    }
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
        self.assertEqual(s.log_targets['baz'].name, 'baz')
        self.assertEqual(s.log_targets['baz'].override, 'merge')
        self.assertEqual(s.log_targets['baz'].type, 'loki')
        self.assertEqual(s.log_targets['baz'].location, 'https://example.com')
        self.assertEqual(s.log_targets['baz'].services, ['foo'])
        self.assertEqual(s.log_targets['baz'].labels, {'key': 'value $VAR'})

        self.assertEqual(s.to_dict(), d)

    def test_yaml(self):
        s = pebble.Layer('')
        self._assert_empty(s)

        yaml = """checks:
  chk:
    http:
      url: https://example.com/
description: The quick brown fox!
log-targets:
  baz:
    location: https://example.com:3100
    override: replace
    type: loki
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

        self.assertEqual(s.log_targets['baz'].name, 'baz')
        self.assertEqual(s.log_targets['baz'].override, 'replace')
        self.assertEqual(s.log_targets['baz'].location, 'https://example.com:3100')

        self.assertEqual(s.to_yaml(), yaml)
        self.assertEqual(str(s), yaml)

    def test_layer_service_equality(self):
        s = pebble.Layer({})
        self._assert_empty(s)

        d: pebble.LayerDict = {
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

    def test_layer_equality(self):
        s = pebble.Layer({})
        self._assert_empty(s)

        d: pebble.LayerDict = {
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
        t = pebble.Layer(d)
        self.assertNotEqual(s, t)
        self.assertNotEqual(t, {})
        self.assertEqual(t, d)

        s = pebble.Layer(d)
        self.assertEqual(s, t)
        self.assertNotEqual(s, {})
        self.assertEqual(s, d)

        self.assertNotEqual(s, 5)


class TestService(unittest.TestCase):
    def _assert_empty(self, service: pebble.Service, name: str):
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
        self.assertEqual(service.working_dir, '')
        self.assertEqual(service.on_success, '')
        self.assertEqual(service.on_failure, '')
        self.assertEqual(service.on_check_failure, {})
        self.assertEqual(service.backoff_delay, '')
        self.assertIs(service.backoff_factor, None)
        self.assertEqual(service.backoff_limit, '')
        self.assertIs(service.kill_delay, '')
        self.assertEqual(service.to_dict(), {})

    def test_name_only(self):
        s = pebble.Service('Name 0')
        self._assert_empty(s, 'Name 0')

    def test_dict(self):
        s = pebble.Service('Name 1', {})
        self._assert_empty(s, 'Name 1')

        d: pebble.ServiceDict = {
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
            'working-dir': '/working/dir',
            'on-success': 'restart',
            'on-failure': 'ignore',
            'on-check-failure': {'chk1': 'halt'},
            'backoff-delay': '1s',
            'backoff-factor': 4,
            'backoff-limit': '10s',
            'kill-delay': '420s',
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
        self.assertEqual(s.working_dir, '/working/dir')
        self.assertEqual(s.on_success, 'restart')
        self.assertEqual(s.on_failure, 'ignore')
        self.assertEqual(s.on_check_failure, {'chk1': 'halt'})
        self.assertEqual(s.backoff_delay, '1s')
        self.assertEqual(s.backoff_factor, 4)
        self.assertEqual(s.backoff_limit, '10s')
        self.assertEqual(s.kill_delay, '420s')

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
        d: pebble.ServiceDict = {
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

        self.assertNotEqual(one, 5)


class TestCheck(unittest.TestCase):
    def _assert_empty(self, check: pebble.Check, name: str):
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
        d: pebble.CheckDict = {
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
        assert check.http is not None and check.tcp is not None and check.exec is not None
        check.http['url'] = 'https://www.google.com'
        self.assertEqual(d['http'], {'url': 'https://example.com/'})
        check.tcp['port'] = 81
        self.assertEqual(d['tcp'], {'port': 80})
        check.exec['command'] = 'foo'
        self.assertEqual(d['exec'], {'command': 'echo foo'})

    def test_level_raw(self):
        d: pebble.CheckDict = {
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
        d: pebble.CheckDict = {
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

        self.assertNotEqual(one, 5)


class TestLogTarget(unittest.TestCase):
    def _assert_empty(self, target: pebble.LogTarget, name: str):
        self.assertEqual(target.name, name)
        self.assertEqual(target.override, '')
        self.assertEqual(target.type, '')
        self.assertEqual(target.location, '')
        self.assertEqual(target.services, [])
        self.assertIs(target.labels, None)

    def test_name_only(self):
        target = pebble.LogTarget('tgt')
        self._assert_empty(target, 'tgt')

    def test_dict(self):
        d: pebble.LogTargetDict = {
            'override': 'replace',
            'type': 'loki',
            'location': 'https://example.com:3100/loki/api/v1/push',
            'services': ['+all'],
            'labels': {'key': 'val', 'key2': 'val2'}
        }
        target = pebble.LogTarget('tgt', d)
        self.assertEqual(target.name, 'tgt')
        self.assertEqual(target.override, 'replace')
        self.assertEqual(target.type, 'loki')
        self.assertEqual(target.location, 'https://example.com:3100/loki/api/v1/push')
        self.assertEqual(target.services, ['+all'])
        self.assertEqual(target.labels, {'key': 'val', 'key2': 'val2'})

        self.assertEqual(target.to_dict(), d)

        # Ensure pebble.Target has made copies of mutable objects.
        assert target.services is not None and target.labels is not None
        target.services[0] = '-all'
        self.assertEqual(d['services'], ['+all'])
        target.labels['key'] = 'val3'
        assert d['labels'] is not None
        self.assertEqual(d['labels']['key'], 'val')

    def test_equality(self):
        d: pebble.LogTargetDict = {
            'override': 'replace',
            'type': 'loki',
            'location': 'https://example.com',
            'services': ['foo', 'bar'],
            'labels': {'k': 'v'}
        }
        one = pebble.LogTarget('one', d)
        two = pebble.LogTarget('two', d)
        self.assertEqual(one, two)
        self.assertEqual(one, d)
        self.assertEqual(two, d)
        self.assertEqual(one, one.to_dict())
        self.assertEqual(two, two.to_dict())
        d['override'] = 'merge'
        self.assertNotEqual(one, d)
        self.assertNotEqual(one, 5)


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

        d: pebble._CheckInfoDict = {
            'name': 'chk3',
            'status': 'up',
            'threshold': 3,
        }
        check = pebble.CheckInfo.from_dict(d)
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


_bytes_generator = typing.Generator[bytes, typing.Any, typing.Any]


class MockClient(pebble.Client):
    """Mock Pebble client that simply records requests and returns stored responses."""

    def __init__(self):
        self.requests: typing.List[typing.Any] = []
        self.responses: typing.List[typing.Any] = []
        self.timeout = 5
        self.websockets: typing.Dict[typing.Any, MockWebsocket] = {}

    def _request(self,
                 method: str,
                 path: str,
                 query: typing.Optional[typing.Dict[str, typing.Any]] = None,
                 body: typing.Optional[typing.Dict[str, typing.Any]] = None
                 ) -> typing.Dict[str, typing.Any]:
        self.requests.append((method, path, query, body))
        resp = self.responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        if callable(resp):
            resp = resp()
        return resp

    def _request_raw(self,
                     method: str,
                     path: str,
                     query: typing.Optional[typing.Dict[str, typing.Any]] = None,
                     headers: typing.Optional[typing.Dict[str, str]] = None,
                     data: typing.Optional[typing.Union[bytes, _bytes_generator]] = None):
        self.requests.append((method, path, query, headers, data))
        headers, body = self.responses.pop(0)
        assert headers is not None
        return MockHTTPResponse(headers, body)

    def _connect_websocket(self, task_id: str, websocket_id: str):
        return self.websockets[task_id, websocket_id]


class MockHTTPResponse:
    def __init__(self, headers: typing.Dict[str, str], body: bytes):
        message = email.message.Message()
        for key, value in (headers or {}).items():
            message[key] = value
        self.headers = message
        reader = io.BytesIO(body)
        self.read = reader.read


class MockTime:
    """Mocked versions of time.time() and time.sleep().

    MockTime.sleep() advances the clock and MockTime.time() returns the current time.
    """

    def __init__(self):
        self._time = 0

    def time(self):
        return self._time

    def sleep(self, delay: float):
        self._time += delay


def build_mock_change_dict(change_id: str = '70') -> 'pebble._ChangeDict':
    return {
        "id": change_id,
        "kind": "autostart",
        "ready": True,
        "ready-time": "2021-01-28T14:37:04.291517768+13:00",
        "spawn-time": "2021-01-28T14:37:02.247202105+13:00",
        "status": "Done",
        "summary": 'Autostart service "svc"',
        "tasks": [
            {
                "id": "78",
                "kind": "start",
                "progress": {
                    "done": 1,
                    "label": "",
                    "total": 1,
                    "extra-field": "foo",  # type: ignore
                },
                "ready-time": "2021-01-28T14:37:03.270218778+13:00",
                "spawn-time": "2021-01-28T14:37:02.247158162+13:00",
                "status": "Done",
                "summary": 'Start service "svc"',
                "extra-field": "foo",
            },
        ],
        "extra-field": "foo",
    }


class TestMultipartParser(unittest.TestCase):
    class _Case:
        def __init__(
                self,
                name: str,
                data: bytes,
                want_headers: typing.List[bytes],
                want_bodies: typing.List[bytes],
                want_bodies_done: typing.List[bool],
                max_boundary: int = 14,
                max_lookahead: int = 8 * 1024,
                error: str = ''):
            self.name = name
            self.data = data
            self.want_headers = want_headers
            self.want_bodies = want_bodies
            self.want_bodies_done = want_bodies_done
            self.max_boundary = max_boundary
            self.max_lookahead = max_lookahead
            self.error = error

    def test_multipart_parser(self):
        tests = [
            TestMultipartParser._Case(
                'baseline',
                b'\r\n--qwerty\r\nheader foo\r\n\r\nfoo bar\nfoo bar\r\n--qwerty--\r\n',
                [b'header foo\r\n\r\n'],
                [b'foo bar\nfoo bar'],
                want_bodies_done=[True],
            ),
            TestMultipartParser._Case(
                'incomplete header',
                b'\r\n--qwerty\r\nheader foo\r\n',
                [],
                [],
                want_bodies_done=[],
            ),
            TestMultipartParser._Case(
                'missing header',
                b'\r\n--qwerty\r\nheader foo\r\n' + 40 * b' ',
                [],
                [],
                want_bodies_done=[],
                max_lookahead=40,
                error='header terminator not found',
            ),
            TestMultipartParser._Case(
                'incomplete body terminator',
                b'\r\n--qwerty\r\nheader foo\r\n\r\nfoo bar\r\n--qwerty\rhello my name is joe and I work in a button factory',  # noqa
                [b'header foo\r\n\r\n'],
                [b'foo bar\r\n--qwerty\rhello my name is joe and I work in a '],
                want_bodies_done=[False],
            ),
            TestMultipartParser._Case(
                'empty body',
                b'\r\n--qwerty\r\nheader foo\r\n\r\n\r\n--qwerty\r\n',
                [b'header foo\r\n\r\n'],
                [b''],
                want_bodies_done=[True],
            ),
            TestMultipartParser._Case(
                'ignore leading garbage',
                b'hello my name is joe\r\n\n\n\n\r\n--qwerty\r\nheader foo\r\n\r\nfoo bar\r\n--qwerty\r\n',  # noqa
                [b'header foo\r\n\r\n'],
                [b'foo bar'],
                want_bodies_done=[True],
            ),
            TestMultipartParser._Case(
                'ignore trailing garbage',
                b'\r\n--qwerty\r\nheader foo\r\n\r\nfoo bar\r\n--qwerty\r\nhello my name is joe',
                [b'header foo\r\n\r\n'],
                [b'foo bar'],
                want_bodies_done=[True],
            ),
            TestMultipartParser._Case(
                'boundary allow linear whitespace',
                b'\r\n--qwerty \t \r\nheader foo\r\n\r\nfoo bar\r\n--qwerty\r\n',
                [b'header foo\r\n\r\n'],
                [b'foo bar'],
                want_bodies_done=[True],
                max_boundary=20,
            ),
            TestMultipartParser._Case(
                'terminal boundary allow linear whitespace',
                b'\r\n--qwerty\r\nheader foo\r\n\r\nfoo bar\r\n--qwerty-- \t \r\n',
                [b'header foo\r\n\r\n'],
                [b'foo bar'],
                want_bodies_done=[True],
                max_boundary=20,
            ),
            TestMultipartParser._Case(
                'multiple parts',
                b'\r\n--qwerty \t \r\nheader foo\r\n\r\nfoo bar\r\n--qwerty\r\nheader bar\r\n\r\nfoo baz\r\n--qwerty--\r\n',  # noqa
                [b'header foo\r\n\r\n', b'header bar\r\n\r\n'],
                [b'foo bar', b'foo baz'],
                want_bodies_done=[True, True],
            ),
            TestMultipartParser._Case(
                'ignore after terminal boundary',
                b'\r\n--qwerty \t \r\nheader foo\r\n\r\nfoo bar\r\n--qwerty--\r\nheader bar\r\n\r\nfoo baz\r\n--qwerty--\r\n',  # noqa
                [b'header foo\r\n\r\n'],
                [b'foo bar'],
                want_bodies_done=[True],
            ),
        ]

        chunk_sizes = [1, 2, 3, 4, 5, 7, 13, 17, 19, 23, 29, 31, 37, 42, 50, 100, 1000]
        marker = b'qwerty'
        for i, test in enumerate(tests):
            for chunk_size in chunk_sizes:
                headers: typing.List[bytes] = []
                bodies: typing.List[bytes] = []
                bodies_done: typing.List[bool] = []

                def handle_header(data: typing.Any):
                    headers.append(bytes(data))
                    bodies.append(b'')
                    bodies_done.append(False)

                def handle_body(data: bytes, done: bool = False):
                    bodies[-1] += data
                    bodies_done[-1] = done

                parser = pebble._MultipartParser(
                    marker,
                    handle_header,
                    handle_body,
                    max_boundary_length=test.max_boundary,
                    max_lookahead=test.max_lookahead)
                src = io.BytesIO(test.data)

                try:
                    while True:
                        data = src.read(chunk_size)
                        if not data:
                            break
                        parser.feed(data)
                except Exception as err:
                    if not test.error:
                        self.fail(f'unexpected error: {err}')
                        break
                    self.assertEqual(test.error, str(err))
                else:
                    if test.error:
                        self.fail(f'missing expected error: {test.error!r}')

                    msg = f'test case {i + 1} ({test.name}), chunk size {chunk_size}'
                    self.assertEqual(test.want_headers, headers, msg)
                    self.assertEqual(test.want_bodies, bodies, msg)
                    self.assertEqual(test.want_bodies_done, bodies_done, msg)


class TestClient(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.client = MockClient()
        self.time = MockTime()
        time_patcher = unittest.mock.patch('ops.pebble.time', self.time)
        time_patcher.start()
        self.addCleanup(time_patcher.stop)

    def test_client_init(self):
        pebble.Client(socket_path='foo')  # test that constructor runs
        with self.assertRaises(TypeError):
            pebble.Client()  # type: ignore (socket_path arg required)

    def test_get_system_info(self):
        self.client.responses.append({
            "result": {
                "version": "1.2.3",
                "extra-field": "foo",
            },
            "status": "OK",
            "status-code": 200,
            "type": "sync"
        })
        info = self.client.get_system_info()
        self.assertEqual(info.version, '1.2.3')
        self.assertEqual(self.client.requests, [
            ('GET', '/v1/system-info', None, None),
        ])

    def test_get_warnings(self):
        empty: typing.Dict[str, typing.Any] = {
            "result": [],
            "status": "OK",
            "status-code": 200,
            "type": "sync"
        }
        self.client.responses.append(empty)
        warnings = self.client.get_warnings()
        self.assertEqual(warnings, [])

        self.client.responses.append(empty)
        warnings = self.client.get_warnings(select=pebble.WarningState.ALL)
        self.assertEqual(warnings, [])

        self.assertEqual(self.client.requests, [
            ('GET', '/v1/warnings', {'select': 'pending'}, None),
            ('GET', '/v1/warnings', {'select': 'all'}, None),
        ])

    def test_ack_warnings(self):
        self.client.responses.append({
            "result": 0,
            "status": "OK",
            "status-code": 200,
            "type": "sync"
        })
        num = self.client.ack_warnings(datetime_nzdt(2021, 1, 28, 15, 11, 0))
        self.assertEqual(num, 0)
        self.assertEqual(self.client.requests, [
            ('POST', '/v1/warnings', None, {
                'action': 'okay',
                'timestamp': '2021-01-28T15:11:00+13:00',
            }),
        ])

    def assert_mock_change(self, change: pebble.Change):
        self.assertEqual(change.id, '70')
        self.assertEqual(change.kind, 'autostart')
        self.assertEqual(change.summary, 'Autostart service "svc"')
        self.assertEqual(change.status, 'Done')
        self.assertEqual(len(change.tasks), 1)
        self.assertEqual(change.tasks[0].id, '78')
        self.assertEqual(change.tasks[0].kind, 'start')
        self.assertEqual(change.tasks[0].summary, 'Start service "svc"')
        self.assertEqual(change.tasks[0].status, 'Done')
        self.assertEqual(change.tasks[0].log, [])
        self.assertEqual(change.tasks[0].progress.done, 1)
        self.assertEqual(change.tasks[0].progress.label, '')
        self.assertEqual(change.tasks[0].progress.total, 1)
        self.assertEqual(change.tasks[0].ready_time,
                         datetime_nzdt(2021, 1, 28, 14, 37, 3, 270219))
        self.assertEqual(change.tasks[0].spawn_time,
                         datetime_nzdt(2021, 1, 28, 14, 37, 2, 247158))
        self.assertEqual(change.ready, True)
        self.assertEqual(change.err, None)
        self.assertEqual(change.ready_time, datetime_nzdt(2021, 1, 28, 14, 37, 4, 291518))
        self.assertEqual(change.spawn_time, datetime_nzdt(2021, 1, 28, 14, 37, 2, 247202))

    def test_get_changes(self):
        empty: typing.Dict[str, typing.Any] = {
            "result": [],
            "status": "OK",
            "status-code": 200,
            "type": "sync"
        }
        self.client.responses.append(empty)
        changes = self.client.get_changes()
        self.assertEqual(changes, [])

        self.client.responses.append(empty)
        changes = self.client.get_changes(select=pebble.ChangeState.ALL)
        self.assertEqual(changes, [])

        self.client.responses.append(empty)
        changes = self.client.get_changes(select=pebble.ChangeState.ALL, service='foo')
        self.assertEqual(changes, [])

        self.client.responses.append({
            "result": [
                build_mock_change_dict(),
            ],
            "status": "OK",
            "status-code": 200,
            "type": "sync"
        })
        changes = self.client.get_changes()
        self.assertEqual(len(changes), 1)
        self.assert_mock_change(changes[0])

        self.assertEqual(self.client.requests, [
            ('GET', '/v1/changes', {'select': 'in-progress'}, None),
            ('GET', '/v1/changes', {'select': 'all'}, None),
            ('GET', '/v1/changes', {'select': 'all', 'for': 'foo'}, None),
            ('GET', '/v1/changes', {'select': 'in-progress'}, None),
        ])

    def test_get_change(self):
        self.client.responses.append({
            "result": build_mock_change_dict(),
            "status": "OK",
            "status-code": 200,
            "type": "sync"
        })
        change = self.client.get_change(pebble.ChangeID('70'))
        self.assert_mock_change(change)
        self.assertEqual(self.client.requests, [
            ('GET', '/v1/changes/70', None, None),
        ])

    def test_get_change_str(self):
        self.client.responses.append({
            "result": build_mock_change_dict(),
            "status": "OK",
            "status-code": 200,
            "type": "sync"
        })
        change = self.client.get_change('70')  # type: ignore
        self.assert_mock_change(change)
        self.assertEqual(self.client.requests, [
            ('GET', '/v1/changes/70', None, None),
        ])

    def test_abort_change(self):
        self.client.responses.append({
            "result": build_mock_change_dict(),
            "status": "OK",
            "status-code": 200,
            "type": "sync"
        })
        change = self.client.abort_change(pebble.ChangeID('70'))
        self.assert_mock_change(change)
        self.assertEqual(self.client.requests, [
            ('POST', '/v1/changes/70', None, {'action': 'abort'}),
        ])

    def _services_action_helper(
            self,
            action: str,
            api_func: typing.Callable[[], str],
            services: typing.List[str]):
        self.client.responses.append({
            "change": "70",
            "result": None,
            "status": "Accepted",
            "status-code": 202,
            "type": "async"
        })
        change = build_mock_change_dict()
        change['ready'] = True
        self.client.responses.append({
            "result": change,
            "status": "OK",
            "status-code": 200,
            "type": "sync"
        })
        change_id = api_func()
        self.assertEqual(change_id, '70')
        self.assertEqual(self.client.requests, [
            ('POST', '/v1/services', None, {'action': action, 'services': services}),
            ('GET', '/v1/changes/70/wait', {'timeout': '4.000s'}, None),
        ])

    def _services_action_async_helper(
            self, action: str, api_func: typing.Callable[..., str], services: typing.List[str]):
        self.client.responses.append({
            "change": "70",
            "result": None,
            "status": "Accepted",
            "status-code": 202,
            "type": "async"
        })
        change_id = api_func(timeout=0)
        self.assertEqual(change_id, '70')
        self.assertEqual(self.client.requests, [
            ('POST', '/v1/services', None, {'action': action, 'services': services}),
        ])

    def test_autostart_services(self):
        self._services_action_helper('autostart', self.client.autostart_services, [])

    def test_autostart_services_async(self):
        self._services_action_async_helper('autostart', self.client.autostart_services, [])

    def test_replan_services(self):
        self._services_action_helper('replan', self.client.replan_services, [])

    def test_replan_services_async(self):
        self._services_action_async_helper('replan', self.client.replan_services, [])

    def test_start_services(self):
        def api_func():
            return self.client.start_services(['svc'])
        self._services_action_helper('start', api_func, ['svc'])

        with self.assertRaises(TypeError):
            self.client.start_services(1)  # type: ignore

        with self.assertRaises(TypeError):
            self.client.start_services([1])  # type: ignore

        with self.assertRaises(TypeError):
            self.client.start_services([['foo']])  # type: ignore

    def test_start_services_async(self):
        def api_func(timeout: float = 30):
            return self.client.start_services(['svc'], timeout=timeout)
        self._services_action_async_helper('start', api_func, ['svc'])

    def test_stop_services(self):
        def api_func():
            return self.client.stop_services(['svc'])
        self._services_action_helper('stop', api_func, ['svc'])

        with self.assertRaises(TypeError):
            self.client.stop_services(1)  # type: ignore

        with self.assertRaises(TypeError):
            self.client.stop_services([1])  # type: ignore

        with self.assertRaises(TypeError):
            self.client.stop_services([['foo']])  # type: ignore

    def test_stop_services_async(self):
        def api_func(timeout: float = 30):
            return self.client.stop_services(['svc'], timeout=timeout)
        self._services_action_async_helper('stop', api_func, ['svc'])

    def test_restart_services(self):
        def api_func():
            return self.client.restart_services(['svc'])
        self._services_action_helper('restart', api_func, ['svc'])

        with self.assertRaises(TypeError):
            self.client.restart_services(1)  # type: ignore

        with self.assertRaises(TypeError):
            self.client.restart_services([1])  # type: ignore

        with self.assertRaises(TypeError):
            self.client.restart_services([['foo']])  # type: ignore

    def test_restart_services_async(self):
        def api_func(timeout: float = 30):
            return self.client.restart_services(['svc'], timeout=timeout)
        self._services_action_async_helper('restart', api_func, ['svc'])

    def test_change_error(self):
        self.client.responses.append({
            "change": "70",
            "result": None,
            "status": "Accepted",
            "status-code": 202,
            "type": "async"
        })
        change = build_mock_change_dict()
        change['err'] = 'Some kind of service error'
        self.client.responses.append({
            "result": change,
            "status": "OK",
            "status-code": 200,
            "type": "sync"
        })
        with self.assertRaises(pebble.ChangeError) as cm:
            self.client.autostart_services()
        self.assertIsInstance(cm.exception, pebble.Error)
        self.assertEqual(cm.exception.err, 'Some kind of service error')
        self.assertIsInstance(cm.exception.change, pebble.Change)
        self.assertEqual(cm.exception.change.id, '70')

        self.assertEqual(self.client.requests, [
            ('POST', '/v1/services', None, {'action': 'autostart', 'services': []}),
            ('GET', '/v1/changes/70/wait', {'timeout': '4.000s'}, None),
        ])

    def test_wait_change_success(self, timeout: typing.Optional[float] = 30.0):
        change = build_mock_change_dict()
        self.client.responses.append({
            "result": change,
            "status": "OK",
            "status-code": 200,
            "type": "sync"
        })

        response = self.client.wait_change(pebble.ChangeID('70'), timeout=timeout)
        self.assertEqual(response.id, '70')
        self.assertTrue(response.ready)

        self.assertEqual(self.client.requests, [
            ('GET', '/v1/changes/70/wait', {'timeout': '4.000s'}, None),
        ])

    def test_wait_change_success_timeout_none(self):
        self.test_wait_change_success(timeout=None)

    def test_wait_change_success_multiple_calls(self):
        def timeout_response(n: float):
            self.time.sleep(n)  # simulate passing of time due to wait_change call
            raise pebble.APIError({}, 504, "Gateway Timeout", "timed out")

        self.client.responses.append(lambda: timeout_response(4))

        change = build_mock_change_dict()
        self.client.responses.append({
            "result": change,
            "status": "OK",
            "status-code": 200,
            "type": "sync"
        })

        response = self.client.wait_change(pebble.ChangeID('70'))
        self.assertEqual(response.id, '70')
        self.assertTrue(response.ready)

        self.assertEqual(self.client.requests, [
            ('GET', '/v1/changes/70/wait', {'timeout': '4.000s'}, None),
            ('GET', '/v1/changes/70/wait', {'timeout': '4.000s'}, None),
        ])

        self.assertEqual(self.time.time(), 4)

    def test_wait_change_success_polled(self, timeout: typing.Optional[float] = 30.0):
        # Trigger polled mode
        self.client.responses.append(pebble.APIError({}, 404, "Not Found", "not found"))

        for i in range(3):
            change = build_mock_change_dict()
            change['ready'] = i == 2
            self.client.responses.append({
                "result": change,
                "status": "OK",
                "status-code": 200,
                "type": "sync"
            })

        response = self.client.wait_change(pebble.ChangeID('70'), timeout=timeout, delay=1)
        self.assertEqual(response.id, '70')
        self.assertTrue(response.ready)

        self.assertEqual(self.client.requests, [
            ('GET', '/v1/changes/70/wait', {'timeout': '4.000s'}, None),
            ('GET', '/v1/changes/70', None, None),
            ('GET', '/v1/changes/70', None, None),
            ('GET', '/v1/changes/70', None, None),
        ])

        self.assertEqual(self.time.time(), 2)

    def test_wait_change_success_polled_timeout_none(self):
        self.test_wait_change_success_polled(timeout=None)

    def test_wait_change_timeout(self):
        def timeout_response(n: float):
            self.time.sleep(n)  # simulate passing of time due to wait_change call
            raise pebble.APIError({}, 504, "Gateway Timeout", "timed out")

        self.client.responses.append(lambda: timeout_response(4))
        self.client.responses.append(lambda: timeout_response(2))

        with self.assertRaises(pebble.TimeoutError) as cm:
            self.client.wait_change(pebble.ChangeID('70'), timeout=6)
        self.assertIsInstance(cm.exception, pebble.Error)
        self.assertIsInstance(cm.exception, TimeoutError)

        self.assertEqual(self.client.requests, [
            ('GET', '/v1/changes/70/wait', {'timeout': '4.000s'}, None),
            ('GET', '/v1/changes/70/wait', {'timeout': '2.000s'}, None),
        ])

        self.assertEqual(self.time.time(), 6)

    def test_wait_change_timeout_polled(self):
        # Trigger polled mode
        self.client.responses.append(pebble.APIError({}, 404, "Not Found", "not found"))

        change = build_mock_change_dict()
        change['ready'] = False
        for _ in range(3):
            self.client.responses.append({
                "result": change,
                "status": "OK",
                "status-code": 200,
                "type": "sync"
            })

        with self.assertRaises(pebble.TimeoutError) as cm:
            self.client.wait_change(pebble.ChangeID('70'), timeout=3, delay=1)
        self.assertIsInstance(cm.exception, pebble.Error)
        self.assertIsInstance(cm.exception, TimeoutError)

        self.assertEqual(self.client.requests, [
            ('GET', '/v1/changes/70/wait', {'timeout': '3.000s'}, None),
            ('GET', '/v1/changes/70', None, None),
            ('GET', '/v1/changes/70', None, None),
            ('GET', '/v1/changes/70', None, None),
        ])

        self.assertEqual(self.time.time(), 3)

    def test_wait_change_error(self):
        change = build_mock_change_dict()
        change['err'] = 'Some kind of service error'
        self.client.responses.append({
            "result": change,
            "status": "OK",
            "status-code": 200,
            "type": "sync"
        })
        # wait_change() itself shouldn't raise an error
        response = self.client.wait_change(pebble.ChangeID('70'))
        self.assertEqual(response.id, '70')
        self.assertEqual(response.err, 'Some kind of service error')

        self.assertEqual(self.client.requests, [
            ('GET', '/v1/changes/70/wait', {'timeout': '4.000s'}, None),
        ])

    def test_add_layer(self):
        okay_response = {
            "result": True,
            "status": "OK",
            "status-code": 200,
            "type": "sync"
        }
        self.client.responses.append(okay_response)
        self.client.responses.append(okay_response)
        self.client.responses.append(okay_response)
        self.client.responses.append(okay_response)

        layer_yaml = """
services:
  foo:
    command: echo bar
    override: replace
"""[1:]
        layer = pebble.Layer(layer_yaml)

        self.client.add_layer('a', layer)
        self.client.add_layer('b', layer.to_yaml())
        self.client.add_layer('c', layer.to_dict())
        self.client.add_layer('d', layer, combine=True)

        def build_expected(label: str, combine: bool):
            return {
                'action': 'add',
                'combine': combine,
                'label': label,
                'format': 'yaml',
                'layer': layer_yaml,
            }

        self.assertEqual(self.client.requests, [
            ('POST', '/v1/layers', None, build_expected('a', False)),
            ('POST', '/v1/layers', None, build_expected('b', False)),
            ('POST', '/v1/layers', None, build_expected('c', False)),
            ('POST', '/v1/layers', None, build_expected('d', True)),
        ])

    def test_add_layer_invalid_type(self):
        with self.assertRaises(TypeError):
            self.client.add_layer('foo', 42)  # type: ignore
        with self.assertRaises(TypeError):
            self.client.add_layer(42, 'foo')  # type: ignore

        # combine is a keyword-only arg (should be combine=True)
        with self.assertRaises(TypeError):
            self.client.add_layer('foo', {}, True)  # type: ignore

    def test_get_plan(self):
        plan_yaml = """
services:
  foo:
    command: echo bar
    override: replace
"""[1:]
        self.client.responses.append({
            "result": plan_yaml,
            "status": "OK",
            "status-code": 200,
            "type": "sync"
        })
        plan = self.client.get_plan()
        self.assertEqual(plan.to_yaml(), plan_yaml)
        self.assertEqual(len(plan.services), 1)
        self.assertEqual(plan.services['foo'].command, 'echo bar')
        self.assertEqual(plan.services['foo'].override, 'replace')

        self.assertEqual(self.client.requests, [
            ('GET', '/v1/plan', {'format': 'yaml'}, None),
        ])

    def test_get_services_all(self):
        self.client.responses.append({
            "result": [
                {
                    "current": "inactive",
                    "name": "svc1",
                    "startup": "disabled"
                },
                {
                    "current": "active",
                    "name": "svc2",
                    "startup": "enabled"
                }
            ],
            "status": "OK",
            "status-code": 200,
            "type": "sync"
        })
        services = self.client.get_services()
        self.assertEqual(len(services), 2)
        self.assertEqual(services[0].name, 'svc1')
        self.assertEqual(services[0].startup, pebble.ServiceStartup.DISABLED)
        self.assertEqual(services[0].current, pebble.ServiceStatus.INACTIVE)
        self.assertEqual(services[1].name, 'svc2')
        self.assertEqual(services[1].startup, pebble.ServiceStartup.ENABLED)
        self.assertEqual(services[1].current, pebble.ServiceStatus.ACTIVE)

        self.assertEqual(self.client.requests, [
            ('GET', '/v1/services', None, None),
        ])

    def test_get_services_names(self):
        self.client.responses.append({
            "result": [
                {
                    "current": "inactive",
                    "name": "svc1",
                    "startup": "disabled"
                },
                {
                    "current": "active",
                    "name": "svc2",
                    "startup": "enabled"
                }
            ],
            "status": "OK",
            "status-code": 200,
            "type": "sync"
        })
        services = self.client.get_services(['svc1', 'svc2'])
        self.assertEqual(len(services), 2)
        self.assertEqual(services[0].name, 'svc1')
        self.assertEqual(services[0].startup, pebble.ServiceStartup.DISABLED)
        self.assertEqual(services[0].current, pebble.ServiceStatus.INACTIVE)
        self.assertEqual(services[1].name, 'svc2')
        self.assertEqual(services[1].startup, pebble.ServiceStartup.ENABLED)
        self.assertEqual(services[1].current, pebble.ServiceStatus.ACTIVE)

        self.client.responses.append({
            "result": [
                {
                    "current": "active",
                    "name": "svc2",
                    "startup": "enabled"
                }
            ],
            "status": "OK",
            "status-code": 200,
            "type": "sync"
        })
        services = self.client.get_services(['svc2'])
        self.assertEqual(len(services), 1)
        self.assertEqual(services[0].name, 'svc2')
        self.assertEqual(services[0].startup, pebble.ServiceStartup.ENABLED)
        self.assertEqual(services[0].current, pebble.ServiceStatus.ACTIVE)

        self.assertEqual(self.client.requests, [
            ('GET', '/v1/services', {'names': 'svc1,svc2'}, None),
            ('GET', '/v1/services', {'names': 'svc2'}, None),
        ])

    def test_pull_boundary_spanning_chunk(self):
        self.client.responses.append((
            {'Content-Type': 'multipart/form-data; boundary=01234567890123456789012345678901'},
            b"""\
--01234567890123456789012345678901\r
Content-Disposition: form-data; name="files"; filename="/etc/hosts"\r
\r
127.0.0.1 localhost  # \xf0\x9f\x98\x80\nfoo\r\nbar\r
--01234567890123456789012345678901\r
Content-Disposition: form-data; name="response"\r
\r
{
    "result": [{"path": "/etc/hosts"}],
    "status": "OK",
    "status-code": 200,
    "type": "sync"
}\r
--01234567890123456789012345678901--\r
""",
        ))

        self.client._chunk_size = 13
        with self.client.pull('/etc/hosts') as infile:
            content = infile.read()
        self.assertEqual(content, '127.0.0.1 localhost  # 😀\nfoo\r\nbar')

        self.assertEqual(self.client.requests, [
            ('GET', '/v1/files', {'action': 'read', 'path': '/etc/hosts'},
                {'Accept': 'multipart/form-data'}, None),
        ])

    def test_pull_text(self):
        self.client.responses.append((
            {'Content-Type': 'multipart/form-data; boundary=01234567890123456789012345678901'},
            b"""\
--01234567890123456789012345678901\r
Content-Disposition: form-data; name="files"; filename="/etc/hosts"\r
\r
127.0.0.1 localhost  # \xf0\x9f\x98\x80\nfoo\r\nbar\r
--01234567890123456789012345678901\r
Content-Disposition: form-data; name="response"\r
\r
{
    "result": [{"path": "/etc/hosts"}],
    "status": "OK",
    "status-code": 200,
    "type": "sync"
}\r
--01234567890123456789012345678901--\r
""",
        ))

        with self.client.pull('/etc/hosts') as infile:
            content = infile.read()
        self.assertEqual(content, '127.0.0.1 localhost  # 😀\nfoo\r\nbar')

        self.assertEqual(self.client.requests, [
            ('GET', '/v1/files', {'action': 'read', 'path': '/etc/hosts'},
                {'Accept': 'multipart/form-data'}, None),
        ])

    def test_pull_binary(self):
        self.client.responses.append((
            {'Content-Type': 'multipart/form-data; boundary=01234567890123456789012345678901'},
            b"""\
--01234567890123456789012345678901\r
Content-Disposition: form-data; name="files"; filename="/etc/hosts"\r
\r
127.0.0.1 localhost  # \xf0\x9f\x98\x80\nfoo\r\nbar\r
--01234567890123456789012345678901\r
Content-Disposition: form-data; name="response"\r
\r
{
    "result": [{"path": "/etc/hosts"}],
    "status": "OK",
    "status-code": 200,
    "type": "sync"
}\r
--01234567890123456789012345678901--\r
""",
        ))

        with self.client.pull('/etc/hosts', encoding=None) as infile:
            content = infile.read()
        self.assertEqual(content, b'127.0.0.1 localhost  # \xf0\x9f\x98\x80\nfoo\r\nbar')

        self.assertEqual(self.client.requests, [
            ('GET', '/v1/files', {'action': 'read', 'path': '/etc/hosts'},
                {'Accept': 'multipart/form-data'}, None),
        ])

    def test_pull_path_error(self):
        self.client.responses.append((
            {'Content-Type': 'multipart/form-data; boundary=01234567890123456789012345678901'},
            b"""\
--01234567890123456789012345678901\r
Content-Disposition: form-data; name="response"\r
\r
{
    "result": [
        {"path": "/etc/hosts", "error": {"kind": "not-found", "message": "not found"}}
    ],
    "status": "OK",
    "status-code": 200,
    "type": "sync"
}\r
--01234567890123456789012345678901--\r
""",
        ))

        with self.assertRaises(pebble.PathError) as cm:
            self.client.pull('/etc/hosts')
        self.assertIsInstance(cm.exception, pebble.Error)
        self.assertEqual(cm.exception.kind, 'not-found')
        self.assertEqual(cm.exception.message, 'not found')

        self.assertEqual(self.client.requests, [
            ('GET', '/v1/files', {'action': 'read', 'path': '/etc/hosts'},
                {'Accept': 'multipart/form-data'}, None),
        ])

    def test_pull_protocol_errors(self):
        self.client.responses.append(({'Content-Type': 'c/t'}, b''))
        with self.assertRaises(pebble.ProtocolError) as cm:
            self.client.pull('/etc/hosts')
        self.assertIsInstance(cm.exception, pebble.Error)
        self.assertEqual(str(cm.exception),
                         "expected Content-Type 'multipart/form-data', got 'c/t'")

        self.client.responses.append(({'Content-Type': 'multipart/form-data'}, b''))
        with self.assertRaises(pebble.ProtocolError) as cm:
            self.client.pull('/etc/hosts')
        self.assertEqual(str(cm.exception), "invalid boundary ''")

        self.client.responses.append((
            {'Content-Type': 'multipart/form-data; boundary=01234567890123456789012345678901'},
            b"""\
--01234567890123456789012345678901\r
Content-Disposition: form-data; name="files"; filename="/bad"\r
\r
bad path\r
--01234567890123456789012345678901\r
Content-Disposition: form-data; name="response"\r
\r
{
    "result": [{"path": "/etc/hosts"}],
    "status": "OK",
    "status-code": 200,
    "type": "sync"
}\r
--01234567890123456789012345678901--\r
""",
        ))
        with self.assertRaises(pebble.ProtocolError) as cm:
            self.client.pull('/etc/hosts')
        self.assertEqual(str(cm.exception), "path not expected: '/bad'")

        self.client.responses.append((
            {'Content-Type': 'multipart/form-data; boundary=01234567890123456789012345678901'},
            b"""\
--01234567890123456789012345678901\r
Content-Disposition: form-data; name="files"; filename="/etc/hosts"\r
\r
bad path\r
--01234567890123456789012345678901--\r
""",
        ))
        with self.assertRaises(pebble.ProtocolError) as cm:
            self.client.pull('/etc/hosts')
        self.assertEqual(str(cm.exception), 'no "response" field in multipart body')

    def test_push_str(self):
        self._test_push_str('content 😀\nfoo\r\nbar')

    def test_push_text(self):
        self._test_push_str(io.StringIO('content 😀\nfoo\r\nbar'))

    def _test_push_str(self, source: typing.Union[str, typing.IO[str]]):
        self.client.responses.append((
            {'Content-Type': 'application/json'},
            b"""
{
    "result": [
        {"path": "/foo/bar"}
    ],
    "status": "OK",
    "status-code": 200,
    "type": "sync"
}
""",
        ))

        self.client.push('/foo/bar', source)

        self.assertEqual(len(self.client.requests), 1)
        request = self.client.requests[0]
        self.assertEqual(request[:3], ('POST', '/v1/files', None))

        headers, body = request[3:]

        content_type = headers['Content-Type']
        req, filename, content = self._parse_write_multipart(content_type, body)
        self.assertEqual(filename, '/foo/bar')
        self.assertEqual(content, b'content \xf0\x9f\x98\x80\nfoo\r\nbar')
        self.assertEqual(req, {
            'action': 'write',
            'files': [{'path': '/foo/bar'}],
        })

    def test_push_bytes(self):
        self._test_push_bytes(b'content \xf0\x9f\x98\x80\nfoo\r\nbar')

    def test_push_binary(self):
        self._test_push_bytes(io.BytesIO(b'content \xf0\x9f\x98\x80\nfoo\r\nbar'))

    def _test_push_bytes(self, source: typing.Union[bytes, typing.IO[bytes]]):
        self.client.responses.append((
            {'Content-Type': 'application/json'},
            b"""
{
    "result": [
        {"path": "/foo/bar"}
    ],
    "status": "OK",
    "status-code": 200,
    "type": "sync"
}
""",
        ))

        self.client.push('/foo/bar', source)

        self.assertEqual(len(self.client.requests), 1)
        request = self.client.requests[0]
        self.assertEqual(request[:3], ('POST', '/v1/files', None))

        headers, body = request[3:]
        content_type = headers['Content-Type']
        req, filename, content = self._parse_write_multipart(content_type, body)
        self.assertEqual(filename, '/foo/bar')
        self.assertEqual(content, b'content \xf0\x9f\x98\x80\nfoo\r\nbar')
        self.assertEqual(req, {
            'action': 'write',
            'files': [{'path': '/foo/bar'}],
        })

    def test_push_all_options(self):
        self.client.responses.append((
            {'Content-Type': 'application/json'},
            b"""
{
    "result": [
        {"path": "/foo/bar"}
    ],
    "status": "OK",
    "status-code": 200,
    "type": "sync"
}
""",
        ))

        self.client.push('/foo/bar', 'content', make_dirs=True, permissions=0o600,
                         user_id=12, user='bob', group_id=34, group='staff')

        self.assertEqual(len(self.client.requests), 1)
        request = self.client.requests[0]
        self.assertEqual(request[:3], ('POST', '/v1/files', None))

        headers, body = request[3:]
        content_type = headers['Content-Type']
        req, filename, content = self._parse_write_multipart(content_type, body)
        self.assertEqual(filename, '/foo/bar')
        self.assertEqual(content, b'content')
        self.assertEqual(req, {
            'action': 'write',
            'files': [{
                'path': '/foo/bar',
                'make-dirs': True,
                'permissions': '600',
                'user-id': 12,
                'user': 'bob',
                'group-id': 34,
                'group': 'staff',
            }],
        })

    def test_push_uid_gid(self):
        self.client.responses.append((
            {'Content-Type': 'application/json'},
            b"""
{
    "result": [
        {"path": "/foo/bar"}
    ],
    "status": "OK",
    "status-code": 200,
    "type": "sync"
}
""",
        ))

        self.client.push('/foo/bar', 'content', user_id=12, group_id=34)

        self.assertEqual(len(self.client.requests), 1)
        request = self.client.requests[0]
        self.assertEqual(request[:3], ('POST', '/v1/files', None))

        headers, body = request[3:]
        content_type = headers['Content-Type']
        req, filename, content = self._parse_write_multipart(content_type, body)
        self.assertEqual(filename, '/foo/bar')
        self.assertEqual(content, b'content')
        self.assertEqual(req, {
            'action': 'write',
            'files': [{
                'path': '/foo/bar',
                'user-id': 12,
                'group-id': 34,
            }],
        })

    def test_push_path_error(self):
        self.client.responses.append((
            {'Content-Type': 'application/json'},
            b"""
{
    "result": [
        {"path": "/foo/bar", "error": {"kind": "not-found", "message": "not found"}}
    ],
    "status": "OK",
    "status-code": 200,
    "type": "sync"
}
""",
        ))

        with self.assertRaises(pebble.PathError) as cm:
            self.client.push('/foo/bar', 'content')
        self.assertEqual(cm.exception.kind, 'not-found')
        self.assertEqual(cm.exception.message, 'not found')

        self.assertEqual(len(self.client.requests), 1)
        request = self.client.requests[0]
        self.assertEqual(request[:3], ('POST', '/v1/files', None))

        headers, body = request[3:]
        content_type = headers['Content-Type']
        req, filename, content = self._parse_write_multipart(content_type, body)
        self.assertEqual(filename, '/foo/bar')
        self.assertEqual(content, b'content')
        self.assertEqual(req, {
            'action': 'write',
            'files': [{'path': '/foo/bar'}],
        })

    def _parse_write_multipart(self,
                               content_type: str,
                               body: _bytes_generator):
        message = email.message.Message()
        message['Content-Type'] = content_type
        self.assertEqual(message.get_content_type(), 'multipart/form-data')
        boundary = message.get_param('boundary')
        assert isinstance(boundary, str)

        # We have to manually write the Content-Type with boundary, because
        # email.parser expects the entire multipart message with headers.
        parser = email.parser.BytesFeedParser()
        parser.feed(b'Content-Type: multipart/form-data; boundary='
                    + boundary.encode('utf-8') + b'\r\n\r\n')
        for b in body:
            # With the "memory efficient push" changes, body is an iterable.
            parser.feed(b)
        message = parser.close()

        req = None
        filename = None
        content = None
        for part in message.walk():
            name = part.get_param('name', header='Content-Disposition')
            if name == 'request':
                req = json.loads(part.get_payload())
            elif name == 'files':
                # decode=True, ironically, avoids decoding bytes to str
                content = part.get_payload(decode=True)
                filename = part.get_filename()
        return (req, filename, content)

    def test_list_files_path(self):
        self.client.responses.append({
            "result": [
                {
                    'path': '/etc/hosts',
                    'name': 'hosts',
                    'type': 'file',
                    'size': 123,
                    'permissions': '644',
                    'last-modified': '2021-01-28T14:37:04.291517768+13:00',
                    'user-id': 12,
                    'user': 'bob',
                    'group-id': 34,
                    'group': 'staff',
                },
                {
                    'path': '/etc/nginx',
                    'name': 'nginx',
                    'type': 'directory',
                    'permissions': '755',
                    'last-modified': '2020-01-01T01:01:01.000000+13:00',
                },
            ],
            'status': 'OK',
            'status-code': 200,
            'type': 'sync',
        })
        infos = self.client.list_files('/etc')

        self.assertEqual(len(infos), 2)
        self.assertEqual(infos[0].path, '/etc/hosts')
        self.assertEqual(infos[0].name, 'hosts')
        self.assertEqual(infos[0].type, pebble.FileType.FILE)
        self.assertEqual(infos[0].size, 123)
        self.assertEqual(infos[0].permissions, 0o644)
        self.assertEqual(infos[0].last_modified, datetime_nzdt(2021, 1, 28, 14, 37, 4, 291518))
        self.assertEqual(infos[0].user_id, 12)
        self.assertEqual(infos[0].user, 'bob')
        self.assertEqual(infos[0].group_id, 34)
        self.assertEqual(infos[0].group, 'staff')
        self.assertEqual(infos[1].path, '/etc/nginx')
        self.assertEqual(infos[1].name, 'nginx')
        self.assertEqual(infos[1].type, pebble.FileType.DIRECTORY)
        self.assertEqual(infos[1].size, None)
        self.assertEqual(infos[1].permissions, 0o755)
        self.assertEqual(infos[1].last_modified, datetime_nzdt(2020, 1, 1, 1, 1, 1, 0))
        self.assertIs(infos[1].user_id, None)
        self.assertIs(infos[1].user, None)
        self.assertIs(infos[1].group_id, None)
        self.assertIs(infos[1].group, None)

        self.assertEqual(self.client.requests, [
            ('GET', '/v1/files', {'action': 'list', 'path': '/etc'}, None),
        ])

    def test_list_files_pattern(self):
        self.client.responses.append({
            "result": [],
            'status': 'OK',
            'status-code': 200,
            'type': 'sync',
        })

        infos = self.client.list_files('/etc', pattern='*.conf')

        self.assertEqual(len(infos), 0)
        self.assertEqual(self.client.requests, [
            ('GET', '/v1/files', {'action': 'list', 'path': '/etc', 'pattern': '*.conf'}, None),
        ])

    def test_list_files_itself(self):
        self.client.responses.append({
            "result": [],
            'status': 'OK',
            'status-code': 200,
            'type': 'sync',
        })

        infos = self.client.list_files('/etc', itself=True)

        self.assertEqual(len(infos), 0)
        self.assertEqual(self.client.requests, [
            ('GET', '/v1/files', {'action': 'list', 'path': '/etc', 'itself': 'true'}, None),
        ])

    def test_make_dir_basic(self):
        self.client.responses.append({
            "result": [{'path': '/foo/bar'}],
            'status': 'OK',
            'status-code': 200,
            'type': 'sync',
        })
        self.client.make_dir('/foo/bar')
        req = {'action': 'make-dirs', 'dirs': [{
            'path': '/foo/bar',
        }]}
        self.assertEqual(self.client.requests, [
            ('POST', '/v1/files', None, req),
        ])

    def test_make_dir_all_options(self):
        self.client.responses.append({
            "result": [{'path': '/foo/bar'}],
            'status': 'OK',
            'status-code': 200,
            'type': 'sync',
        })
        self.client.make_dir('/foo/bar', make_parents=True, permissions=0o600,
                             user_id=12, user='bob', group_id=34, group='staff')

        req = {'action': 'make-dirs', 'dirs': [{
            'path': '/foo/bar',
            'make-parents': True,
            'permissions': '600',
            'user-id': 12,
            'user': 'bob',
            'group-id': 34,
            'group': 'staff',
        }]}
        self.assertEqual(self.client.requests, [
            ('POST', '/v1/files', None, req),
        ])

    def test_make_dir_error(self):
        self.client.responses.append({
            "result": [{
                'path': '/foo/bar',
                'error': {
                    'kind': 'permission-denied',
                    'message': 'permission denied',
                },
            }],
            'status': 'OK',
            'status-code': 200,
            'type': 'sync',
        })
        with self.assertRaises(pebble.PathError) as cm:
            self.client.make_dir('/foo/bar')
        self.assertIsInstance(cm.exception, pebble.Error)
        self.assertEqual(cm.exception.kind, 'permission-denied')
        self.assertEqual(cm.exception.message, 'permission denied')

    def test_remove_path_basic(self):
        self.client.responses.append({
            "result": [{'path': '/boo/far'}],
            'status': 'OK',
            'status-code': 200,
            'type': 'sync',
        })
        self.client.remove_path('/boo/far')
        req = {'action': 'remove', 'paths': [{
            'path': '/boo/far',
        }]}
        self.assertEqual(self.client.requests, [
            ('POST', '/v1/files', None, req),
        ])

    def test_remove_path_recursive(self):
        self.client.responses.append({
            "result": [{'path': '/boo/far'}],
            'status': 'OK',
            'status-code': 200,
            'type': 'sync',
        })
        self.client.remove_path('/boo/far', recursive=True)

        req = {'action': 'remove', 'paths': [{
            'path': '/boo/far',
            'recursive': True,
        }]}
        self.assertEqual(self.client.requests, [
            ('POST', '/v1/files', None, req),
        ])

    def test_remove_path_error(self):
        self.client.responses.append({
            "result": [{
                'path': '/boo/far',
                'error': {
                    'kind': 'generic-file-error',
                    'message': 'some other error',
                },
            }],
            'status': 'OK',
            'status-code': 200,
            'type': 'sync',
        })
        with self.assertRaises(pebble.PathError) as cm:
            self.client.remove_path('/boo/far')
        self.assertIsInstance(cm.exception, pebble.Error)
        self.assertEqual(cm.exception.kind, 'generic-file-error')
        self.assertEqual(cm.exception.message, 'some other error')

    def test_send_signal_name(self):
        self.client.responses.append({
            'result': True,
            'status': 'OK',
            'status-code': 200,
            'type': 'sync',
        })

        self.client.send_signal('SIGHUP', ['s1', 's2'])

        self.assertEqual(self.client.requests, [
            ('POST', '/v1/signals', None, {'signal': 'SIGHUP', 'services': ['s1', 's2']}),
        ])

    @unittest.skipUnless(hasattr(signal, 'SIGHUP'), 'signal constants not present')
    def test_send_signal_number(self):
        self.client.responses.append({
            'result': True,
            'status': 'OK',
            'status-code': 200,
            'type': 'sync',
        })

        self.client.send_signal(signal.SIGHUP, ['s1', 's2'])

        self.assertEqual(self.client.requests, [
            ('POST', '/v1/signals', None, {'signal': 'SIGHUP', 'services': ['s1', 's2']}),
        ])

    def test_send_signal_type_error(self):
        with self.assertRaises(TypeError):
            self.client.send_signal('SIGHUP', 'should-be-a-list')

        with self.assertRaises(TypeError):
            self.client.send_signal('SIGHUP', [1, 2])  # type: ignore

    def test_get_checks_all(self):
        self.client.responses.append({
            "result": [
                {
                    "name": "chk1",
                    "status": "up",
                    "threshold": 2,
                },
                {
                    "name": "chk2",
                    "level": "alive",
                    "status": "down",
                    "failures": 5,
                    "threshold": 3,
                }
            ],
            "status": "OK",
            "status-code": 200,
            "type": "sync"
        })
        checks = self.client.get_checks()
        self.assertEqual(len(checks), 2)
        self.assertEqual(checks[0].name, 'chk1')
        self.assertEqual(checks[0].level, pebble.CheckLevel.UNSET)
        self.assertEqual(checks[0].status, pebble.CheckStatus.UP)
        self.assertEqual(checks[0].failures, 0)
        self.assertEqual(checks[0].threshold, 2)
        self.assertEqual(checks[1].name, 'chk2')
        self.assertEqual(checks[1].level, pebble.CheckLevel.ALIVE)
        self.assertEqual(checks[1].status, pebble.CheckStatus.DOWN)
        self.assertEqual(checks[1].failures, 5)
        self.assertEqual(checks[1].threshold, 3)

        self.assertEqual(self.client.requests, [
            ('GET', '/v1/checks', {}, None),
        ])

    def test_get_checks_filters(self):
        self.client.responses.append({
            "result": [
                {
                    "name": "chk2",
                    "level": "ready",
                    "status": "up",
                    "threshold": 3,
                },
            ],
            "status": "OK",
            "status-code": 200,
            "type": "sync"
        })
        checks = self.client.get_checks(level=pebble.CheckLevel.READY, names=['chk2'])
        self.assertEqual(len(checks), 1)
        self.assertEqual(checks[0].name, 'chk2')
        self.assertEqual(checks[0].level, pebble.CheckLevel.READY)
        self.assertEqual(checks[0].status, pebble.CheckStatus.UP)
        self.assertEqual(checks[0].failures, 0)
        self.assertEqual(checks[0].threshold, 3)

        self.assertEqual(self.client.requests, [
            ('GET', '/v1/checks', {'level': 'ready', 'names': ['chk2']}, None),
        ])

    def test_checklevel_conversion(self):
        self.client.responses.append({
            "result": [
                {
                    "name": "chk2",
                    "level": "foobar!",
                    "status": "up",
                    "threshold": 3,
                },
            ],
            "status": "OK",
            "status-code": 200,
            "type": "sync"
        })
        checks = self.client.get_checks(level=pebble.CheckLevel.READY, names=['chk2'])
        self.assertEqual(len(checks), 1)
        self.assertEqual(checks[0].name, 'chk2')
        self.assertEqual(checks[0].level, 'foobar!')  # stays a raw string
        self.assertEqual(checks[0].status, pebble.CheckStatus.UP)
        self.assertEqual(checks[0].failures, 0)
        self.assertEqual(checks[0].threshold, 3)

        self.assertEqual(self.client.requests, [
            ('GET', '/v1/checks', {'level': 'ready', 'names': ['chk2']}, None),
        ])


class TestSocketClient(unittest.TestCase):
    def test_socket_not_found(self):
        client = pebble.Client(socket_path='does_not_exist')
        with self.assertRaises(pebble.ConnectionError) as cm:
            client.get_system_info()
        self.assertIsInstance(cm.exception, pebble.Error)
        self.assertIn("Could not connect to Pebble", str(cm.exception))

    def test_real_client(self):
        shutdown, socket_path = fake_pebble.start_server()

        try:
            client = pebble.Client(socket_path=socket_path)
            info = client.get_system_info()
            self.assertEqual(info.version, '3.14.159')

            change_id = client.start_services(['foo'], timeout=0)
            self.assertEqual(change_id, '1234')

            with self.assertRaises(pebble.APIError) as cm:
                client.start_services(['bar'], timeout=0)
            self.assertIsInstance(cm.exception, pebble.Error)
            self.assertEqual(cm.exception.code, 400)
            self.assertEqual(cm.exception.status, 'Bad Request')
            self.assertEqual(cm.exception.message, 'service "bar" does not exist')

        finally:
            shutdown()


class TestExecError(unittest.TestCase):
    def test_init(self):
        e = pebble.ExecError(['foo'], 42, 'out', 'err')
        self.assertEqual(e.command, ['foo'])
        self.assertEqual(e.exit_code, 42)
        self.assertEqual(e.stdout, 'out')
        self.assertEqual(e.stderr, 'err')

    def test_str(self):
        e = pebble.ExecError[str](['x'], 1, None, None)
        self.assertEqual(str(e), "non-zero exit code 1 executing ['x']")

        e = pebble.ExecError(['x'], 1, 'only-out', None)
        self.assertEqual(str(e), "non-zero exit code 1 executing ['x'], stdout='only-out'")

        e = pebble.ExecError(['x'], 1, None, 'only-err')
        self.assertEqual(str(e), "non-zero exit code 1 executing ['x'], stderr='only-err'")

        e = pebble.ExecError(['a', 'b'], 1, 'out', 'err')
        self.assertEqual(str(e), "non-zero exit code 1 executing ['a', 'b'], "
                                 + "stdout='out', stderr='err'")

    def test_str_truncated(self):
        e = pebble.ExecError(['foo'], 2, 'longout', 'longerr')
        e.STR_MAX_OUTPUT = 5  # type: ignore
        self.assertEqual(str(e), "non-zero exit code 2 executing ['foo'], "
                                 + "stdout='longo' [truncated], stderr='longe' [truncated]")


class MockWebsocket:
    def __init__(self):
        self.sends: typing.List[typing.Tuple[str, typing.Union[str, bytes]]] = []
        self.receives: typing.List[typing.Union[str, bytes]] = []

    def send_binary(self, b: bytes):
        self.sends.append(('BIN', b))

    def send(self, s: str):
        self.sends.append(('TXT', s))

    def recv(self):
        return self.receives.pop(0)

    def shutdown(self):
        pass


class TestExec(unittest.TestCase):
    def setUp(self):
        self.client = MockClient()
        self.time = MockTime()
        time_patcher = unittest.mock.patch('ops.pebble.time', self.time)
        time_patcher.start()
        self.addCleanup(time_patcher.stop)

    def add_responses(self, change_id: str, exit_code: int,
                      change_err: typing.Optional[str] = None):
        task_id = f"T{change_id}"  # create a task_id based on change_id
        self.client.responses.append({
            'change': change_id,
            'result': {'task-id': task_id},
        })

        change = build_mock_change_dict(change_id)
        # pyright doesn't understand "assert change.get('tasks') is not None"
        assert 'tasks' in change and change['tasks'] is not None
        change['tasks'][0]['data'] = {'exit-code': exit_code}
        if change_err is not None:
            change['err'] = change_err
        self.client.responses.append({
            'result': change,
        })

        stdio = MockWebsocket()
        stderr = MockWebsocket()
        control = MockWebsocket()
        self.client.websockets = {
            (task_id, 'stdio'): stdio,
            (task_id, 'stderr'): stderr,
            (task_id, 'control'): control,
        }
        return (stdio, stderr, control)

    def build_exec_data(self,
                        command: typing.List[str],
                        service_context: typing.Optional[str] = None,
                        environment: typing.Optional[typing.Dict[str, str]] = None,
                        working_dir: typing.Optional[str] = None,
                        timeout: typing.Optional[float] = None,
                        user_id: typing.Optional[int] = None,
                        user: typing.Optional[str] = None,
                        group_id: typing.Optional[int] = None,
                        group: typing.Optional[str] = None,
                        combine_stderr: bool = False):
        return {
            'command': command,
            'service-context': service_context,
            'environment': environment or {},
            'working-dir': working_dir,
            'timeout': f'{timeout:.3f}s' if timeout is not None else None,
            'user-id': user_id,
            'user': user,
            'group-id': group_id,
            'group': group,
            'split-stderr': not combine_stderr,
        }

    def test_arg_errors(self):
        with self.assertRaises(TypeError):
            self.client.exec('foo')  # type: ignore
        with self.assertRaises(ValueError):
            self.client.exec([])
        with self.assertRaises(ValueError):
            self.client.exec(['foo'], stdin='s', encoding=None)  # type: ignore
        with self.assertRaises(ValueError):
            self.client.exec(['foo'], stdin=b's')
        with self.assertRaises(TypeError):
            self.client.exec(['foo'], stdin=123)  # type: ignore
        with self.assertRaises(ValueError):
            self.client.exec(['foo'], stdout=io.StringIO(), stderr=io.StringIO(),
                             combine_stderr=True)

    def test_no_wait_call(self):
        self.add_responses('123', 0)
        with self.assertWarns(ResourceWarning) as cm:
            process = self.client.exec(['true'])
            del process
        self.assertEqual(str(cm.warning), 'ExecProcess instance garbage collected '
                                          + 'without call to wait() or wait_output()')

    def test_wait_exit_zero(self):
        self.add_responses('123', 0)

        process = self.client.exec(['true'])
        self.assertIsNotNone(process.stdout)
        self.assertIsNotNone(process.stderr)
        process.wait()

        self.assertEqual(self.client.requests, [
            ('POST', '/v1/exec', None, self.build_exec_data(['true'])),
            ('GET', '/v1/changes/123/wait', {'timeout': '4.000s'}, None),
        ])

    def test_wait_exit_nonzero(self):
        self.add_responses('456', 1)

        process = self.client.exec(['false'])
        with self.assertRaises(pebble.ExecError) as cm:
            process.wait()
        self.assertEqual(cm.exception.command, ['false'])
        self.assertEqual(cm.exception.exit_code, 1)
        self.assertEqual(cm.exception.stdout, None)
        self.assertEqual(cm.exception.stderr, None)

        self.assertEqual(self.client.requests, [
            ('POST', '/v1/exec', None, self.build_exec_data(['false'])),
            ('GET', '/v1/changes/456/wait', {'timeout': '4.000s'}, None),
        ])

    def test_wait_timeout(self):
        self.add_responses('123', 0)

        process = self.client.exec(['true'], timeout=2)
        process.wait()

        self.assertEqual(self.client.requests, [
            ('POST', '/v1/exec', None, self.build_exec_data(['true'], timeout=2)),
            ('GET', '/v1/changes/123/wait', {'timeout': '3.000s'}, None),
        ])

    def test_wait_other_args(self):
        self.add_responses('123', 0)

        process = self.client.exec(
            ['true'],
            environment={'K1': 'V1', 'K2': 'V2'},
            working_dir='WD',
            user_id=1000,
            user='bob',
            group_id=1000,
            group='staff',
        )
        process.wait()

        self.assertEqual(self.client.requests, [
            ('POST', '/v1/exec', None, self.build_exec_data(
                command=['true'],
                environment={'K1': 'V1', 'K2': 'V2'},
                working_dir='WD',
                user_id=1000,
                user='bob',
                group_id=1000,
                group='staff',
            )),
            ('GET', '/v1/changes/123/wait', {'timeout': '4.000s'}, None),
        ])

    def test_wait_change_error(self):
        self.add_responses('123', 0, change_err='change error!')

        process = self.client.exec(['true'])
        with self.assertRaises(pebble.ChangeError) as cm:
            process.wait()
        self.assertEqual(cm.exception.err, 'change error!')
        self.assertEqual(cm.exception.change.id, '123')

        self.assertEqual(self.client.requests, [
            ('POST', '/v1/exec', None, self.build_exec_data(['true'])),
            ('GET', '/v1/changes/123/wait', {'timeout': '4.000s'}, None),
        ])

    def test_send_signal(self):
        _, _, control = self.add_responses('123', 0)

        process = self.client.exec(['server'])
        process.send_signal('SIGHUP')
        num_sends = 1
        if hasattr(signal, 'SIGHUP'):
            process.send_signal(1)
            process.send_signal(signal.SIGHUP)
            num_sends += 2

        process.wait()

        self.assertEqual(self.client.requests, [
            ('POST', '/v1/exec', None, self.build_exec_data(['server'])),
            ('GET', '/v1/changes/123/wait', {'timeout': '4.000s'}, None),
        ])

        self.assertEqual(len(control.sends), num_sends)
        self.assertEqual(control.sends[0][0], 'TXT')
        self.assertEqual(json.loads(control.sends[0][1]),
                         {'command': 'signal', 'signal': {'name': 'SIGHUP'}})
        if hasattr(signal, 'SIGHUP'):
            self.assertEqual(control.sends[1][0], 'TXT')
            self.assertEqual(json.loads(control.sends[1][1]),
                             {'command': 'signal', 'signal': {'name': signal.Signals(1).name}})
            self.assertEqual(control.sends[2][0], 'TXT')
            self.assertEqual(json.loads(control.sends[2][1]),
                             {'command': 'signal', 'signal': {'name': 'SIGHUP'}})

    def test_wait_output(self):
        stdio, stderr, _ = self.add_responses('123', 0)
        stdio.receives.append(b'Python 3.8.10\n')
        stdio.receives.append('{"command":"end"}')
        stderr.receives.append('{"command":"end"}')

        process = self.client.exec(['python3', '--version'])
        out, err = process.wait_output()
        self.assertEqual(out, 'Python 3.8.10\n')
        self.assertEqual(err, '')

        self.assertEqual(self.client.requests, [
            ('POST', '/v1/exec', None, self.build_exec_data(['python3', '--version'])),
            ('GET', '/v1/changes/123/wait', {'timeout': '4.000s'}, None),
        ])
        self.assertEqual(stdio.sends, [])

    def test_wait_output_combine_stderr(self):
        stdio, _, _ = self.add_responses('123', 0)
        stdio.receives.append(b'invalid time interval\n')
        stdio.receives.append('{"command":"end"}')

        process = self.client.exec(['sleep', 'x'], combine_stderr=True)
        out, err = process.wait_output()
        self.assertEqual(out, 'invalid time interval\n')
        self.assertIsNone(err)
        self.assertIsNone(process.stderr)

        exec_data = self.build_exec_data(['sleep', 'x'], combine_stderr=True)
        self.assertEqual(self.client.requests, [
            ('POST', '/v1/exec', None, exec_data),
            ('GET', '/v1/changes/123/wait', {'timeout': '4.000s'}, None),
        ])
        self.assertEqual(stdio.sends, [])

    def test_wait_output_bytes(self):
        stdio, stderr, _ = self.add_responses('123', 0)
        stdio.receives.append(b'Python 3.8.10\n')
        stdio.receives.append('{"command":"end"}')
        stderr.receives.append('{"command":"end"}')

        process = self.client.exec(['python3', '--version'], encoding=None)
        out, err = process.wait_output()
        self.assertEqual(out, b'Python 3.8.10\n')
        self.assertEqual(err, b'')

        self.assertEqual(self.client.requests, [
            ('POST', '/v1/exec', None, self.build_exec_data(['python3', '--version'])),
            ('GET', '/v1/changes/123/wait', {'timeout': '4.000s'}, None),
        ])
        self.assertEqual(stdio.sends, [])

    def test_wait_output_exit_nonzero(self):
        stdio, stderr, _ = self.add_responses('123', 0)
        stdio.receives.append('{"command":"end"}')
        stderr.receives.append(b'file not found: x\n')
        stderr.receives.append('{"command":"end"}')

        process = self.client.exec(['ls', 'x'])
        out, err = process.wait_output()
        self.assertEqual(out, '')
        self.assertEqual(err, 'file not found: x\n')

        self.assertEqual(self.client.requests, [
            ('POST', '/v1/exec', None, self.build_exec_data(['ls', 'x'])),
            ('GET', '/v1/changes/123/wait', {'timeout': '4.000s'}, None),
        ])
        self.assertEqual(stdio.sends, [])

    def test_wait_output_exit_nonzero_combine_stderr(self):
        stdio, _, _ = self.add_responses('123', 0)
        stdio.receives.append(b'file not found: x\n')
        stdio.receives.append('{"command":"end"}')

        process = self.client.exec(['ls', 'x'], combine_stderr=True)
        out, err = process.wait_output()
        self.assertEqual(out, 'file not found: x\n')
        self.assertIsNone(err)

        exec_data = self.build_exec_data(['ls', 'x'], combine_stderr=True)
        self.assertEqual(self.client.requests, [
            ('POST', '/v1/exec', None, exec_data),
            ('GET', '/v1/changes/123/wait', {'timeout': '4.000s'}, None),
        ])
        self.assertEqual(stdio.sends, [])

    def test_wait_output_send_stdin(self):
        stdio, stderr, _ = self.add_responses('123', 0)
        stdio.receives.append(b'FOO\nBAR\n')
        stdio.receives.append('{"command":"end"}')
        stderr.receives.append('{"command":"end"}')

        process = self.client.exec(['awk', '{ print toupper($) }'], stdin='foo\nbar\n')
        out, err = process.wait_output()
        self.assertEqual(out, 'FOO\nBAR\n')
        self.assertEqual(err, '')

        self.assertEqual(self.client.requests, [
            ('POST', '/v1/exec', None, self.build_exec_data(['awk', '{ print toupper($) }'])),
            ('GET', '/v1/changes/123/wait', {'timeout': '4.000s'}, None),
        ])
        self.assertEqual(stdio.sends, [
            ('BIN', b'foo\nbar\n'),
            ('TXT', '{"command":"end"}'),
        ])

    def test_wait_output_send_stdin_bytes(self):
        stdio, stderr, _ = self.add_responses('123', 0)
        stdio.receives.append(b'FOO\nBAR\n')
        stdio.receives.append('{"command":"end"}')
        stderr.receives.append('{"command":"end"}')

        process = self.client.exec(['awk', '{ print toupper($) }'], stdin=b'foo\nbar\n',
                                   encoding=None)
        out, err = process.wait_output()
        self.assertEqual(out, b'FOO\nBAR\n')
        self.assertEqual(err, b'')

        self.assertEqual(self.client.requests, [
            ('POST', '/v1/exec', None, self.build_exec_data(['awk', '{ print toupper($) }'])),
            ('GET', '/v1/changes/123/wait', {'timeout': '4.000s'}, None),
        ])
        self.assertEqual(stdio.sends, [
            ('BIN', b'foo\nbar\n'),
            ('TXT', '{"command":"end"}'),
        ])

    def test_wait_output_no_stdout(self):
        stdio, stderr, _ = self.add_responses('123', 0)
        stdio.receives.append('{"command":"end"}')
        stderr.receives.append('{"command":"end"}')
        stdout_buffer = io.BytesIO()
        process = self.client.exec(["echo", "FOOBAR"], stdout=stdout_buffer, encoding=None)
        with self.assertRaises(TypeError):
            process.wait_output()

    def test_wait_output_bad_command(self):
        stdio, stderr, _ = self.add_responses('123', 0)
        stdio.receives.append(b'Python 3.8.10\n')
        stdio.receives.append('not json')  # bad JSON should be ignored
        stdio.receives.append('{"command":"foo"}')  # unknown command should be ignored
        stdio.receives.append('{"command":"end"}')
        stderr.receives.append('{"command":"end"}')

        with self.assertLogs('ops.pebble', level='WARNING') as cm:
            process = self.client.exec(['python3', '--version'])
            out, err = process.wait_output()
        self.assertEqual(cm.output, [
            "WARNING:ops.pebble:Cannot decode I/O command (invalid JSON)",
            "WARNING:ops.pebble:Invalid I/O command 'foo'",
        ])

        self.assertEqual(out, 'Python 3.8.10\n')
        self.assertEqual(err, '')

        self.assertEqual(self.client.requests, [
            ('POST', '/v1/exec', None, self.build_exec_data(['python3', '--version'])),
            ('GET', '/v1/changes/123/wait', {'timeout': '4.000s'}, None),
        ])
        self.assertEqual(stdio.sends, [])

    def test_wait_passed_output(self):
        io_ws, stderr, _ = self.add_responses('123', 0)
        io_ws.receives.append(b'foo\n')
        io_ws.receives.append('{"command":"end"}')
        stderr.receives.append(b'some error\n')
        stderr.receives.append('{"command":"end"}')

        out = io.StringIO()
        err = io.StringIO()
        process = self.client.exec(['echo', 'foo'], stdout=out, stderr=err)
        process.wait()
        self.assertEqual(out.getvalue(), 'foo\n')
        self.assertEqual(err.getvalue(), 'some error\n')

        self.assertEqual(self.client.requests, [
            ('POST', '/v1/exec', None, self.build_exec_data(['echo', 'foo'])),
            ('GET', '/v1/changes/123/wait', {'timeout': '4.000s'}, None),
        ])
        self.assertEqual(io_ws.sends, [])

    def test_wait_passed_output_combine_stderr(self):
        io_ws, _, _ = self.add_responses('123', 0)
        io_ws.receives.append(b'foo\n')
        io_ws.receives.append(b'some error\n')
        io_ws.receives.append('{"command":"end"}')

        out = io.StringIO()
        process = self.client.exec(['echo', 'foo'], stdout=out, combine_stderr=True)
        process.wait()
        self.assertEqual(out.getvalue(), 'foo\nsome error\n')
        self.assertIsNone(process.stderr)

        exec_data = self.build_exec_data(['echo', 'foo'], combine_stderr=True)
        self.assertEqual(self.client.requests, [
            ('POST', '/v1/exec', None, exec_data),
            ('GET', '/v1/changes/123/wait', {'timeout': '4.000s'}, None),
        ])
        self.assertEqual(io_ws.sends, [])

    def test_wait_passed_output_bytes(self):
        io_ws, stderr, _ = self.add_responses('123', 0)
        io_ws.receives.append(b'foo\n')
        io_ws.receives.append('{"command":"end"}')
        stderr.receives.append(b'some error\n')
        stderr.receives.append('{"command":"end"}')

        out = io.BytesIO()
        err = io.BytesIO()
        process = self.client.exec(['echo', 'foo'], stdout=out, stderr=err, encoding=None)
        process.wait()
        self.assertEqual(out.getvalue(), b'foo\n')
        self.assertEqual(err.getvalue(), b'some error\n')

        self.assertEqual(self.client.requests, [
            ('POST', '/v1/exec', None, self.build_exec_data(['echo', 'foo'])),
            ('GET', '/v1/changes/123/wait', {'timeout': '4.000s'}, None),
        ])
        self.assertEqual(io_ws.sends, [])

    def test_wait_passed_output_bad_command(self):
        io_ws, stderr, _ = self.add_responses('123', 0)
        io_ws.receives.append(b'foo\n')
        io_ws.receives.append('not json')  # bad JSON should be ignored
        io_ws.receives.append('{"command":"foo"}')  # unknown command should be ignored
        io_ws.receives.append('{"command":"end"}')
        stderr.receives.append(b'some error\n')
        stderr.receives.append('{"command":"end"}')

        out = io.StringIO()
        err = io.StringIO()

        with self.assertLogs('ops.pebble', level='WARNING') as cm:
            process = self.client.exec(['echo', 'foo'], stdout=out, stderr=err)
            process.wait()
        self.assertEqual(cm.output, [
            "WARNING:ops.pebble:Cannot decode I/O command (invalid JSON)",
            "WARNING:ops.pebble:Invalid I/O command 'foo'",
        ])

        self.assertEqual(out.getvalue(), 'foo\n')
        self.assertEqual(err.getvalue(), 'some error\n')

        self.assertEqual(self.client.requests, [
            ('POST', '/v1/exec', None, self.build_exec_data(['echo', 'foo'])),
            ('GET', '/v1/changes/123/wait', {'timeout': '4.000s'}, None),
        ])
        self.assertEqual(io_ws.sends, [])

    def test_wait_file_io(self):
        fin = tempfile.TemporaryFile(mode='w+', encoding='utf-8')
        out = tempfile.TemporaryFile(mode='w+', encoding='utf-8')
        err = tempfile.TemporaryFile(mode='w+', encoding='utf-8')
        try:
            fin.write('foo\n')
            fin.seek(0)

            io_ws, stderr, _ = self.add_responses('123', 0)
            io_ws.receives.append(b'foo\n')
            io_ws.receives.append('{"command":"end"}')
            stderr.receives.append(b'some error\n')
            stderr.receives.append('{"command":"end"}')

            process = self.client.exec(['echo', 'foo'], stdin=fin, stdout=out, stderr=err)
            process.wait()

            out.seek(0)
            self.assertEqual(out.read(), 'foo\n')
            err.seek(0)
            self.assertEqual(err.read(), 'some error\n')

            self.assertEqual(self.client.requests, [
                ('POST', '/v1/exec', None, self.build_exec_data(['echo', 'foo'])),
                ('GET', '/v1/changes/123/wait', {'timeout': '4.000s'}, None),
            ])
            self.assertEqual(io_ws.sends, [
                ('BIN', b'foo\n'),
                ('TXT', '{"command":"end"}'),
            ])
        finally:
            fin.close()
            out.close()
            err.close()

    def test_wait_returned_io(self):
        stdio = self.add_responses('123', 0)[0]
        stdio.receives.append(b'FOO BAR\n')
        stdio.receives.append(b'BAZZ\n')
        stdio.receives.append('{"command":"end"}')

        process = self.client.exec(['awk', '{ print toupper($) }'])
        assert process.stdout is not None and process.stdin is not None
        process.stdin.write('Foo Bar\n')
        self.assertEqual(process.stdout.read(4), 'FOO ')
        process.stdin.write('bazz\n')
        self.assertEqual(process.stdout.read(), 'BAR\nBAZZ\n')
        process.stdin.close()
        self.assertEqual(process.stdout.read(), '')
        process.wait()

        self.assertEqual(self.client.requests, [
            ('POST', '/v1/exec', None, self.build_exec_data(['awk', '{ print toupper($) }'])),
            ('GET', '/v1/changes/123/wait', {'timeout': '4.000s'}, None),
        ])
        self.assertEqual(stdio.sends, [
            ('BIN', b'Foo Bar\nbazz\n'),  # TextIOWrapper groups the writes together
            ('TXT', '{"command":"end"}'),
        ])

    def test_wait_returned_io_bytes(self):
        stdio = self.add_responses('123', 0)[0]
        stdio.receives.append(b'FOO BAR\n')
        stdio.receives.append(b'BAZZ\n')
        stdio.receives.append('{"command":"end"}')

        process = self.client.exec(['awk', '{ print toupper($) }'], encoding=None)
        assert process.stdout is not None and process.stdin is not None
        process.stdin.write(b'Foo Bar\n')
        self.assertEqual(process.stdout.read(4), b'FOO ')
        self.assertEqual(process.stdout.read(), b'BAR\n')
        process.stdin.write(b'bazz\n')
        self.assertEqual(process.stdout.read(), b'BAZZ\n')
        process.stdin.close()
        self.assertEqual(process.stdout.read(), b'')
        process.wait()

        self.assertEqual(self.client.requests, [
            ('POST', '/v1/exec', None, self.build_exec_data(['awk', '{ print toupper($) }'])),
            ('GET', '/v1/changes/123/wait', {'timeout': '4.000s'}, None),
        ])
        self.assertEqual(stdio.sends, [
            ('BIN', b'Foo Bar\n'),
            ('BIN', b'bazz\n'),
            ('TXT', '{"command":"end"}'),
        ])

    def test_connect_websocket_error(self):
        class Client(MockClient):
            def _connect_websocket(self, change_id: str, websocket_id: str):
                raise websocket.WebSocketException('conn!')

        self.client = Client()
        self.add_responses('123', 0, change_err='change error!')
        with self.assertRaises(pebble.ChangeError) as cm:
            self.client.exec(['foo'])
        self.assertEqual(str(cm.exception), 'change error!')

        self.client = Client()
        self.add_responses('123', 0)
        with self.assertRaises(pebble.ConnectionError) as cm:
            self.client.exec(['foo'])
        self.assertIn(str(cm.exception), 'unexpected error connecting to websockets: conn!')

    def test_websocket_send_raises(self):
        stdio, stderr, _ = self.add_responses('123', 0)
        raised = False

        def send_binary(b: bytes):
            nonlocal raised
            raised = True
            raise Exception('a simulated error!')

        stdio.send_binary = send_binary
        stdio.receives.append('{"command":"end"}')
        stderr.receives.append('{"command":"end"}')

        process = self.client.exec(['cat'], stdin='foo\nbar\n')
        out, err = process.wait_output()
        self.assertEqual(out, '')
        self.assertEqual(err, '')
        self.assertTrue(raised)

        self.assertEqual(self.client.requests, [
            ('POST', '/v1/exec', None, self.build_exec_data(['cat'])),
            ('GET', '/v1/changes/123/wait', {'timeout': '4.000s'}, None),
        ])
        self.assertEqual(stdio.sends, [])

    # You'd normally use pytest.mark.filterwarnings as a decorator, but
    # PytestUnhandledThreadExceptionWarning isn't present on older Python versions.
    if hasattr(pytest, 'PytestUnhandledThreadExceptionWarning'):
        test_websocket_send_raises = pytest.mark.filterwarnings(
            'ignore::pytest.PytestUnhandledThreadExceptionWarning')(test_websocket_send_raises)

    def test_websocket_recv_raises(self):
        stdio, stderr, _ = self.add_responses('123', 0)
        raised = False

        def recv():
            nonlocal raised
            raised = True
            raise Exception('a simulated error!')

        stdio.recv = recv
        stderr.receives.append('{"command":"end"}')

        process = self.client.exec(['cat'], stdin='foo\nbar\n')
        out, err = process.wait_output()
        self.assertEqual(out, '')
        self.assertEqual(err, '')
        self.assertTrue(raised)

        self.assertEqual(self.client.requests, [
            ('POST', '/v1/exec', None, self.build_exec_data(['cat'])),
            ('GET', '/v1/changes/123/wait', {'timeout': '4.000s'}, None),
        ])
        self.assertEqual(stdio.sends, [
            ('BIN', b'foo\nbar\n'),
            ('TXT', '{"command":"end"}'),
        ])

    if hasattr(pytest, 'PytestUnhandledThreadExceptionWarning'):
        test_websocket_recv_raises = pytest.mark.filterwarnings(
            'ignore::pytest.PytestUnhandledThreadExceptionWarning')(test_websocket_recv_raises)
