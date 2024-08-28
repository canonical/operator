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
import socket
import tempfile
import typing
import unittest
import unittest.mock
import unittest.util

import pytest
import websocket

import test.fake_pebble as fake_pebble
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


class TestTypes:
    def test_error(self):
        error = pebble.Error('error')
        assert isinstance(error, Exception)

    def test_timeout_error(self):
        error = pebble.TimeoutError('timeout!')
        assert isinstance(error, pebble.Error)
        assert isinstance(error, TimeoutError)
        assert str(error) == 'timeout!'

    def test_connection_error(self):
        error = pebble.ConnectionError('connerr!')
        assert isinstance(error, pebble.Error)
        assert str(error) == 'connerr!'

    def test_protocol_error(self):
        error = pebble.ProtocolError('protoerr!')
        assert isinstance(error, pebble.Error)
        assert str(error) == 'protoerr!'

    def test_path_error(self):
        error = pebble.PathError('not-found', 'thing not found')
        assert isinstance(error, pebble.Error)
        assert error.kind == 'not-found'
        assert error.message == 'thing not found'
        assert str(error) == 'not-found - thing not found'

    def test_api_error(self):
        body = {
            'result': {'message': 'no services to start provided'},
            'status': 'Bad Request',
            'status-code': 400,
            'type': 'error',
        }
        error = pebble.APIError(body, 400, 'Bad Request', 'no services')
        assert isinstance(error, pebble.Error)
        assert error.body == body
        assert error.code == 400
        assert error.status == 'Bad Request'
        assert error.message == 'no services'
        assert str(error) == 'no services'

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
        assert isinstance(error, pebble.Error)
        assert error.err == 'Some error'
        assert error.change == change
        assert str(error) == 'Some error'

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
        assert isinstance(error, pebble.Error)
        assert error.err == 'Some error'
        assert error.change == change
        assert (
            str(error)
            == """Some error
----- Logs from task 0 -----
LINE1
LINE2
----- Logs from task 2 -----
single log
-----"""
        )

    def test_warning_state(self):
        assert list(pebble.WarningState) == [
            pebble.WarningState.ALL,
            pebble.WarningState.PENDING,
        ]
        assert pebble.WarningState.ALL.value == 'all'
        assert pebble.WarningState.PENDING.value == 'pending'

    def test_change_state(self):
        assert list(pebble.ChangeState) == [
            pebble.ChangeState.ALL,
            pebble.ChangeState.IN_PROGRESS,
            pebble.ChangeState.READY,
        ]
        assert pebble.ChangeState.ALL.value == 'all'
        assert pebble.ChangeState.IN_PROGRESS.value == 'in-progress'
        assert pebble.ChangeState.READY.value == 'ready'

    def test_system_info_init(self):
        info = pebble.SystemInfo(version='1.2.3')
        assert info.version == '1.2.3'

    def test_system_info_from_dict(self):
        info = pebble.SystemInfo.from_dict({'version': '3.2.1'})
        assert info.version == '3.2.1'

    def test_warning_init(self):
        warning = pebble.Warning(
            message='Beware!',
            first_added=datetime_utc(2021, 1, 1, 1, 1, 1),
            last_added=datetime_utc(2021, 1, 26, 2, 3, 4),
            last_shown=None,
            expire_after='1s',
            repeat_after='2s',
        )
        assert warning.message == 'Beware!'
        assert warning.first_added == datetime_utc(2021, 1, 1, 1, 1, 1)
        assert warning.last_added == datetime_utc(2021, 1, 26, 2, 3, 4)
        assert warning.last_shown is None
        assert warning.expire_after == '1s'
        assert warning.repeat_after == '2s'

    def test_warning_from_dict(self):
        d: pebble._WarningDict = {
            'message': 'Look out...',
            'first-added': '2020-12-25T17:18:54.016273778+13:00',
            'last-added': '2021-01-26T17:01:02.12345+13:00',
            'expire-after': '1s',
            'repeat-after': '2s',
        }
        warning = pebble.Warning.from_dict(d)
        assert warning.message == 'Look out...'
        assert warning.first_added == datetime_nzdt(2020, 12, 25, 17, 18, 54, 16274)
        assert warning.last_added == datetime_nzdt(2021, 1, 26, 17, 1, 2, 123450)
        assert warning.last_shown is None
        assert warning.expire_after == '1s'
        assert warning.repeat_after == '2s'

        d['last-shown'] = None
        warning = pebble.Warning.from_dict(d)
        assert warning.last_shown is None

        d['last-shown'] = '2021-08-04T03:02:01.000000000+13:00'
        warning = pebble.Warning.from_dict(d)
        assert warning.last_shown == datetime_nzdt(2021, 8, 4, 3, 2, 1)

        d['first-added'] = '2020-02-03T02:00:40.000000+00:00'
        d['last-added'] = '2021-03-04T03:01:41.100000+00:00'
        d['last-shown'] = '2022-04-05T06:02:42.200000+00:00'
        warning = pebble.Warning.from_dict(d)
        assert warning.first_added == datetime_utc(2020, 2, 3, 2, 0, 40, 0)
        assert warning.last_added == datetime_utc(2021, 3, 4, 3, 1, 41, 100000)
        assert warning.last_shown == datetime_utc(2022, 4, 5, 6, 2, 42, 200000)

    def test_task_progress_init(self):
        tp = pebble.TaskProgress(label='foo', done=3, total=7)
        assert tp.label == 'foo'
        assert tp.done == 3
        assert tp.total == 7

    def test_task_progress_from_dict(self):
        tp = pebble.TaskProgress.from_dict({
            'label': 'foo',
            'done': 3,
            'total': 7,
        })
        assert tp.label == 'foo'
        assert tp.done == 3
        assert tp.total == 7

    def test_task_id(self):
        task_id = pebble.TaskID('1234')
        assert task_id == '1234'

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
        assert task.id == '42'
        assert task.kind == 'start'
        assert task.summary == 'Start service "svc"'
        assert task.status == 'Done'
        assert task.log == []
        assert task.progress.label == 'foo'
        assert task.progress.done == 3
        assert task.progress.total == 7
        assert task.spawn_time == datetime_nzdt(2021, 1, 28, 14, 37, 3, 270218)
        assert task.ready_time == datetime_nzdt(2021, 1, 28, 14, 37, 2, 247158)
        assert task.data == {}

    def test_task_from_dict(self):
        d: pebble._TaskDict = {
            'id': '78',
            'kind': 'start',
            'progress': {
                'done': 1,
                'label': '',
                'total': 1,
            },
            'ready-time': '2021-01-28T14:37:03.270218778+13:00',
            'spawn-time': '2021-01-28T14:37:02.247158162+13:00',
            'status': 'Done',
            'summary': 'Start service "svc"',
            'data': {'exit-code': 42},
        }
        task = pebble.Task.from_dict(d)
        assert task.id == '78'
        assert task.kind == 'start'
        assert task.summary == 'Start service "svc"'
        assert task.status == 'Done'
        assert task.log == []
        assert task.progress.label == ''
        assert task.progress.done == 1
        assert task.progress.total == 1
        assert task.ready_time == datetime_nzdt(2021, 1, 28, 14, 37, 3, 270219)
        assert task.spawn_time == datetime_nzdt(2021, 1, 28, 14, 37, 2, 247158)
        assert task.data == {'exit-code': 42}

        d['ready-time'] = '2021-01-28T14:37:03.270218778+00:00'
        d['spawn-time'] = '2021-01-28T14:37:02.247158162+00:00'
        task = pebble.Task.from_dict(d)
        assert task.ready_time == datetime_utc(2021, 1, 28, 14, 37, 3, 270219)
        assert task.spawn_time == datetime_utc(2021, 1, 28, 14, 37, 2, 247158)

    def test_change_id(self):
        change_id = pebble.ChangeID('1234')
        assert change_id == '1234'

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
        assert change.id == '70'
        assert change.kind == 'autostart'
        assert change.err == 'SILLY'
        assert change.ready
        assert change.ready_time == datetime_nzdt(2021, 1, 28, 14, 37, 4, 291517)
        assert change.spawn_time == datetime_nzdt(2021, 1, 28, 14, 37, 2, 247202)
        assert change.status == 'Done'
        assert change.summary == 'Autostart service "svc"'
        assert change.tasks == []
        assert change.data == {}

    def test_change_from_dict(self):
        d: pebble._ChangeDict = {
            'id': '70',
            'kind': 'autostart',
            'err': 'SILLY',
            'ready': True,
            'ready-time': '2021-01-28T14:37:04.291517768+13:00',
            'spawn-time': '2021-01-28T14:37:02.247202105+13:00',
            'status': 'Done',
            'summary': 'Autostart service "svc"',
            'tasks': [],
            'data': {'exit-code': 42},
        }
        change = pebble.Change.from_dict(d)
        assert change.id == '70'
        assert change.kind == 'autostart'
        assert change.err == 'SILLY'
        assert change.ready
        assert change.ready_time == datetime_nzdt(2021, 1, 28, 14, 37, 4, 291518)
        assert change.spawn_time == datetime_nzdt(2021, 1, 28, 14, 37, 2, 247202)
        assert change.status == 'Done'
        assert change.summary == 'Autostart service "svc"'
        assert change.tasks == []
        assert change.data == {'exit-code': 42}

        d['ready-time'] = '2021-01-28T14:37:04.291517768+00:00'
        d['spawn-time'] = '2021-01-28T14:37:02.247202105+00:00'
        change = pebble.Change.from_dict(d)
        assert change.ready_time == datetime_utc(2021, 1, 28, 14, 37, 4, 291518)
        assert change.spawn_time == datetime_utc(2021, 1, 28, 14, 37, 2, 247202)

    def test_file_type(self):
        assert list(pebble.FileType) == [
            pebble.FileType.FILE,
            pebble.FileType.DIRECTORY,
            pebble.FileType.SYMLINK,
            pebble.FileType.SOCKET,
            pebble.FileType.NAMED_PIPE,
            pebble.FileType.DEVICE,
            pebble.FileType.UNKNOWN,
        ]
        assert pebble.FileType.FILE.value == 'file'
        assert pebble.FileType.DIRECTORY.value == 'directory'
        assert pebble.FileType.SYMLINK.value == 'symlink'
        assert pebble.FileType.SOCKET.value == 'socket'
        assert pebble.FileType.NAMED_PIPE.value == 'named-pipe'
        assert pebble.FileType.DEVICE.value == 'device'
        assert pebble.FileType.UNKNOWN.value == 'unknown'

    def test_file_info_init(self):
        info = pebble.FileInfo(
            '/etc/hosts',
            'hosts',
            pebble.FileType.FILE,
            123,
            0o644,
            datetime_nzdt(2021, 1, 28, 14, 37, 4, 291518),
            12,
            'bob',
            34,
            'staff',
        )
        assert info.path == '/etc/hosts'
        assert info.name == 'hosts'
        assert info.type == pebble.FileType.FILE
        assert info.size == 123
        assert info.permissions == 0o644
        assert info.last_modified == datetime_nzdt(2021, 1, 28, 14, 37, 4, 291518)
        assert info.user_id == 12
        assert info.user == 'bob'
        assert info.group_id == 34
        assert info.group == 'staff'

    def test_file_info_from_dict(self):
        d: pebble._FileInfoDict = {
            'path': '/etc',
            'name': 'etc',
            'type': 'directory',
            'permissions': '644',
            'last-modified': '2021-01-28T14:37:04.291517768+13:00',
        }
        info = pebble.FileInfo.from_dict(d)
        assert info.path == '/etc'
        assert info.name == 'etc'
        assert info.type == pebble.FileType.DIRECTORY
        assert info.permissions == 0o644
        assert info.last_modified == datetime_nzdt(2021, 1, 28, 14, 37, 4, 291518)
        assert info.user_id is None
        assert info.user is None
        assert info.group_id is None
        assert info.group is None

        d['type'] = 'foobar'
        d['size'] = 123
        d['user-id'] = 12
        d['user'] = 'bob'
        d['group-id'] = 34
        d['group'] = 'staff'
        info = pebble.FileInfo.from_dict(d)
        assert info.type == 'foobar'
        assert info.size == 123
        assert info.user_id == 12
        assert info.user == 'bob'
        assert info.group_id == 34
        assert info.group == 'staff'

    def test_notice_from_dict(self):
        notice = pebble.Notice.from_dict({
            'id': '123',
            'user-id': 1000,
            'type': 'custom',
            'key': 'example.com/a',
            'first-occurred': '2023-12-07T17:01:02.123456789Z',
            'last-occurred': '2023-12-07T17:01:03.123456789Z',
            'last-repeated': '2023-12-07T17:01:04.123456789Z',
            'occurrences': 7,
            'last-data': {'k1': 'v1', 'k2': 'v2'},
            'repeat-after': '30m',
            'expire-after': '24h',
        })
        assert notice == pebble.Notice(
            id='123',
            user_id=1000,
            type=pebble.NoticeType.CUSTOM,
            key='example.com/a',
            first_occurred=datetime_utc(2023, 12, 7, 17, 1, 2, 123457),
            last_occurred=datetime_utc(2023, 12, 7, 17, 1, 3, 123457),
            last_repeated=datetime_utc(2023, 12, 7, 17, 1, 4, 123457),
            occurrences=7,
            last_data={'k1': 'v1', 'k2': 'v2'},
            repeat_after=datetime.timedelta(minutes=30),
            expire_after=datetime.timedelta(hours=24),
        )

        notice = pebble.Notice.from_dict({
            'id': '124',
            'type': 'other',
            'key': 'example.com/b',
            'first-occurred': '2023-12-07T17:01:02.123456789Z',
            'last-occurred': '2023-12-07T17:01:03.123456789Z',
            'last-repeated': '2023-12-07T17:01:04.123456789Z',
            'occurrences': 8,
        })
        assert notice == pebble.Notice(
            id='124',
            user_id=None,
            type='other',
            key='example.com/b',
            first_occurred=datetime_utc(2023, 12, 7, 17, 1, 2, 123457),
            last_occurred=datetime_utc(2023, 12, 7, 17, 1, 3, 123457),
            last_repeated=datetime_utc(2023, 12, 7, 17, 1, 4, 123457),
            occurrences=8,
        )


class TestPlan:
    def test_services(self):
        plan = pebble.Plan('')
        assert plan.services == {}

        plan = pebble.Plan("""
services:
  foo:
    override: replace
    command: echo foo
""")

        assert len(plan.services) == 1
        assert plan.services['foo'].name == 'foo'
        assert plan.services['foo'].override == 'replace'
        assert plan.services['foo'].command == 'echo foo'

        # Should be read-only ("can't set attribute")
        with pytest.raises(AttributeError):
            plan.services = {}  # type: ignore

    def test_checks(self):
        plan = pebble.Plan('')
        assert plan.checks == {}

        plan = pebble.Plan("""
checks:
  bar:
    override: replace
    http:
      url: https://example.com/
""")

        assert len(plan.checks) == 1
        assert plan.checks['bar'].name == 'bar'
        assert plan.checks['bar'].override == 'replace'
        assert plan.checks['bar'].http == {'url': 'https://example.com/'}

        # Should be read-only ("can't set attribute")
        with pytest.raises(AttributeError):
            plan.checks = {}  # type: ignore

    def test_log_targets(self):
        plan = pebble.Plan('')
        assert plan.log_targets == {}

        location = 'https://example.com:3100/loki/api/v1/push'
        plan = pebble.Plan(f"""
log-targets:
  baz:
    override: replace
    type: loki
    location: {location}
""")

        assert len(plan.log_targets) == 1
        assert plan.log_targets['baz'].name == 'baz'
        assert plan.log_targets['baz'].override == 'replace'
        assert plan.log_targets['baz'].type == 'loki'
        assert plan.log_targets['baz'].location == location

        # Should be read-only ("can't set attribute")
        with pytest.raises(AttributeError):
            plan.log_targets = {}  # type: ignore

    def test_yaml(self):
        # Starting with nothing, we get the empty result
        plan = pebble.Plan('')
        assert plan.to_yaml() == '{}\n'
        assert str(plan) == '{}\n'

        # With a service, we return validated yaml content.
        raw = """\
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
"""
        plan = pebble.Plan(raw)
        reformed = yaml.safe_dump(yaml.safe_load(raw))
        assert plan.to_yaml() == reformed
        assert str(plan) == reformed

    def test_plandict(self):
        # Starting with nothing, we get the empty result.
        plan = pebble.Plan({})
        assert plan.to_dict() == {}
        plan = pebble.Plan()
        assert plan.to_dict() == {}

        # With a service, we return validated yaml content.
        raw: pebble.PlanDict = {
            'services': {
                'foo': {
                    'override': 'replace',
                    'command': 'echo foo',
                },
            },
            'checks': {
                'bar': {
                    'http': {'url': 'https://example.com/'},
                },
            },
            'log-targets': {
                'baz': {
                    'override': 'replace',
                    'type': 'loki',
                    'location': 'https://example.com:3100/loki/api/v1/push',
                },
            },
        }
        plan = pebble.Plan(raw)
        assert plan.to_dict() == raw

    def test_service_equality(self):
        plan = pebble.Plan("""
services:
  foo:
    override: replace
    command: echo foo
""")

        old_service = pebble.Service(
            name='foo', raw={'override': 'replace', 'command': 'echo foo'}
        )
        old_services = {'foo': old_service}
        assert plan.services == old_services

        services_as_dict = {'foo': {'override': 'replace', 'command': 'echo foo'}}
        assert plan.services == services_as_dict

    def test_plan_equality(self):
        plan1 = pebble.Plan("""
services:
  foo:
    override: replace
    command: echo foo
""")
        assert plan1 != 'foo'
        plan2 = pebble.Plan("""
services:
  foo:
    command: echo foo
    override: replace
""")
        assert plan1 == plan2
        plan1_as_dict = {
            'services': {
                'foo': {
                    'command': 'echo foo',
                    'override': 'replace',
                },
            },
        }
        assert plan1 == plan1_as_dict
        plan3 = pebble.Plan("""
services:
  foo:
    override: replace
    command: echo bar
""")
        # Different command.
        assert plan1 != plan3
        plan4 = pebble.Plan("""
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
""")
        plan5 = pebble.Plan("""
services:
 foo:
  override: replace
  command: echo foo

checks:
 bar:
  http:
   https://different.example.com/

log-targets:
 baz:
  override: replace
  type: loki
  location: https://example.com:3100/loki/api/v1/push
""")
        # Different checks.bar.http
        assert plan4 != plan5
        plan6 = pebble.Plan("""
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
  location: https://example.com:3200/loki/api/v1/push
""")
        # Reordered elements.
        assert plan4 != plan6
        plan7 = pebble.Plan("""
services:
 foo:
  command: echo foo
  override: replace

log-targets:
 baz:
  type: loki
  override: replace
  location: https://example.com:3100/loki/api/v1/push

checks:
 bar:
  http:
   https://example.com/

""")
        # Reordered sections.
        assert plan4 == plan7


class TestLayer:
    def _assert_empty(self, layer: pebble.Layer):
        assert layer.summary == ''
        assert layer.description == ''
        assert layer.services == {}
        assert layer.checks == {}
        assert layer.log_targets == {}
        assert layer.to_dict() == {}

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
                    },
                },
            },
        }
        s = pebble.Layer(d)
        assert s.summary == 'Sum Mary'
        assert s.description == 'The quick brown fox!'
        assert s.services['foo'].name == 'foo'
        assert s.services['foo'].summary == 'Foo'
        assert s.services['foo'].command == 'echo foo'
        assert s.services['bar'].name == 'bar'
        assert s.services['bar'].summary == 'Bar'
        assert s.services['bar'].command == 'echo bar'
        assert s.log_targets['baz'].name == 'baz'
        assert s.log_targets['baz'].override == 'merge'
        assert s.log_targets['baz'].type == 'loki'
        assert s.log_targets['baz'].location == 'https://example.com'
        assert s.log_targets['baz'].services == ['foo']
        assert s.log_targets['baz'].labels == {'key': 'value $VAR'}

        assert s.to_dict() == d

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
        assert s.summary == 'Sum Mary'
        assert s.description == 'The quick brown fox!'
        assert s.services['foo'].name == 'foo'
        assert s.services['foo'].summary == 'Foo'
        assert s.services['foo'].command == 'echo foo'
        assert s.services['bar'].name == 'bar'
        assert s.services['bar'].summary == 'Bar'
        assert s.services['bar'].command == 'echo bar'
        assert s.services['bar'].environment == {'ENV1': 'value1', 'ENV2': 'value2'}
        assert s.services['bar'].user == 'bob'
        assert s.services['bar'].user_id == 1000
        assert s.services['bar'].group == 'staff'
        assert s.services['bar'].group_id == 2000

        assert s.checks['chk'].name == 'chk'
        assert s.checks['chk'].http == {'url': 'https://example.com/'}

        assert s.log_targets['baz'].name == 'baz'
        assert s.log_targets['baz'].override == 'replace'
        assert s.log_targets['baz'].location == 'https://example.com:3100'

        assert s.to_yaml() == yaml
        assert str(s) == yaml

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
            },
        }
        s = pebble.Layer(d)
        t = pebble.Layer(d)

        assert s.services == t.services

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
            },
        }
        t = pebble.Layer(d)
        assert s != t
        assert t != {}
        assert t == d

        s = pebble.Layer(d)
        assert s == t
        assert s != {}
        assert s == d

        assert s != 5


class TestService:
    def _assert_empty(self, service: pebble.Service, name: str):
        assert service.name == name
        assert service.summary == ''
        assert service.description == ''
        assert service.startup == ''
        assert service.override == ''
        assert service.command == ''
        assert service.after == []
        assert service.before == []
        assert service.requires == []
        assert service.environment == {}
        assert service.user == ''
        assert service.user_id is None
        assert service.group == ''
        assert service.group_id is None
        assert service.working_dir == ''
        assert service.on_success == ''
        assert service.on_failure == ''
        assert service.on_check_failure == {}
        assert service.backoff_delay == ''
        assert service.backoff_factor is None
        assert service.backoff_limit == ''
        assert service.kill_delay == ''
        assert service.to_dict() == {}

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
        assert s.name == 'Name 2'
        assert s.description == 'The lazy quick brown'
        assert s.startup == 'Start Up'
        assert s.override == 'override'
        assert s.command == 'echo sum mary'
        assert s.after == ['a1', 'a2']
        assert s.before == ['b1', 'b2']
        assert s.requires == ['r1', 'r2']
        assert s.environment == {'k1': 'v1', 'k2': 'v2'}
        assert s.user == 'bob'
        assert s.user_id == 1000
        assert s.group == 'staff'
        assert s.group_id == 2000
        assert s.working_dir == '/working/dir'
        assert s.on_success == 'restart'
        assert s.on_failure == 'ignore'
        assert s.on_check_failure == {'chk1': 'halt'}
        assert s.backoff_delay == '1s'
        assert s.backoff_factor == 4
        assert s.backoff_limit == '10s'
        assert s.kill_delay == '420s'

        assert s.to_dict() == d

        # Ensure pebble.Service has made copies of mutable objects
        s.after.append('a3')
        s.before.append('b3')
        s.requires.append('r3')
        s.environment['k3'] = 'v3'
        s.on_check_failure['chk2'] = 'ignore'
        assert s.after == ['a1', 'a2', 'a3']
        assert s.before == ['b1', 'b2', 'b3']
        assert s.requires == ['r1', 'r2', 'r3']
        assert s.environment == {'k1': 'v1', 'k2': 'v2', 'k3': 'v3'}
        assert d['after'] == ['a1', 'a2']
        assert d['before'] == ['b1', 'b2']
        assert d['requires'] == ['r1', 'r2']
        assert d['environment'] == {'k1': 'v1', 'k2': 'v2'}
        assert d['on-check-failure'] == {'chk1': 'halt'}

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
        one = pebble.Service('Name 1', d)
        two = pebble.Service('Name 1', d)
        assert one == two

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
        assert one == as_dict

        assert one != 5


class TestCheck:
    def _assert_empty(self, check: pebble.Check, name: str):
        assert check.name == name
        assert check.override == ''
        assert check.level == pebble.CheckLevel.UNSET
        assert check.period == ''
        assert check.timeout == ''
        assert check.threshold is None
        assert check.http is None
        assert check.tcp is None
        assert check.exec is None

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
        assert check.name == 'chk-http'
        assert check.override == 'replace'
        assert check.level == pebble.CheckLevel.ALIVE
        assert check.period == '10s'
        assert check.timeout == '3s'
        assert check.threshold == 5
        assert check.http == {'url': 'https://example.com/'}
        assert check.tcp == {'port': 80}
        assert check.exec == {'command': 'echo foo'}

        assert check.to_dict() == d

        # Ensure pebble.Check has made copies of mutable objects
        assert check.http is not None and check.tcp is not None and check.exec is not None
        check.http['url'] = 'https://www.google.com'
        assert d['http'] == {'url': 'https://example.com/'}
        check.tcp['port'] = 81
        assert d['tcp'] == {'port': 80}
        check.exec['command'] = 'foo'
        assert d['exec'] == {'command': 'echo foo'}

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
        assert check.level == 'foobar!'  # remains a string

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
        assert one == two
        assert one == d
        assert two == d
        assert one == one.to_dict()
        assert two == two.to_dict()
        d['level'] = 'ready'
        assert one != d

        assert one != 5


class TestLogTarget:
    def _assert_empty(self, target: pebble.LogTarget, name: str):
        assert target.name == name
        assert target.override == ''
        assert target.type == ''
        assert target.location == ''
        assert target.services == []
        assert target.labels == {}

    def test_name_only(self):
        target = pebble.LogTarget('tgt')
        self._assert_empty(target, 'tgt')

    def test_dict(self):
        d: pebble.LogTargetDict = {
            'override': 'replace',
            'type': 'loki',
            'location': 'https://example.com:3100/loki/api/v1/push',
            'services': ['+all'],
            'labels': {'key': 'val', 'key2': 'val2'},
        }
        target = pebble.LogTarget('tgt', d)
        assert target.name == 'tgt'
        assert target.override == 'replace'
        assert target.type == 'loki'
        assert target.location == 'https://example.com:3100/loki/api/v1/push'
        assert target.services == ['+all']
        assert target.labels == {'key': 'val', 'key2': 'val2'}

        assert target.to_dict() == d

        # Ensure pebble.Target has made copies of mutable objects.
        assert target.services is not None and target.labels is not None
        target.services[0] = '-all'
        assert d['services'] == ['+all']
        target.labels['key'] = 'val3'
        assert d['labels'] is not None
        assert d['labels']['key'] == 'val'

    def test_equality(self):
        d: pebble.LogTargetDict = {
            'override': 'replace',
            'type': 'loki',
            'location': 'https://example.com',
            'services': ['foo', 'bar'],
            'labels': {'k': 'v'},
        }
        one = pebble.LogTarget('one', d)
        two = pebble.LogTarget('two', d)
        assert one == two
        assert one == d
        assert two == d
        assert one == one.to_dict()
        assert two == two.to_dict()
        d['override'] = 'merge'
        assert one != d
        assert one != 5


class TestServiceInfo:
    def test_service_startup(self):
        assert list(pebble.ServiceStartup) == [
            pebble.ServiceStartup.ENABLED,
            pebble.ServiceStartup.DISABLED,
        ]
        assert pebble.ServiceStartup.ENABLED.value == 'enabled'
        assert pebble.ServiceStartup.DISABLED.value == 'disabled'

    def test_service_status(self):
        assert list(pebble.ServiceStatus) == [
            pebble.ServiceStatus.ACTIVE,
            pebble.ServiceStatus.INACTIVE,
            pebble.ServiceStatus.ERROR,
        ]
        assert pebble.ServiceStatus.ACTIVE.value == 'active'
        assert pebble.ServiceStatus.INACTIVE.value == 'inactive'
        assert pebble.ServiceStatus.ERROR.value == 'error'

    def test_service_info(self):
        s = pebble.ServiceInfo('svc1', pebble.ServiceStartup.ENABLED, pebble.ServiceStatus.ACTIVE)
        assert s.name == 'svc1'
        assert s.startup == pebble.ServiceStartup.ENABLED
        assert s.current == pebble.ServiceStatus.ACTIVE

        s = pebble.ServiceInfo('svc1', pebble.ServiceStartup.ENABLED, pebble.ServiceStatus.ACTIVE)
        assert s.name == 'svc1'
        assert s.startup == pebble.ServiceStartup.ENABLED
        assert s.current == pebble.ServiceStatus.ACTIVE

        s = pebble.ServiceInfo.from_dict({
            'name': 'svc2',
            'startup': 'disabled',
            'current': 'inactive',
        })
        assert s.name == 'svc2'
        assert s.startup == pebble.ServiceStartup.DISABLED
        assert s.current == pebble.ServiceStatus.INACTIVE

        s = pebble.ServiceInfo.from_dict({
            'name': 'svc2',
            'startup': 'thingy',
            'current': 'bob',
        })
        assert s.name == 'svc2'
        assert s.startup == 'thingy'
        assert s.current == 'bob'

    def test_is_running(self):
        s = pebble.ServiceInfo('s', pebble.ServiceStartup.ENABLED, pebble.ServiceStatus.ACTIVE)
        assert s.is_running()
        for current in [pebble.ServiceStatus.INACTIVE, pebble.ServiceStatus.ERROR, 'other']:
            s = pebble.ServiceInfo('s', pebble.ServiceStartup.ENABLED, current)
            assert not s.is_running()


class TestCheckInfo:
    def test_check_level(self):
        assert list(pebble.CheckLevel) == [
            pebble.CheckLevel.UNSET,
            pebble.CheckLevel.ALIVE,
            pebble.CheckLevel.READY,
        ]
        assert pebble.CheckLevel.UNSET.value == ''
        assert pebble.CheckLevel.ALIVE.value == 'alive'
        assert pebble.CheckLevel.READY.value == 'ready'

    def test_check_status(self):
        assert list(pebble.CheckStatus) == [
            pebble.CheckStatus.UP,
            pebble.CheckStatus.DOWN,
        ]
        assert pebble.CheckStatus.UP.value == 'up'
        assert pebble.CheckStatus.DOWN.value == 'down'

    def test_check_info(self):
        check = pebble.CheckInfo(
            name='chk1',
            level=pebble.CheckLevel.READY,
            status=pebble.CheckStatus.UP,
            threshold=3,
        )
        assert check.name == 'chk1'
        assert check.level == pebble.CheckLevel.READY
        assert check.status == pebble.CheckStatus.UP
        assert check.failures == 0
        assert check.threshold == 3
        assert check.change_id is None

        check = pebble.CheckInfo(
            name='chk2',
            level=pebble.CheckLevel.ALIVE,
            status=pebble.CheckStatus.DOWN,
            failures=5,
            threshold=3,
            change_id=pebble.ChangeID('10'),
        )
        assert check.name == 'chk2'
        assert check.level == pebble.CheckLevel.ALIVE
        assert check.status == pebble.CheckStatus.DOWN
        assert check.failures == 5
        assert check.threshold == 3
        assert check.change_id == pebble.ChangeID('10')

        d: pebble._CheckInfoDict = {
            'name': 'chk3',
            'status': 'up',
            'threshold': 3,
        }
        check = pebble.CheckInfo.from_dict(d)
        assert check.name == 'chk3'
        assert check.level == pebble.CheckLevel.UNSET
        assert check.status == pebble.CheckStatus.UP
        assert check.failures == 0
        assert check.threshold == 3
        assert check.change_id is None

        check = pebble.CheckInfo.from_dict({
            'name': 'chk4',
            'level': pebble.CheckLevel.UNSET,
            'status': pebble.CheckStatus.DOWN,
            'failures': 3,
            'threshold': 3,
            'change-id': '42',
        })
        assert check.name == 'chk4'
        assert check.level == pebble.CheckLevel.UNSET
        assert check.status == pebble.CheckStatus.DOWN
        assert check.failures == 3
        assert check.threshold == 3
        assert check.change_id == pebble.ChangeID('42')


_bytes_generator = typing.Generator[bytes, typing.Any, typing.Any]


class MockClient(pebble.Client):
    """Mock Pebble client that simply records requests and returns stored responses."""

    def __init__(self):
        self.requests: typing.List[typing.Any] = []
        self.responses: typing.List[typing.Any] = []
        self.timeout = 5
        self.websockets: typing.Dict[typing.Any, MockWebsocket] = {}

    def _request(
        self,
        method: str,
        path: str,
        query: typing.Optional[typing.Dict[str, typing.Any]] = None,
        body: typing.Optional[typing.Dict[str, typing.Any]] = None,
    ) -> typing.Dict[str, typing.Any]:
        self.requests.append((method, path, query, body))
        resp = self.responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        if callable(resp):
            resp = resp()
        return resp

    def _request_raw(
        self,
        method: str,
        path: str,
        query: typing.Optional[typing.Dict[str, typing.Any]] = None,
        headers: typing.Optional[typing.Dict[str, str]] = None,
        data: typing.Optional[typing.Union[bytes, _bytes_generator]] = None,
    ):
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
        'id': change_id,
        'kind': 'autostart',
        'ready': True,
        'ready-time': '2021-01-28T14:37:04.291517768+13:00',
        'spawn-time': '2021-01-28T14:37:02.247202105+13:00',
        'status': 'Done',
        'summary': 'Autostart service "svc"',
        'tasks': [
            {
                'id': '78',
                'kind': 'start',
                'progress': {
                    'done': 1,
                    'label': '',
                    'total': 1,
                    'extra-field': 'foo',  # type: ignore
                },
                'ready-time': '2021-01-28T14:37:03.270218778+13:00',
                'spawn-time': '2021-01-28T14:37:02.247158162+13:00',
                'status': 'Done',
                'summary': 'Start service "svc"',
                'extra-field': 'foo',
            },
        ],
        'extra-field': 'foo',
    }


class MultipartParserTestCase:
    def __init__(
        self,
        name: str,
        data: bytes,
        want_headers: typing.List[bytes],
        want_bodies: typing.List[bytes],
        want_bodies_done: typing.List[bool],
        max_boundary: int = 14,
        max_lookahead: int = 8 * 1024,
        error: str = '',
    ):
        self.name = name
        self.data = data
        self.want_headers = want_headers
        self.want_bodies = want_bodies
        self.want_bodies_done = want_bodies_done
        self.max_boundary = max_boundary
        self.max_lookahead = max_lookahead
        self.error = error


class TestMultipartParser:
    @pytest.mark.parametrize(
        'test',
        [
            MultipartParserTestCase(
                'baseline',
                b'\r\n--qwerty\r\nheader foo\r\n\r\nfoo bar\nfoo bar\r\n--qwerty--\r\n',
                [b'header foo\r\n\r\n'],
                [b'foo bar\nfoo bar'],
                want_bodies_done=[True],
            ),
            MultipartParserTestCase(
                'incomplete header',
                b'\r\n--qwerty\r\nheader foo\r\n',
                [],
                [],
                want_bodies_done=[],
            ),
            MultipartParserTestCase(
                'missing header',
                b'\r\n--qwerty\r\nheader foo\r\n' + 40 * b' ',
                [],
                [],
                want_bodies_done=[],
                max_lookahead=40,
                error='header terminator not found',
            ),
            MultipartParserTestCase(
                'incomplete body terminator',
                b'\r\n--qwerty\r\nheader foo\r\n\r\nfoo bar\r\n--qwerty\rhello my name is joe and I work in a button factory',  # noqa
                [b'header foo\r\n\r\n'],
                [b'foo bar\r\n--qwerty\rhello my name is joe and I work in a '],
                want_bodies_done=[False],
            ),
            MultipartParserTestCase(
                'empty body',
                b'\r\n--qwerty\r\nheader foo\r\n\r\n\r\n--qwerty\r\n',
                [b'header foo\r\n\r\n'],
                [b''],
                want_bodies_done=[True],
            ),
            MultipartParserTestCase(
                'ignore leading garbage',
                b'hello my name is joe\r\n\n\n\n\r\n--qwerty\r\nheader foo\r\n\r\nfoo bar\r\n--qwerty\r\n',  # noqa
                [b'header foo\r\n\r\n'],
                [b'foo bar'],
                want_bodies_done=[True],
            ),
            MultipartParserTestCase(
                'ignore trailing garbage',
                b'\r\n--qwerty\r\nheader foo\r\n\r\nfoo bar\r\n--qwerty\r\nhello my name is joe',
                [b'header foo\r\n\r\n'],
                [b'foo bar'],
                want_bodies_done=[True],
            ),
            MultipartParserTestCase(
                'boundary allow linear whitespace',
                b'\r\n--qwerty \t \r\nheader foo\r\n\r\nfoo bar\r\n--qwerty\r\n',
                [b'header foo\r\n\r\n'],
                [b'foo bar'],
                want_bodies_done=[True],
                max_boundary=20,
            ),
            MultipartParserTestCase(
                'terminal boundary allow linear whitespace',
                b'\r\n--qwerty\r\nheader foo\r\n\r\nfoo bar\r\n--qwerty-- \t \r\n',
                [b'header foo\r\n\r\n'],
                [b'foo bar'],
                want_bodies_done=[True],
                max_boundary=20,
            ),
            MultipartParserTestCase(
                'multiple parts',
                b'\r\n--qwerty \t \r\nheader foo\r\n\r\nfoo bar\r\n--qwerty\r\nheader bar\r\n\r\nfoo baz\r\n--qwerty--\r\n',  # noqa
                [b'header foo\r\n\r\n', b'header bar\r\n\r\n'],
                [b'foo bar', b'foo baz'],
                want_bodies_done=[True, True],
            ),
            MultipartParserTestCase(
                'ignore after terminal boundary',
                b'\r\n--qwerty \t \r\nheader foo\r\n\r\nfoo bar\r\n--qwerty--\r\nheader bar\r\n\r\nfoo baz\r\n--qwerty--\r\n',  # noqa
                [b'header foo\r\n\r\n'],
                [b'foo bar'],
                want_bodies_done=[True],
            ),
        ],
    )
    def test_multipart_parser(self, test: MultipartParserTestCase):
        chunk_sizes = [1, 2, 3, 4, 5, 7, 13, 17, 19, 23, 29, 31, 37, 42, 50, 100, 1000]
        marker = b'qwerty'
        for chunk_size in chunk_sizes:
            headers: typing.List[bytes] = []
            bodies: typing.List[bytes] = []
            bodies_done: typing.List[bool] = []

            # All of the "noqa: B023" here are due to a ruff bug:
            # https://github.com/astral-sh/ruff/issues/7847
            # ruff should tell us when the 'noqa's are no longer required.
            def handle_header(data: typing.Any):
                headers.append(bytes(data))  # noqa: B023
                bodies.append(b'')  # noqa: B023
                bodies_done.append(False)  # noqa: B023

            def handle_body(data: bytes, done: bool = False):
                bodies[-1] += data  # noqa: B023
                bodies_done[-1] = done  # noqa: B023

            parser = pebble._MultipartParser(
                marker,
                handle_header,
                handle_body,
                max_boundary_length=test.max_boundary,
                max_lookahead=test.max_lookahead,
            )
            src = io.BytesIO(test.data)

            try:
                while True:
                    data = src.read(chunk_size)
                    if not data:
                        break
                    parser.feed(data)
            except Exception as err:
                if not test.error:
                    pytest.fail(f'unexpected error: {err}')
                    break
                assert test.error == str(err)
            else:
                if test.error:
                    pytest.fail(f'missing expected error: {test.error!r}')

                msg = f'test case ({test.name}), chunk size {chunk_size}'
                assert test.want_headers == headers, msg
                assert test.want_bodies == bodies, msg
                assert test.want_bodies_done == bodies_done, msg


@pytest.fixture
def time():
    return MockTime()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, time: MockTime):
    client = MockClient()
    monkeypatch.setattr('ops.pebble.time', time)
    return client


class TestClient:
    def test_client_init(self):
        pebble.Client(socket_path='foo')  # test that constructor runs
        with pytest.raises(TypeError):
            pebble.Client()  # type: ignore (socket_path arg required)

    def test_get_system_info(self, client: MockClient):
        client.responses.append({
            'result': {
                'version': '1.2.3',
                'extra-field': 'foo',
            },
            'status': 'OK',
            'status-code': 200,
            'type': 'sync',
        })
        info = client.get_system_info()
        assert info.version == '1.2.3'
        assert client.requests == [
            ('GET', '/v1/system-info', None, None),
        ]

    def test_get_warnings(self, client: MockClient):
        empty: typing.Dict[str, typing.Any] = {
            'result': [],
            'status': 'OK',
            'status-code': 200,
            'type': 'sync',
        }
        client.responses.append(empty)
        warnings = client.get_warnings()
        assert warnings == []

        client.responses.append(empty)
        warnings = client.get_warnings(select=pebble.WarningState.ALL)
        assert warnings == []

        assert client.requests == [
            ('GET', '/v1/warnings', {'select': 'pending'}, None),
            ('GET', '/v1/warnings', {'select': 'all'}, None),
        ]

    def test_ack_warnings(self, client: MockClient):
        client.responses.append({'result': 0, 'status': 'OK', 'status-code': 200, 'type': 'sync'})
        num = client.ack_warnings(datetime_nzdt(2021, 1, 28, 15, 11, 0))
        assert num == 0
        assert client.requests == [
            (
                'POST',
                '/v1/warnings',
                None,
                {
                    'action': 'okay',
                    'timestamp': '2021-01-28T15:11:00+13:00',
                },
            ),
        ]

    def assert_mock_change(self, change: pebble.Change):
        assert change.id == '70'
        assert change.kind == 'autostart'
        assert change.summary == 'Autostart service "svc"'
        assert change.status == 'Done'
        assert len(change.tasks) == 1
        assert change.tasks[0].id == '78'
        assert change.tasks[0].kind == 'start'
        assert change.tasks[0].summary == 'Start service "svc"'
        assert change.tasks[0].status == 'Done'
        assert change.tasks[0].log == []
        assert change.tasks[0].progress.done == 1
        assert change.tasks[0].progress.label == ''
        assert change.tasks[0].progress.total == 1
        assert change.tasks[0].ready_time == datetime_nzdt(2021, 1, 28, 14, 37, 3, 270219)
        assert change.tasks[0].spawn_time == datetime_nzdt(2021, 1, 28, 14, 37, 2, 247158)
        assert change.ready
        assert change.err is None
        assert change.ready_time == datetime_nzdt(2021, 1, 28, 14, 37, 4, 291518)
        assert change.spawn_time == datetime_nzdt(2021, 1, 28, 14, 37, 2, 247202)

    def test_get_changes(self, client: MockClient):
        empty: typing.Dict[str, typing.Any] = {
            'result': [],
            'status': 'OK',
            'status-code': 200,
            'type': 'sync',
        }
        client.responses.append(empty)
        changes = client.get_changes()
        assert changes == []

        client.responses.append(empty)
        changes = client.get_changes(select=pebble.ChangeState.ALL)
        assert changes == []

        client.responses.append(empty)
        changes = client.get_changes(select=pebble.ChangeState.ALL, service='foo')
        assert changes == []

        client.responses.append({
            'result': [
                build_mock_change_dict(),
            ],
            'status': 'OK',
            'status-code': 200,
            'type': 'sync',
        })
        changes = client.get_changes()
        assert len(changes) == 1
        self.assert_mock_change(changes[0])

        assert client.requests == [
            ('GET', '/v1/changes', {'select': 'in-progress'}, None),
            ('GET', '/v1/changes', {'select': 'all'}, None),
            ('GET', '/v1/changes', {'select': 'all', 'for': 'foo'}, None),
            ('GET', '/v1/changes', {'select': 'in-progress'}, None),
        ]

    def test_get_change(self, client: MockClient):
        client.responses.append({
            'result': build_mock_change_dict(),
            'status': 'OK',
            'status-code': 200,
            'type': 'sync',
        })
        change = client.get_change(pebble.ChangeID('70'))
        self.assert_mock_change(change)
        assert client.requests == [
            ('GET', '/v1/changes/70', None, None),
        ]

    def test_get_change_str(self, client: MockClient):
        client.responses.append({
            'result': build_mock_change_dict(),
            'status': 'OK',
            'status-code': 200,
            'type': 'sync',
        })
        change = client.get_change('70')  # type: ignore
        self.assert_mock_change(change)
        assert client.requests == [
            ('GET', '/v1/changes/70', None, None),
        ]

    def test_abort_change(self, client: MockClient):
        client.responses.append({
            'result': build_mock_change_dict(),
            'status': 'OK',
            'status-code': 200,
            'type': 'sync',
        })
        change = client.abort_change(pebble.ChangeID('70'))
        self.assert_mock_change(change)
        assert client.requests == [
            ('POST', '/v1/changes/70', None, {'action': 'abort'}),
        ]

    def _services_action_helper(
        self,
        client: MockClient,
        action: str,
        api_func: typing.Callable[[], str],
        services: typing.List[str],
    ):
        client.responses.append({
            'change': '70',
            'result': None,
            'status': 'Accepted',
            'status-code': 202,
            'type': 'async',
        })
        change = build_mock_change_dict()
        change['ready'] = True
        client.responses.append({
            'result': change,
            'status': 'OK',
            'status-code': 200,
            'type': 'sync',
        })
        change_id = api_func()
        assert change_id == '70'
        assert client.requests == [
            ('POST', '/v1/services', None, {'action': action, 'services': services}),
            ('GET', '/v1/changes/70/wait', {'timeout': '4.000s'}, None),
        ]

    def _services_action_async_helper(
        self,
        client: MockClient,
        action: str,
        api_func: typing.Callable[..., str],
        services: typing.List[str],
    ):
        client.responses.append({
            'change': '70',
            'result': None,
            'status': 'Accepted',
            'status-code': 202,
            'type': 'async',
        })
        change_id = api_func(timeout=0)
        assert change_id == '70'
        assert client.requests == [
            ('POST', '/v1/services', None, {'action': action, 'services': services}),
        ]

    def test_autostart_services(self, client: MockClient):
        self._services_action_helper(client, 'autostart', client.autostart_services, [])

    def test_autostart_services_async(self, client: MockClient):
        self._services_action_async_helper(client, 'autostart', client.autostart_services, [])

    def test_replan_services(self, client: MockClient):
        self._services_action_helper(client, 'replan', client.replan_services, [])

    def test_replan_services_async(self, client: MockClient):
        self._services_action_async_helper(client, 'replan', client.replan_services, [])

    def test_start_services(self, client: MockClient):
        def api_func():
            return client.start_services(['svc'])

        self._services_action_helper(client, 'start', api_func, ['svc'])

        with pytest.raises(TypeError):
            client.start_services(1)  # type: ignore

        with pytest.raises(TypeError):
            client.start_services([1])  # type: ignore

        with pytest.raises(TypeError):
            client.start_services([['foo']])  # type: ignore

    def test_start_services_async(self, client: MockClient):
        def api_func(timeout: float = 30):
            return client.start_services(['svc'], timeout=timeout)

        self._services_action_async_helper(client, 'start', api_func, ['svc'])

    def test_stop_services(self, client: MockClient):
        def api_func():
            return client.stop_services(['svc'])

        self._services_action_helper(client, 'stop', api_func, ['svc'])

        with pytest.raises(TypeError):
            client.stop_services(1)  # type: ignore

        with pytest.raises(TypeError):
            client.stop_services([1])  # type: ignore

        with pytest.raises(TypeError):
            client.stop_services([['foo']])  # type: ignore

    def test_stop_services_async(self, client: MockClient):
        def api_func(timeout: float = 30):
            return client.stop_services(['svc'], timeout=timeout)

        self._services_action_async_helper(client, 'stop', api_func, ['svc'])

    def test_restart_services(self, client: MockClient):
        def api_func():
            return client.restart_services(['svc'])

        self._services_action_helper(client, 'restart', api_func, ['svc'])

        with pytest.raises(TypeError):
            client.restart_services(1)  # type: ignore

        with pytest.raises(TypeError):
            client.restart_services([1])  # type: ignore

        with pytest.raises(TypeError):
            client.restart_services([['foo']])  # type: ignore

    def test_restart_services_async(self, client: MockClient):
        def api_func(timeout: float = 30):
            return client.restart_services(['svc'], timeout=timeout)

        self._services_action_async_helper(client, 'restart', api_func, ['svc'])

    def test_change_error(self, client: MockClient):
        client.responses.append({
            'change': '70',
            'result': None,
            'status': 'Accepted',
            'status-code': 202,
            'type': 'async',
        })
        change = build_mock_change_dict()
        change['err'] = 'Some kind of service error'
        client.responses.append({
            'result': change,
            'status': 'OK',
            'status-code': 200,
            'type': 'sync',
        })
        excinfo: pytest.ExceptionInfo[pebble.ChangeError]
        with pytest.raises(pebble.ChangeError) as excinfo:
            client.autostart_services()
        assert isinstance(excinfo.value, pebble.Error)
        assert excinfo.value.err == 'Some kind of service error'
        assert isinstance(excinfo.value.change, pebble.Change)
        assert excinfo.value.change.id == '70'

        assert client.requests == [
            ('POST', '/v1/services', None, {'action': 'autostart', 'services': []}),
            ('GET', '/v1/changes/70/wait', {'timeout': '4.000s'}, None),
        ]

    def test_wait_change_success(self, client: MockClient, timeout: typing.Optional[float] = 30.0):
        change = build_mock_change_dict()
        client.responses.append({
            'result': change,
            'status': 'OK',
            'status-code': 200,
            'type': 'sync',
        })

        response = client.wait_change(pebble.ChangeID('70'), timeout=timeout)
        assert response.id == '70'
        assert response.ready

        assert client.requests == [
            ('GET', '/v1/changes/70/wait', {'timeout': '4.000s'}, None),
        ]

    def test_wait_change_success_timeout_none(self, client: MockClient):
        self.test_wait_change_success(client, timeout=None)

    def test_wait_change_success_multiple_calls(self, client: MockClient, time: MockTime):
        def timeout_response(n: float):
            time.sleep(n)  # simulate passing of time due to wait_change call
            raise pebble.APIError({}, 504, 'Gateway Timeout', 'timed out')

        client.responses.append(lambda: timeout_response(4))

        change = build_mock_change_dict()
        client.responses.append({
            'result': change,
            'status': 'OK',
            'status-code': 200,
            'type': 'sync',
        })

        response = client.wait_change(pebble.ChangeID('70'))
        assert response.id == '70'
        assert response.ready

        assert client.requests == [
            ('GET', '/v1/changes/70/wait', {'timeout': '4.000s'}, None),
            ('GET', '/v1/changes/70/wait', {'timeout': '4.000s'}, None),
        ]

        assert time.time() == 4

    def test_wait_change_success_polled(
        self,
        client: MockClient,
        time: MockTime,
        timeout: typing.Optional[float] = 30.0,
    ):
        # Trigger polled mode
        client.responses.append(pebble.APIError({}, 404, 'Not Found', 'not found'))
        for i in range(3):
            change = build_mock_change_dict()
            change['ready'] = i == 2
            client.responses.append({
                'result': change,
                'status': 'OK',
                'status-code': 200,
                'type': 'sync',
            })

        response = client.wait_change(pebble.ChangeID('70'), timeout=timeout, delay=1)
        assert response.id == '70'
        assert response.ready

        assert client.requests == [
            ('GET', '/v1/changes/70/wait', {'timeout': '4.000s'}, None),
            ('GET', '/v1/changes/70', None, None),
            ('GET', '/v1/changes/70', None, None),
            ('GET', '/v1/changes/70', None, None),
        ]

        assert time.time() == 2

    def test_wait_change_success_polled_timeout_none(self, client: MockClient, time: MockTime):
        self.test_wait_change_success_polled(client, time, timeout=None)

    def test_wait_change_timeout(self, client: MockClient, time: MockTime):
        def timeout_response(n: float):
            time.sleep(n)  # simulate passing of time due to wait_change call
            raise pebble.APIError({}, 504, 'Gateway Timeout', 'timed out')

        client.responses.append(lambda: timeout_response(4))
        client.responses.append(lambda: timeout_response(2))

        with pytest.raises(pebble.TimeoutError) as excinfo:
            client.wait_change(pebble.ChangeID('70'), timeout=6)
        assert isinstance(excinfo.value, pebble.Error)
        assert isinstance(excinfo.value, TimeoutError)

        assert client.requests == [
            ('GET', '/v1/changes/70/wait', {'timeout': '4.000s'}, None),
            ('GET', '/v1/changes/70/wait', {'timeout': '2.000s'}, None),
        ]

        assert time.time() == 6

    def test_wait_change_timeout_polled(self, client: MockClient, time: MockTime):
        # Trigger polled mode
        client.responses.append(pebble.APIError({}, 404, 'Not Found', 'not found'))

        change = build_mock_change_dict()
        change['ready'] = False
        for _ in range(3):
            client.responses.append({
                'result': change,
                'status': 'OK',
                'status-code': 200,
                'type': 'sync',
            })

        with pytest.raises(pebble.TimeoutError) as excinfo:
            client.wait_change(pebble.ChangeID('70'), timeout=3, delay=1)
        assert isinstance(excinfo.value, pebble.Error)
        assert isinstance(excinfo.value, TimeoutError)

        assert client.requests == [
            ('GET', '/v1/changes/70/wait', {'timeout': '3.000s'}, None),
            ('GET', '/v1/changes/70', None, None),
            ('GET', '/v1/changes/70', None, None),
            ('GET', '/v1/changes/70', None, None),
        ]

        assert time.time() == 3

    def test_wait_change_error(self, client: MockClient):
        change = build_mock_change_dict()
        change['err'] = 'Some kind of service error'
        client.responses.append({
            'result': change,
            'status': 'OK',
            'status-code': 200,
            'type': 'sync',
        })
        # wait_change() itself shouldn't raise an error
        response = client.wait_change(pebble.ChangeID('70'))
        assert response.id == '70'
        assert response.err == 'Some kind of service error'

        assert client.requests == [
            ('GET', '/v1/changes/70/wait', {'timeout': '4.000s'}, None),
        ]

    def test_wait_change_socket_timeout(self, client: MockClient, time: MockTime):
        def timeout_response(n: float):
            time.sleep(n)
            raise socket.timeout('socket.timeout: timed out')

        client.responses.append(lambda: timeout_response(3))

        with pytest.raises(pebble.TimeoutError) as excinfo:
            client.wait_change(pebble.ChangeID('70'), timeout=3)
        assert isinstance(excinfo.value, pebble.Error)
        assert isinstance(excinfo.value, TimeoutError)

    def test_add_layer(self, client: MockClient):
        okay_response = {'result': True, 'status': 'OK', 'status-code': 200, 'type': 'sync'}
        client.responses.append(okay_response)
        client.responses.append(okay_response)
        client.responses.append(okay_response)
        client.responses.append(okay_response)

        layer_yaml = """
services:
  foo:
    command: echo bar
    override: replace
"""[1:]
        layer = pebble.Layer(layer_yaml)

        client.add_layer('a', layer)
        client.add_layer('b', layer.to_yaml())
        client.add_layer('c', layer.to_dict())
        client.add_layer('d', layer, combine=True)

        def build_expected(label: str, combine: bool):
            return {
                'action': 'add',
                'combine': combine,
                'label': label,
                'format': 'yaml',
                'layer': layer_yaml,
            }

        assert client.requests == [
            ('POST', '/v1/layers', None, build_expected('a', False)),
            ('POST', '/v1/layers', None, build_expected('b', False)),
            ('POST', '/v1/layers', None, build_expected('c', False)),
            ('POST', '/v1/layers', None, build_expected('d', True)),
        ]

    def test_add_layer_invalid_type(self, client: MockClient):
        with pytest.raises(TypeError):
            client.add_layer('foo', 42)  # type: ignore
        with pytest.raises(TypeError):
            client.add_layer(42, 'foo')  # type: ignore

        # combine is a keyword-only arg (should be combine=True)
        with pytest.raises(TypeError):
            client.add_layer('foo', {}, True)  # type: ignore

    def test_get_plan(self, client: MockClient):
        plan_yaml = """
services:
  foo:
    command: echo bar
    override: replace
"""[1:]
        client.responses.append({
            'result': plan_yaml,
            'status': 'OK',
            'status-code': 200,
            'type': 'sync',
        })
        plan = client.get_plan()
        assert plan.to_yaml() == plan_yaml
        assert len(plan.services) == 1
        assert plan.services['foo'].command == 'echo bar'
        assert plan.services['foo'].override == 'replace'

        assert client.requests == [
            ('GET', '/v1/plan', {'format': 'yaml'}, None),
        ]

    def test_get_services_all(self, client: MockClient):
        client.responses.append({
            'result': [
                {'current': 'inactive', 'name': 'svc1', 'startup': 'disabled'},
                {'current': 'active', 'name': 'svc2', 'startup': 'enabled'},
            ],
            'status': 'OK',
            'status-code': 200,
            'type': 'sync',
        })
        services = client.get_services()
        assert len(services) == 2
        assert services[0].name == 'svc1'
        assert services[0].startup == pebble.ServiceStartup.DISABLED
        assert services[0].current == pebble.ServiceStatus.INACTIVE
        assert services[1].name == 'svc2'
        assert services[1].startup == pebble.ServiceStartup.ENABLED
        assert services[1].current == pebble.ServiceStatus.ACTIVE

        assert client.requests == [
            ('GET', '/v1/services', None, None),
        ]

    def test_get_services_names(self, client: MockClient):
        client.responses.append({
            'result': [
                {'current': 'inactive', 'name': 'svc1', 'startup': 'disabled'},
                {'current': 'active', 'name': 'svc2', 'startup': 'enabled'},
            ],
            'status': 'OK',
            'status-code': 200,
            'type': 'sync',
        })
        services = client.get_services(['svc1', 'svc2'])
        assert len(services) == 2
        assert services[0].name == 'svc1'
        assert services[0].startup == pebble.ServiceStartup.DISABLED
        assert services[0].current == pebble.ServiceStatus.INACTIVE
        assert services[1].name == 'svc2'
        assert services[1].startup == pebble.ServiceStartup.ENABLED
        assert services[1].current == pebble.ServiceStatus.ACTIVE

        client.responses.append({
            'result': [{'current': 'active', 'name': 'svc2', 'startup': 'enabled'}],
            'status': 'OK',
            'status-code': 200,
            'type': 'sync',
        })
        services = client.get_services(['svc2'])
        assert len(services) == 1
        assert services[0].name == 'svc2'
        assert services[0].startup == pebble.ServiceStartup.ENABLED
        assert services[0].current == pebble.ServiceStatus.ACTIVE

        assert client.requests == [
            ('GET', '/v1/services', {'names': 'svc1,svc2'}, None),
            ('GET', '/v1/services', {'names': 'svc2'}, None),
        ]

    def test_pull_boundary_spanning_chunk(self, client: MockClient):
        client.responses.append((
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

        client._chunk_size = 13
        with client.pull('/etc/hosts') as infile:
            content = infile.read()
        assert content == '127.0.0.1 localhost  # 😀\nfoo\r\nbar'

        assert client.requests == [
            (
                'GET',
                '/v1/files',
                {'action': 'read', 'path': '/etc/hosts'},
                {'Accept': 'multipart/form-data'},
                None,
            ),
        ]

    def test_pull_text(self, client: MockClient):
        client.responses.append((
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

        with client.pull('/etc/hosts') as infile:
            content = infile.read()
        assert content == '127.0.0.1 localhost  # 😀\nfoo\r\nbar'

        assert client.requests == [
            (
                'GET',
                '/v1/files',
                {'action': 'read', 'path': '/etc/hosts'},
                {'Accept': 'multipart/form-data'},
                None,
            ),
        ]

    def test_pull_binary(self, client: MockClient):
        client.responses.append((
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

        with client.pull('/etc/hosts', encoding=None) as infile:
            content = infile.read()
        assert content == b'127.0.0.1 localhost  # \xf0\x9f\x98\x80\nfoo\r\nbar'

        assert client.requests == [
            (
                'GET',
                '/v1/files',
                {'action': 'read', 'path': '/etc/hosts'},
                {'Accept': 'multipart/form-data'},
                None,
            ),
        ]

    def test_pull_path_error(self, client: MockClient):
        client.responses.append((
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

        with pytest.raises(pebble.PathError) as excinfo:
            client.pull('/etc/hosts')
        assert isinstance(excinfo.value, pebble.Error)
        assert excinfo.value.kind == 'not-found'
        assert excinfo.value.message == 'not found'

        assert client.requests == [
            (
                'GET',
                '/v1/files',
                {'action': 'read', 'path': '/etc/hosts'},
                {'Accept': 'multipart/form-data'},
                None,
            ),
        ]

    def test_pull_protocol_errors(self, client: MockClient):
        client.responses.append(({'Content-Type': 'c/t'}, b''))
        with pytest.raises(pebble.ProtocolError) as excinfo:
            client.pull('/etc/hosts')
        assert isinstance(excinfo.value, pebble.Error)
        assert str(excinfo.value) == "expected Content-Type 'multipart/form-data', got 'c/t'"

        client.responses.append(({'Content-Type': 'multipart/form-data'}, b''))
        with pytest.raises(pebble.ProtocolError) as excinfo:
            client.pull('/etc/hosts')
        assert str(excinfo.value) == "invalid boundary ''"

        client.responses.append((
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
        with pytest.raises(pebble.ProtocolError) as excinfo:
            client.pull('/etc/hosts')
        assert str(excinfo.value) == "path not expected: '/bad'"

        client.responses.append((
            {'Content-Type': 'multipart/form-data; boundary=01234567890123456789012345678901'},
            b"""\
--01234567890123456789012345678901\r
Content-Disposition: form-data; name="files"; filename="/etc/hosts"\r
\r
bad path\r
--01234567890123456789012345678901--\r
""",
        ))
        with pytest.raises(pebble.ProtocolError) as excinfo:
            client.pull('/etc/hosts')
        assert str(excinfo.value) == 'no "response" field in multipart body'

    def test_push_str(self, client: MockClient):
        self._test_push_str(client, 'content 😀\nfoo\r\nbar')

    def test_push_text(self, client: MockClient):
        self._test_push_str(client, io.StringIO('content 😀\nfoo\r\nbar'))

    def _test_push_str(self, client: MockClient, source: typing.Union[str, typing.IO[str]]):
        client.responses.append((
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

        client.push('/foo/bar', source)

        assert len(client.requests) == 1
        request = client.requests[0]
        assert request[:3] == ('POST', '/v1/files', None)

        headers, body = request[3:]

        content_type = headers['Content-Type']
        req, filename, content = self._parse_write_multipart(content_type, body)
        assert filename == '/foo/bar'
        assert content == b'content \xf0\x9f\x98\x80\nfoo\r\nbar'
        assert req == {
            'action': 'write',
            'files': [{'path': '/foo/bar'}],
        }

    def test_push_bytes(self, client: MockClient):
        self._test_push_bytes(client, b'content \xf0\x9f\x98\x80\nfoo\r\nbar')

    def test_push_binary(self, client: MockClient):
        self._test_push_bytes(client, io.BytesIO(b'content \xf0\x9f\x98\x80\nfoo\r\nbar'))

    def _test_push_bytes(self, client: MockClient, source: typing.Union[bytes, typing.IO[bytes]]):
        client.responses.append((
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

        client.push('/foo/bar', source)

        assert len(client.requests) == 1
        request = client.requests[0]
        assert request[:3] == ('POST', '/v1/files', None)

        headers, body = request[3:]
        content_type = headers['Content-Type']
        req, filename, content = self._parse_write_multipart(content_type, body)
        assert filename == '/foo/bar'
        assert content == b'content \xf0\x9f\x98\x80\nfoo\r\nbar'
        assert req == {
            'action': 'write',
            'files': [{'path': '/foo/bar'}],
        }

    def test_push_all_options(self, client: MockClient):
        client.responses.append((
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

        client.push(
            '/foo/bar',
            'content',
            make_dirs=True,
            permissions=0o600,
            user_id=12,
            user='bob',
            group_id=34,
            group='staff',
        )

        assert len(client.requests) == 1
        request = client.requests[0]
        assert request[:3] == ('POST', '/v1/files', None)

        headers, body = request[3:]
        content_type = headers['Content-Type']
        req, filename, content = self._parse_write_multipart(content_type, body)
        assert filename == '/foo/bar'
        assert content == b'content'
        assert req == {
            'action': 'write',
            'files': [
                {
                    'path': '/foo/bar',
                    'make-dirs': True,
                    'permissions': '600',
                    'user-id': 12,
                    'user': 'bob',
                    'group-id': 34,
                    'group': 'staff',
                }
            ],
        }

    def test_push_uid_gid(self, client: MockClient):
        client.responses.append((
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

        client.push('/foo/bar', 'content', user_id=12, group_id=34)

        assert len(client.requests) == 1
        request = client.requests[0]
        assert request[:3] == ('POST', '/v1/files', None)

        headers, body = request[3:]
        content_type = headers['Content-Type']
        req, filename, content = self._parse_write_multipart(content_type, body)
        assert filename == '/foo/bar'
        assert content == b'content'
        assert req == {
            'action': 'write',
            'files': [
                {
                    'path': '/foo/bar',
                    'user-id': 12,
                    'group-id': 34,
                }
            ],
        }

    def test_push_path_error(self, client: MockClient):
        client.responses.append((
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

        with pytest.raises(pebble.PathError) as excinfo:
            client.push('/foo/bar', 'content')
        assert excinfo.value.kind == 'not-found'
        assert excinfo.value.message == 'not found'

        assert len(client.requests) == 1
        request = client.requests[0]
        assert request[:3] == ('POST', '/v1/files', None)

        headers, body = request[3:]
        content_type = headers['Content-Type']
        req, filename, content = self._parse_write_multipart(content_type, body)
        assert filename == '/foo/bar'
        assert content == b'content'
        assert req == {
            'action': 'write',
            'files': [{'path': '/foo/bar'}],
        }

    def _parse_write_multipart(self, content_type: str, body: _bytes_generator):
        message = email.message.Message()
        message['Content-Type'] = content_type
        assert message.get_content_type() == 'multipart/form-data'
        boundary = message.get_param('boundary')
        assert isinstance(boundary, str)

        # We have to manually write the Content-Type with boundary, because
        # email.parser expects the entire multipart message with headers.
        parser = email.parser.BytesFeedParser()
        parser.feed(
            b'Content-Type: multipart/form-data; boundary='
            + boundary.encode('utf-8')
            + b'\r\n\r\n'
        )
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
                req = json.loads(typing.cast(str, part.get_payload()))
            elif name == 'files':
                # decode=True, ironically, avoids decoding bytes to str
                content = part.get_payload(decode=True)
                filename = part.get_filename()
        return (req, filename, content)

    def test_list_files_path(self, client: MockClient):
        client.responses.append({
            'result': [
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
        infos = client.list_files('/etc')

        assert len(infos) == 2
        assert infos[0].path == '/etc/hosts'
        assert infos[0].name == 'hosts'
        assert infos[0].type == pebble.FileType.FILE
        assert infos[0].size == 123
        assert infos[0].permissions == 0o644
        assert infos[0].last_modified == datetime_nzdt(2021, 1, 28, 14, 37, 4, 291518)
        assert infos[0].user_id == 12
        assert infos[0].user == 'bob'
        assert infos[0].group_id == 34
        assert infos[0].group == 'staff'
        assert infos[1].path == '/etc/nginx'
        assert infos[1].name == 'nginx'
        assert infos[1].type == pebble.FileType.DIRECTORY
        assert infos[1].size is None
        assert infos[1].permissions == 0o755
        assert infos[1].last_modified == datetime_nzdt(2020, 1, 1, 1, 1, 1, 0)
        assert infos[1].user_id is None
        assert infos[1].user is None
        assert infos[1].group_id is None
        assert infos[1].group is None

        assert client.requests == [
            ('GET', '/v1/files', {'action': 'list', 'path': '/etc'}, None),
        ]

    def test_list_files_pattern(self, client: MockClient):
        client.responses.append({
            'result': [],
            'status': 'OK',
            'status-code': 200,
            'type': 'sync',
        })

        infos = client.list_files('/etc', pattern='*.conf')

        assert len(infos) == 0
        assert client.requests == [
            ('GET', '/v1/files', {'action': 'list', 'path': '/etc', 'pattern': '*.conf'}, None),
        ]

    def test_list_files_itself(self, client: MockClient):
        client.responses.append({
            'result': [],
            'status': 'OK',
            'status-code': 200,
            'type': 'sync',
        })

        infos = client.list_files('/etc', itself=True)

        assert len(infos) == 0
        assert client.requests == [
            ('GET', '/v1/files', {'action': 'list', 'path': '/etc', 'itself': 'true'}, None),
        ]

    def test_make_dir_basic(self, client: MockClient):
        client.responses.append({
            'result': [{'path': '/foo/bar'}],
            'status': 'OK',
            'status-code': 200,
            'type': 'sync',
        })
        client.make_dir('/foo/bar')
        req = {
            'action': 'make-dirs',
            'dirs': [
                {
                    'path': '/foo/bar',
                }
            ],
        }
        assert client.requests == [
            ('POST', '/v1/files', None, req),
        ]

    def test_make_dir_all_options(self, client: MockClient):
        client.responses.append({
            'result': [{'path': '/foo/bar'}],
            'status': 'OK',
            'status-code': 200,
            'type': 'sync',
        })
        client.make_dir(
            '/foo/bar',
            make_parents=True,
            permissions=0o600,
            user_id=12,
            user='bob',
            group_id=34,
            group='staff',
        )

        req = {
            'action': 'make-dirs',
            'dirs': [
                {
                    'path': '/foo/bar',
                    'make-parents': True,
                    'permissions': '600',
                    'user-id': 12,
                    'user': 'bob',
                    'group-id': 34,
                    'group': 'staff',
                }
            ],
        }
        assert client.requests == [
            ('POST', '/v1/files', None, req),
        ]

    def test_make_dir_error(self, client: MockClient):
        client.responses.append({
            'result': [
                {
                    'path': '/foo/bar',
                    'error': {
                        'kind': 'permission-denied',
                        'message': 'permission denied',
                    },
                }
            ],
            'status': 'OK',
            'status-code': 200,
            'type': 'sync',
        })
        with pytest.raises(pebble.PathError) as excinfo:
            client.make_dir('/foo/bar')
        assert isinstance(excinfo.value, pebble.Error)
        assert excinfo.value.kind == 'permission-denied'
        assert excinfo.value.message == 'permission denied'

    def test_remove_path_basic(self, client: MockClient):
        client.responses.append({
            'result': [{'path': '/boo/far'}],
            'status': 'OK',
            'status-code': 200,
            'type': 'sync',
        })
        client.remove_path('/boo/far')
        req = {
            'action': 'remove',
            'paths': [
                {
                    'path': '/boo/far',
                }
            ],
        }
        assert client.requests == [
            ('POST', '/v1/files', None, req),
        ]

    def test_remove_path_recursive(self, client: MockClient):
        client.responses.append({
            'result': [{'path': '/boo/far'}],
            'status': 'OK',
            'status-code': 200,
            'type': 'sync',
        })
        client.remove_path('/boo/far', recursive=True)

        req = {
            'action': 'remove',
            'paths': [
                {
                    'path': '/boo/far',
                    'recursive': True,
                }
            ],
        }
        assert client.requests == [
            ('POST', '/v1/files', None, req),
        ]

    def test_remove_path_error(self, client: MockClient):
        client.responses.append({
            'result': [
                {
                    'path': '/boo/far',
                    'error': {
                        'kind': 'generic-file-error',
                        'message': 'some other error',
                    },
                }
            ],
            'status': 'OK',
            'status-code': 200,
            'type': 'sync',
        })
        with pytest.raises(pebble.PathError) as excinfo:
            client.remove_path('/boo/far')
        assert isinstance(excinfo.value, pebble.Error)
        assert excinfo.value.kind == 'generic-file-error'
        assert excinfo.value.message == 'some other error'

    def test_send_signal_name(self, client: MockClient):
        client.responses.append({
            'result': True,
            'status': 'OK',
            'status-code': 200,
            'type': 'sync',
        })

        client.send_signal('SIGHUP', ['s1', 's2'])

        assert client.requests == [
            ('POST', '/v1/signals', None, {'signal': 'SIGHUP', 'services': ['s1', 's2']}),
        ]

    @unittest.skipUnless(hasattr(signal, 'SIGHUP'), 'signal constants not present')
    def test_send_signal_number(self, client: MockClient):
        client.responses.append({
            'result': True,
            'status': 'OK',
            'status-code': 200,
            'type': 'sync',
        })

        client.send_signal(signal.SIGHUP, ['s1', 's2'])

        assert client.requests == [
            ('POST', '/v1/signals', None, {'signal': 'SIGHUP', 'services': ['s1', 's2']}),
        ]

    def test_send_signal_type_error(self, client: MockClient):
        with pytest.raises(TypeError):
            client.send_signal('SIGHUP', 'should-be-a-list')

        with pytest.raises(TypeError):
            client.send_signal('SIGHUP', [1, 2])  # type: ignore

    def test_get_checks_all(self, client: MockClient):
        client.responses.append({
            'result': [
                {
                    'name': 'chk1',
                    'status': 'up',
                    'threshold': 2,
                },
                {
                    'name': 'chk2',
                    'level': 'alive',
                    'status': 'down',
                    'failures': 5,
                    'threshold': 3,
                },
            ],
            'status': 'OK',
            'status-code': 200,
            'type': 'sync',
        })
        checks = client.get_checks()
        assert len(checks) == 2
        assert checks[0].name == 'chk1'
        assert checks[0].level == pebble.CheckLevel.UNSET
        assert checks[0].status == pebble.CheckStatus.UP
        assert checks[0].failures == 0
        assert checks[0].threshold == 2
        assert checks[1].name == 'chk2'
        assert checks[1].level == pebble.CheckLevel.ALIVE
        assert checks[1].status == pebble.CheckStatus.DOWN
        assert checks[1].failures == 5
        assert checks[1].threshold == 3

        assert client.requests == [
            ('GET', '/v1/checks', {}, None),
        ]

    def test_get_checks_filters(self, client: MockClient):
        client.responses.append({
            'result': [
                {
                    'name': 'chk2',
                    'level': 'ready',
                    'status': 'up',
                    'threshold': 3,
                },
            ],
            'status': 'OK',
            'status-code': 200,
            'type': 'sync',
        })
        checks = client.get_checks(level=pebble.CheckLevel.READY, names=['chk2'])
        assert len(checks) == 1
        assert checks[0].name == 'chk2'
        assert checks[0].level == pebble.CheckLevel.READY
        assert checks[0].status == pebble.CheckStatus.UP
        assert checks[0].failures == 0
        assert checks[0].threshold == 3

        assert client.requests == [
            ('GET', '/v1/checks', {'level': 'ready', 'names': ['chk2']}, None),
        ]

    def test_checklevel_conversion(self, client: MockClient):
        client.responses.append({
            'result': [
                {
                    'name': 'chk2',
                    'level': 'foobar!',
                    'status': 'up',
                    'threshold': 3,
                },
            ],
            'status': 'OK',
            'status-code': 200,
            'type': 'sync',
        })
        checks = client.get_checks(level=pebble.CheckLevel.READY, names=['chk2'])
        assert len(checks) == 1
        assert checks[0].name == 'chk2'
        assert checks[0].level == 'foobar!'  # stays a raw string
        assert checks[0].status == pebble.CheckStatus.UP
        assert checks[0].failures == 0
        assert checks[0].threshold == 3

        assert client.requests == [
            ('GET', '/v1/checks', {'level': 'ready', 'names': ['chk2']}, None),
        ]

    def test_notify_basic(self, client: MockClient):
        client.responses.append({
            'result': {
                'id': '123',
            },
            'status': 'OK',
            'status-code': 200,
            'type': 'sync',
        })

        notice_id = client.notify(pebble.NoticeType.CUSTOM, 'example.com/a')
        assert notice_id == '123'

        assert client.requests == [
            (
                'POST',
                '/v1/notices',
                None,
                {
                    'action': 'add',
                    'key': 'example.com/a',
                    'type': 'custom',
                },
            ),
        ]

    def test_notify_other_args(self, client: MockClient):
        client.responses.append({
            'result': {
                'id': '321',
            },
            'status': 'OK',
            'status-code': 200,
            'type': 'sync',
        })

        notice_id = client.notify(
            pebble.NoticeType.CUSTOM,
            'example.com/a',
            data={'k': 'v'},
            repeat_after=datetime.timedelta(hours=3),
        )
        assert notice_id == '321'

        assert client.requests == [
            (
                'POST',
                '/v1/notices',
                None,
                {
                    'action': 'add',
                    'key': 'example.com/a',
                    'type': 'custom',
                    'data': {'k': 'v'},
                    'repeat-after': '10800.000s',
                },
            ),
        ]

    def test_get_notice(self, client: MockClient):
        client.responses.append({
            'result': {
                'id': '123',
                'user-id': 1000,
                'type': 'custom',
                'key': 'example.com/a',
                'first-occurred': '2023-12-07T17:01:02.123456789Z',
                'last-occurred': '2023-12-07T17:01:03.123456789Z',
                'last-repeated': '2023-12-07T17:01:04.123456789Z',
                'occurrences': 7,
            },
            'status': 'OK',
            'status-code': 200,
            'type': 'sync',
        })

        notice = client.get_notice('123')

        # No need to re-test full Notice.from_dict behaviour.
        assert notice.id == '123'

        assert client.requests == [
            ('GET', '/v1/notices/123', None, None),
        ]

    def test_get_notice_not_found(self, client: MockClient):
        client.responses.append(pebble.APIError({}, 404, 'Not Found', 'not found'))

        with pytest.raises(pebble.APIError) as excinfo:
            client.get_notice('1')
        assert excinfo.value.code == 404

        assert client.requests == [
            ('GET', '/v1/notices/1', None, None),
        ]

    def test_get_notices_all(self, client: MockClient):
        client.responses.append({
            'result': [
                {
                    'id': '123',
                    'user-id': 1000,
                    'type': 'custom',
                    'key': 'example.com/a',
                    'first-occurred': '2023-12-07T17:01:02.123456789Z',
                    'last-occurred': '2023-12-07T17:01:03.123456789Z',
                    'last-repeated': '2023-12-07T17:01:04.123456789Z',
                    'occurrences': 7,
                },
                {
                    'id': '124',
                    'type': 'other',
                    'key': 'example.com/b',
                    'first-occurred': '2023-12-07T17:01:02.123456789Z',
                    'last-occurred': '2023-12-07T17:01:03.123456789Z',
                    'last-repeated': '2023-12-07T17:01:04.123456789Z',
                    'occurrences': 8,
                },
            ],
            'status': 'OK',
            'status-code': 200,
            'type': 'sync',
        })

        checks = client.get_notices()
        assert len(checks) == 2
        assert checks[0].id == '123'
        assert checks[1].id == '124'

        assert client.requests == [
            ('GET', '/v1/notices', {}, None),
        ]

    def test_get_notices_filters(self, client: MockClient):
        client.responses.append({
            'result': [
                {
                    'id': '123',
                    'user-id': 1000,
                    'type': 'custom',
                    'key': 'example.com/a',
                    'first-occurred': '2023-12-07T17:01:02.123456789Z',
                    'last-occurred': '2023-12-07T17:01:03.123456789Z',
                    'last-repeated': '2023-12-07T17:01:04.123456789Z',
                    'occurrences': 7,
                },
                {
                    'id': '124',
                    'type': 'other',
                    'key': 'example.com/b',
                    'first-occurred': '2023-12-07T17:01:02.123456789Z',
                    'last-occurred': '2023-12-07T17:01:03.123456789Z',
                    'last-repeated': '2023-12-07T17:01:04.123456789Z',
                    'occurrences': 8,
                },
            ],
            'status': 'OK',
            'status-code': 200,
            'type': 'sync',
        })

        notices = client.get_notices(
            user_id=1000,
            users=pebble.NoticesUsers.ALL,
            types=[pebble.NoticeType.CUSTOM],
            keys=['example.com/a', 'example.com/b'],
        )
        assert len(notices) == 2
        assert notices[0].id == '123'
        assert notices[1].id == '124'

        query = {
            'user-id': '1000',
            'users': 'all',
            'types': ['custom'],
            'keys': ['example.com/a', 'example.com/b'],
        }
        assert client.requests == [
            ('GET', '/v1/notices', query, None),
        ]


class TestSocketClient:
    def test_socket_not_found(self):
        client = pebble.Client(socket_path='does_not_exist')
        with pytest.raises(pebble.ConnectionError) as excinfo:
            client.get_system_info()
        assert isinstance(excinfo.value, pebble.Error)
        assert 'Could not connect to Pebble' in str(excinfo.value)

    def test_real_client(self):
        shutdown, socket_path = fake_pebble.start_server()

        try:
            client = pebble.Client(socket_path=socket_path)
            info = client.get_system_info()
            assert info.version == '3.14.159'

            change_id = client.start_services(['foo'], timeout=0)
            assert change_id == '1234'

            with pytest.raises(pebble.APIError) as excinfo:
                client.start_services(['bar'], timeout=0)
            assert isinstance(excinfo.value, pebble.Error)
            assert excinfo.value.code == 400
            assert excinfo.value.status == 'Bad Request'
            assert excinfo.value.message == 'service "bar" does not exist'

        finally:
            shutdown()


class TestExecError:
    def test_init(self):
        e = pebble.ExecError(['foo'], 42, 'out', 'err')
        assert e.command == ['foo']
        assert e.exit_code == 42
        assert e.stdout == 'out'
        assert e.stderr == 'err'

    def test_str(self):
        e = pebble.ExecError[str](['x'], 1, None, None)
        assert str(e) == "non-zero exit code 1 executing ['x']"

        e = pebble.ExecError(['x'], 1, 'only-out', None)
        assert str(e) == "non-zero exit code 1 executing ['x'], stdout='only-out'"

        e = pebble.ExecError(['x'], 1, None, 'only-err')
        assert str(e) == "non-zero exit code 1 executing ['x'], stderr='only-err'"

        e = pebble.ExecError(['a', 'b'], 1, 'out', 'err')
        assert (
            str(e) == "non-zero exit code 1 executing ['a', 'b'], " + "stdout='out', stderr='err'"
        )

    def test_str_truncated(self):
        e = pebble.ExecError(['foo'], 2, 'longout', 'longerr')
        e.STR_MAX_OUTPUT = 5  # type: ignore
        assert (
            str(e)
            == "non-zero exit code 2 executing ['foo'], "
            + "stdout='longo' [truncated], stderr='longe' [truncated]"
        )


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


class TestExec:
    def add_responses(
        self,
        client: MockClient,
        change_id: str,
        exit_code: int,
        change_err: typing.Optional[str] = None,
    ):
        task_id = f'T{change_id}'  # create a task_id based on change_id
        client.responses.append({
            'change': change_id,
            'result': {'task-id': task_id},
        })

        change = build_mock_change_dict(change_id)
        # pyright doesn't understand "assert change.get('tasks') is not None"
        assert 'tasks' in change and change['tasks'] is not None
        change['tasks'][0]['data'] = {'exit-code': exit_code}
        if change_err is not None:
            change['err'] = change_err
        client.responses.append({
            'result': change,
        })

        stdio = MockWebsocket()
        stderr = MockWebsocket()
        control = MockWebsocket()
        client.websockets = {
            (task_id, 'stdio'): stdio,
            (task_id, 'stderr'): stderr,
            (task_id, 'control'): control,
        }
        return (stdio, stderr, control)

    def build_exec_data(
        self,
        command: typing.List[str],
        service_context: typing.Optional[str] = None,
        environment: typing.Optional[typing.Dict[str, str]] = None,
        working_dir: typing.Optional[str] = None,
        timeout: typing.Optional[float] = None,
        user_id: typing.Optional[int] = None,
        user: typing.Optional[str] = None,
        group_id: typing.Optional[int] = None,
        group: typing.Optional[str] = None,
        combine_stderr: bool = False,
    ):
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

    def test_arg_errors(self, client: MockClient):
        with pytest.raises(TypeError):
            client.exec('foo')  # type: ignore
        with pytest.raises(ValueError):
            client.exec([])
        with pytest.raises(ValueError):
            client.exec(['foo'], stdin='s', encoding=None)  # type: ignore
        with pytest.raises(ValueError):
            client.exec(['foo'], stdin=b's')
        with pytest.raises(TypeError):
            client.exec(['foo'], stdin=123)  # type: ignore
        with pytest.raises(ValueError):
            client.exec(['foo'], stdout=io.StringIO(), stderr=io.StringIO(), combine_stderr=True)

    def test_no_wait_call(self, client: MockClient):
        self.add_responses(client, '123', 0)
        with pytest.warns(ResourceWarning) as record:
            process = client.exec(['true'])
            del process
        assert (
            str(record[0].message)
            == 'ExecProcess instance garbage collected without call to wait() or wait_output()'
        )

    def test_wait_exit_zero(self, client: MockClient):
        self.add_responses(client, '123', 0)

        process = client.exec(['true'])
        assert process.stdout is not None
        assert process.stderr is not None
        process.wait()

        assert client.requests == [
            ('POST', '/v1/exec', None, self.build_exec_data(['true'])),
            ('GET', '/v1/changes/123/wait', {'timeout': '4.000s'}, None),
        ]

    def test_wait_exit_nonzero(self, client: MockClient):
        self.add_responses(client, '456', 1)

        process = client.exec(['false'])
        excinfo: pytest.ExceptionInfo[pebble.ExecError[str]]
        with pytest.raises(pebble.ExecError) as excinfo:
            process.wait()
        assert excinfo.value.command == ['false']
        assert excinfo.value.exit_code == 1
        assert excinfo.value.stdout is None
        assert excinfo.value.stderr is None

        assert client.requests == [
            ('POST', '/v1/exec', None, self.build_exec_data(['false'])),
            ('GET', '/v1/changes/456/wait', {'timeout': '4.000s'}, None),
        ]

    def test_wait_timeout(self, client: MockClient):
        self.add_responses(client, '123', 0)

        process = client.exec(['true'], timeout=2)
        process.wait()

        assert client.requests == [
            ('POST', '/v1/exec', None, self.build_exec_data(['true'], timeout=2)),
            ('GET', '/v1/changes/123/wait', {'timeout': '3.000s'}, None),
        ]

    def test_wait_other_args(self, client: MockClient):
        self.add_responses(client, '123', 0)

        process = client.exec(
            ['true'],
            environment={'K1': 'V1', 'K2': 'V2'},
            working_dir='WD',
            user_id=1000,
            user='bob',
            group_id=1000,
            group='staff',
        )
        process.wait()

        assert client.requests == [
            (
                'POST',
                '/v1/exec',
                None,
                self.build_exec_data(
                    command=['true'],
                    environment={'K1': 'V1', 'K2': 'V2'},
                    working_dir='WD',
                    user_id=1000,
                    user='bob',
                    group_id=1000,
                    group='staff',
                ),
            ),
            ('GET', '/v1/changes/123/wait', {'timeout': '4.000s'}, None),
        ]

    def test_wait_change_error(self, client: MockClient):
        self.add_responses(client, '123', 0, change_err='change error!')

        process = client.exec(['true'])
        with pytest.raises(pebble.ChangeError) as excinfo:
            process.wait()
        assert excinfo.value.err == 'change error!'
        assert excinfo.value.change.id == '123'

        assert client.requests == [
            ('POST', '/v1/exec', None, self.build_exec_data(['true'])),
            ('GET', '/v1/changes/123/wait', {'timeout': '4.000s'}, None),
        ]

    def test_send_signal(self, client: MockClient):
        _, _, control = self.add_responses(client, '123', 0)

        process = client.exec(['server'])
        process.send_signal('SIGHUP')
        num_sends = 1
        if hasattr(signal, 'SIGHUP'):
            process.send_signal(1)
            process.send_signal(signal.SIGHUP)
            num_sends += 2

        process.wait()

        assert client.requests == [
            ('POST', '/v1/exec', None, self.build_exec_data(['server'])),
            ('GET', '/v1/changes/123/wait', {'timeout': '4.000s'}, None),
        ]

        assert len(control.sends) == num_sends
        assert control.sends[0][0] == 'TXT'
        assert json.loads(control.sends[0][1]) == {
            'command': 'signal',
            'signal': {'name': 'SIGHUP'},
        }
        if hasattr(signal, 'SIGHUP'):
            assert control.sends[1][0] == 'TXT'
            assert json.loads(control.sends[1][1]) == {
                'command': 'signal',
                'signal': {'name': signal.Signals(1).name},
            }
            assert control.sends[2][0] == 'TXT'
            assert json.loads(control.sends[2][1]) == {
                'command': 'signal',
                'signal': {'name': 'SIGHUP'},
            }

    def test_wait_output(self, client: MockClient):
        stdio, stderr, _ = self.add_responses(client, '123', 0)
        stdio.receives.append(b'Python 3.8.10\n')
        stdio.receives.append('{"command":"end"}')
        stderr.receives.append('{"command":"end"}')

        process = client.exec(['python3', '--version'])
        out, err = process.wait_output()
        assert out == 'Python 3.8.10\n'
        assert err == ''

        assert client.requests == [
            ('POST', '/v1/exec', None, self.build_exec_data(['python3', '--version'])),
            ('GET', '/v1/changes/123/wait', {'timeout': '4.000s'}, None),
        ]
        assert stdio.sends == []

    def test_wait_output_combine_stderr(self, client: MockClient):
        stdio, _, _ = self.add_responses(client, '123', 0)
        stdio.receives.append(b'invalid time interval\n')
        stdio.receives.append('{"command":"end"}')

        process = client.exec(['sleep', 'x'], combine_stderr=True)
        out, err = process.wait_output()
        assert out == 'invalid time interval\n'
        assert err is None
        assert process.stderr is None

        exec_data = self.build_exec_data(['sleep', 'x'], combine_stderr=True)
        assert client.requests == [
            ('POST', '/v1/exec', None, exec_data),
            ('GET', '/v1/changes/123/wait', {'timeout': '4.000s'}, None),
        ]
        assert stdio.sends == []

    def test_wait_output_bytes(self, client: MockClient):
        stdio, stderr, _ = self.add_responses(client, '123', 0)
        stdio.receives.append(b'Python 3.8.10\n')
        stdio.receives.append('{"command":"end"}')
        stderr.receives.append('{"command":"end"}')

        process = client.exec(['python3', '--version'], encoding=None)
        out, err = process.wait_output()
        assert out == b'Python 3.8.10\n'
        assert err == b''

        assert client.requests == [
            ('POST', '/v1/exec', None, self.build_exec_data(['python3', '--version'])),
            ('GET', '/v1/changes/123/wait', {'timeout': '4.000s'}, None),
        ]
        assert stdio.sends == []

    def test_wait_output_exit_nonzero(self, client: MockClient):
        stdio, stderr, _ = self.add_responses(client, '123', 0)
        stdio.receives.append('{"command":"end"}')
        stderr.receives.append(b'file not found: x\n')
        stderr.receives.append('{"command":"end"}')

        process = client.exec(['ls', 'x'])
        out, err = process.wait_output()
        assert out == ''
        assert err == 'file not found: x\n'

        assert client.requests == [
            ('POST', '/v1/exec', None, self.build_exec_data(['ls', 'x'])),
            ('GET', '/v1/changes/123/wait', {'timeout': '4.000s'}, None),
        ]
        assert stdio.sends == []

    def test_wait_output_exit_nonzero_combine_stderr(self, client: MockClient):
        stdio, _, _ = self.add_responses(client, '123', 0)
        stdio.receives.append(b'file not found: x\n')
        stdio.receives.append('{"command":"end"}')

        process = client.exec(['ls', 'x'], combine_stderr=True)
        out, err = process.wait_output()
        assert out == 'file not found: x\n'
        assert err is None

        exec_data = self.build_exec_data(['ls', 'x'], combine_stderr=True)
        assert client.requests == [
            ('POST', '/v1/exec', None, exec_data),
            ('GET', '/v1/changes/123/wait', {'timeout': '4.000s'}, None),
        ]
        assert stdio.sends == []

    def test_wait_output_send_stdin(self, client: MockClient):
        stdio, stderr, _ = self.add_responses(client, '123', 0)
        stdio.receives.append(b'FOO\nBAR\n')
        stdio.receives.append('{"command":"end"}')
        stderr.receives.append('{"command":"end"}')

        process = client.exec(['awk', '{ print toupper($) }'], stdin='foo\nbar\n')
        out, err = process.wait_output()
        assert out == 'FOO\nBAR\n'
        assert err == ''

        assert client.requests == [
            ('POST', '/v1/exec', None, self.build_exec_data(['awk', '{ print toupper($) }'])),
            ('GET', '/v1/changes/123/wait', {'timeout': '4.000s'}, None),
        ]
        assert stdio.sends == [
            ('BIN', b'foo\nbar\n'),
            ('TXT', '{"command":"end"}'),
        ]

    def test_wait_output_send_stdin_bytes(self, client: MockClient):
        stdio, stderr, _ = self.add_responses(client, '123', 0)
        stdio.receives.append(b'FOO\nBAR\n')
        stdio.receives.append('{"command":"end"}')
        stderr.receives.append('{"command":"end"}')

        process = client.exec(['awk', '{ print toupper($) }'], stdin=b'foo\nbar\n', encoding=None)
        out, err = process.wait_output()
        assert out == b'FOO\nBAR\n'
        assert err == b''

        assert client.requests == [
            ('POST', '/v1/exec', None, self.build_exec_data(['awk', '{ print toupper($) }'])),
            ('GET', '/v1/changes/123/wait', {'timeout': '4.000s'}, None),
        ]
        assert stdio.sends == [
            ('BIN', b'foo\nbar\n'),
            ('TXT', '{"command":"end"}'),
        ]

    def test_wait_output_no_stdout(self, client: MockClient):
        stdio, stderr, _ = self.add_responses(client, '123', 0)
        stdio.receives.append('{"command":"end"}')
        stderr.receives.append('{"command":"end"}')
        stdout_buffer = io.BytesIO()
        process = client.exec(['echo', 'FOOBAR'], stdout=stdout_buffer, encoding=None)
        with pytest.raises(TypeError):
            process.wait_output()

    def test_wait_output_bad_command(self, caplog: pytest.LogCaptureFixture, client: MockClient):
        stdio, stderr, _ = self.add_responses(client, '123', 0)
        stdio.receives.append(b'Python 3.8.10\n')
        stdio.receives.append('not json')  # bad JSON should be ignored
        stdio.receives.append('{"command":"foo"}')  # unknown command should be ignored
        stdio.receives.append('{"command":"end"}')
        stderr.receives.append('{"command":"end"}')

        with caplog.at_level(level='WARNING', logger='ops.pebble'):
            process = client.exec(['python3', '--version'])
            out, err = process.wait_output()
        expected = [
            'Cannot decode I/O command (invalid JSON)',
            "Invalid I/O command 'foo'",
        ]
        assert expected == [record.message for record in caplog.records]

        assert out == 'Python 3.8.10\n'
        assert err == ''

        assert client.requests == [
            ('POST', '/v1/exec', None, self.build_exec_data(['python3', '--version'])),
            ('GET', '/v1/changes/123/wait', {'timeout': '4.000s'}, None),
        ]
        assert stdio.sends == []

    def test_wait_passed_output(self, client: MockClient):
        io_ws, stderr, _ = self.add_responses(client, '123', 0)
        io_ws.receives.append(b'foo\n')
        io_ws.receives.append('{"command":"end"}')
        stderr.receives.append(b'some error\n')
        stderr.receives.append('{"command":"end"}')

        out = io.StringIO()
        err = io.StringIO()
        process = client.exec(['echo', 'foo'], stdout=out, stderr=err)
        process.wait()
        assert out.getvalue() == 'foo\n'
        assert err.getvalue() == 'some error\n'

        assert client.requests == [
            ('POST', '/v1/exec', None, self.build_exec_data(['echo', 'foo'])),
            ('GET', '/v1/changes/123/wait', {'timeout': '4.000s'}, None),
        ]
        assert io_ws.sends == []

    def test_wait_passed_output_combine_stderr(self, client: MockClient):
        io_ws, _, _ = self.add_responses(client, '123', 0)
        io_ws.receives.append(b'foo\n')
        io_ws.receives.append(b'some error\n')
        io_ws.receives.append('{"command":"end"}')

        out = io.StringIO()
        process = client.exec(['echo', 'foo'], stdout=out, combine_stderr=True)
        process.wait()
        assert out.getvalue() == 'foo\nsome error\n'
        assert process.stderr is None

        exec_data = self.build_exec_data(['echo', 'foo'], combine_stderr=True)
        assert client.requests == [
            ('POST', '/v1/exec', None, exec_data),
            ('GET', '/v1/changes/123/wait', {'timeout': '4.000s'}, None),
        ]
        assert io_ws.sends == []

    def test_wait_passed_output_bytes(self, client: MockClient):
        io_ws, stderr, _ = self.add_responses(client, '123', 0)
        io_ws.receives.append(b'foo\n')
        io_ws.receives.append('{"command":"end"}')
        stderr.receives.append(b'some error\n')
        stderr.receives.append('{"command":"end"}')

        out = io.BytesIO()
        err = io.BytesIO()
        process = client.exec(['echo', 'foo'], stdout=out, stderr=err, encoding=None)
        process.wait()
        assert out.getvalue() == b'foo\n'
        assert err.getvalue() == b'some error\n'

        assert client.requests == [
            ('POST', '/v1/exec', None, self.build_exec_data(['echo', 'foo'])),
            ('GET', '/v1/changes/123/wait', {'timeout': '4.000s'}, None),
        ]
        assert io_ws.sends == []

    def test_wait_passed_output_bad_command(
        self, caplog: pytest.LogCaptureFixture, client: MockClient
    ):
        io_ws, stderr, _ = self.add_responses(client, '123', 0)
        io_ws.receives.append(b'foo\n')
        io_ws.receives.append('not json')  # bad JSON should be ignored
        io_ws.receives.append('{"command":"foo"}')  # unknown command should be ignored
        io_ws.receives.append('{"command":"end"}')
        stderr.receives.append(b'some error\n')
        stderr.receives.append('{"command":"end"}')

        out = io.StringIO()
        err = io.StringIO()

        with caplog.at_level(level='WARNING', logger='ops.pebble'):
            process = client.exec(['echo', 'foo'], stdout=out, stderr=err)
            process.wait()
        expected = [
            'Cannot decode I/O command (invalid JSON)',
            "Invalid I/O command 'foo'",
        ]
        assert expected == [record.message for record in caplog.records]

        assert out.getvalue() == 'foo\n'
        assert err.getvalue() == 'some error\n'

        assert client.requests == [
            ('POST', '/v1/exec', None, self.build_exec_data(['echo', 'foo'])),
            ('GET', '/v1/changes/123/wait', {'timeout': '4.000s'}, None),
        ]
        assert io_ws.sends == []

    def test_wait_file_io(self, client: MockClient):
        fin = tempfile.TemporaryFile(mode='w+', encoding='utf-8')
        out = tempfile.TemporaryFile(mode='w+', encoding='utf-8')
        err = tempfile.TemporaryFile(mode='w+', encoding='utf-8')
        try:
            fin.write('foo\n')
            fin.seek(0)

            io_ws, stderr, _ = self.add_responses(client, '123', 0)
            io_ws.receives.append(b'foo\n')
            io_ws.receives.append('{"command":"end"}')
            stderr.receives.append(b'some error\n')
            stderr.receives.append('{"command":"end"}')

            process = client.exec(['echo', 'foo'], stdin=fin, stdout=out, stderr=err)
            process.wait()

            out.seek(0)
            assert out.read() == 'foo\n'
            err.seek(0)
            assert err.read() == 'some error\n'

            assert client.requests == [
                ('POST', '/v1/exec', None, self.build_exec_data(['echo', 'foo'])),
                ('GET', '/v1/changes/123/wait', {'timeout': '4.000s'}, None),
            ]
            assert io_ws.sends == [
                ('BIN', b'foo\n'),
                ('TXT', '{"command":"end"}'),
            ]
        finally:
            fin.close()
            out.close()
            err.close()

    def test_wait_returned_io(self, client: MockClient):
        stdio = self.add_responses(client, '123', 0)[0]
        stdio.receives.append(b'FOO BAR\n')
        stdio.receives.append(b'BAZZ\n')
        stdio.receives.append('{"command":"end"}')

        process = client.exec(['awk', '{ print toupper($) }'])
        assert process.stdout is not None and process.stdin is not None
        process.stdin.write('Foo Bar\n')
        assert process.stdout.read(4) == 'FOO '
        process.stdin.write('bazz\n')
        assert process.stdout.read() == 'BAR\nBAZZ\n'
        process.stdin.close()
        assert process.stdout.read() == ''
        process.wait()

        assert client.requests == [
            ('POST', '/v1/exec', None, self.build_exec_data(['awk', '{ print toupper($) }'])),
            ('GET', '/v1/changes/123/wait', {'timeout': '4.000s'}, None),
        ]
        assert stdio.sends == [
            ('BIN', b'Foo Bar\nbazz\n'),  # TextIOWrapper groups the writes together
            ('TXT', '{"command":"end"}'),
        ]

    def test_wait_returned_io_bytes(self, client: MockClient):
        stdio = self.add_responses(client, '123', 0)[0]
        stdio.receives.append(b'FOO BAR\n')
        stdio.receives.append(b'BAZZ\n')
        stdio.receives.append('{"command":"end"}')

        process = client.exec(['awk', '{ print toupper($) }'], encoding=None)
        assert process.stdout is not None and process.stdin is not None
        process.stdin.write(b'Foo Bar\n')
        assert process.stdout.read(4) == b'FOO '
        assert process.stdout.read() == b'BAR\n'
        process.stdin.write(b'bazz\n')
        assert process.stdout.read() == b'BAZZ\n'
        process.stdin.close()
        assert process.stdout.read() == b''
        process.wait()

        assert client.requests == [
            ('POST', '/v1/exec', None, self.build_exec_data(['awk', '{ print toupper($) }'])),
            ('GET', '/v1/changes/123/wait', {'timeout': '4.000s'}, None),
        ]
        assert stdio.sends == [
            ('BIN', b'Foo Bar\n'),
            ('BIN', b'bazz\n'),
            ('TXT', '{"command":"end"}'),
        ]

    def test_connect_websocket_error(self):
        class Client(MockClient):
            def _connect_websocket(self, change_id: str, websocket_id: str):
                raise websocket.WebSocketException('conn!')

        client = Client()
        self.add_responses(client, '123', 0, change_err='change error!')
        with pytest.raises(pebble.ChangeError) as excinfo:
            client.exec(['foo'])
        assert str(excinfo.value) == 'change error!'

        client = Client()
        self.add_responses(client, '123', 0)
        with pytest.raises(pebble.ConnectionError) as excinfo:
            client.exec(['foo'])
        assert str(excinfo.value) in 'unexpected error connecting to websockets: conn!'

    def test_websocket_send_raises(self, client: MockClient):
        stdio, stderr, _ = self.add_responses(client, '123', 0)
        raised = False

        def send_binary(b: bytes):
            nonlocal raised
            raised = True
            raise Exception('a simulated error!')

        stdio.send_binary = send_binary
        stdio.receives.append('{"command":"end"}')
        stderr.receives.append('{"command":"end"}')

        process = client.exec(['cat'], stdin='foo\nbar\n')
        out, err = process.wait_output()
        assert out == ''
        assert err == ''
        assert raised

        assert client.requests == [
            ('POST', '/v1/exec', None, self.build_exec_data(['cat'])),
            ('GET', '/v1/changes/123/wait', {'timeout': '4.000s'}, None),
        ]
        assert stdio.sends == []

    # You'd normally use pytest.mark.filterwarnings as a decorator, but
    # PytestUnhandledThreadExceptionWarning isn't present on older Python versions.
    if hasattr(pytest, 'PytestUnhandledThreadExceptionWarning'):
        test_websocket_send_raises = pytest.mark.filterwarnings(
            'ignore::pytest.PytestUnhandledThreadExceptionWarning'
        )(test_websocket_send_raises)

    def test_websocket_recv_raises(self, client: MockClient):
        stdio, stderr, _ = self.add_responses(client, '123', 0)
        raised = False

        def recv():
            nonlocal raised
            raised = True
            raise Exception('a simulated error!')

        stdio.recv = recv
        stderr.receives.append('{"command":"end"}')

        process = client.exec(['cat'], stdin='foo\nbar\n')
        out, err = process.wait_output()
        assert out == ''
        assert err == ''
        assert raised

        assert client.requests == [
            ('POST', '/v1/exec', None, self.build_exec_data(['cat'])),
            ('GET', '/v1/changes/123/wait', {'timeout': '4.000s'}, None),
        ]
        assert stdio.sends == [
            ('BIN', b'foo\nbar\n'),
            ('TXT', '{"command":"end"}'),
        ]

    if hasattr(pytest, 'PytestUnhandledThreadExceptionWarning'):
        test_websocket_recv_raises = pytest.mark.filterwarnings(
            'ignore::pytest.PytestUnhandledThreadExceptionWarning'
        )(test_websocket_recv_raises)
