#!/usr/bin/python3
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
import unittest
import unittest.mock
import unittest.util
import sys

import ops.pebble as pebble
import test.fake_pebble as fake_pebble


# Ensure unittest diffs don't get truncated like "[17 chars]"
unittest.util._MAX_LENGTH = 1000


def datetime_utc(y, m, d, hour, min, sec, micro=0):
    tz = datetime.timezone.utc
    return datetime.datetime(y, m, d, hour, min, sec, micro, tzinfo=tz)


def datetime_nzdt(y, m, d, hour, min, sec, micro=0):
    tz = datetime.timezone(datetime.timedelta(hours=13))
    return datetime.datetime(y, m, d, hour, min, sec, micro, tzinfo=tz)


class TestHelpers(unittest.TestCase):
    def test_parse_timestamp(self):
        self.assertEqual(pebble._parse_timestamp('2020-12-25T13:45:50+13:00'),
                         datetime_nzdt(2020, 12, 25, 13, 45, 50, 0))

        self.assertEqual(pebble._parse_timestamp('2020-12-25T13:45:50.123456789+13:00'),
                         datetime_nzdt(2020, 12, 25, 13, 45, 50, 123457))

        self.assertEqual(pebble._parse_timestamp('2021-02-10T04:36:22Z'),
                         datetime_utc(2021, 2, 10, 4, 36, 22, 0))

        self.assertEqual(pebble._parse_timestamp('2021-02-10t04:36:22z'),
                         datetime_utc(2021, 2, 10, 4, 36, 22, 0))

        self.assertEqual(pebble._parse_timestamp('2021-02-10T04:36:22.118970777Z'),
                         datetime_utc(2021, 2, 10, 4, 36, 22, 118971))

        self.assertEqual(pebble._parse_timestamp('2020-12-25T13:45:50.123456789+00:00'),
                         datetime_utc(2020, 12, 25, 13, 45, 50, 123457))

        tzinfo = datetime.timezone(datetime.timedelta(hours=-11, minutes=-30))
        self.assertEqual(pebble._parse_timestamp('2020-12-25T13:45:50.123456789-11:30'),
                         datetime.datetime(2020, 12, 25, 13, 45, 50, 123457, tzinfo=tzinfo))

        tzinfo = datetime.timezone(datetime.timedelta(hours=4))
        self.assertEqual(pebble._parse_timestamp('2000-01-02T03:04:05.006000+04:00'),
                         datetime.datetime(2000, 1, 2, 3, 4, 5, 6000, tzinfo=tzinfo))

        with self.assertRaises(ValueError):
            pebble._parse_timestamp('')

        with self.assertRaises(ValueError):
            pebble._parse_timestamp('foobar')

        with self.assertRaises(ValueError):
            pebble._parse_timestamp('2021-99-99T04:36:22Z')

        with self.assertRaises(ValueError):
            pebble._parse_timestamp(pebble._parse_timestamp('2021-02-10T04:36:22.118970777x'))

        with self.assertRaises(ValueError):
            pebble._parse_timestamp(pebble._parse_timestamp('2021-02-10T04:36:22.118970777-99:99'))


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
            err=None,
            spawn_time=datetime.datetime.now(),
            ready_time=datetime.datetime.now(),
        )
        error = pebble.ChangeError('Some error', change)
        self.assertIsInstance(error, pebble.Error)
        self.assertEqual(error.err, 'Some error')
        self.assertEqual(error.change, change)
        self.assertEqual(str(error), 'Some error')

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

        d['ready-time'] = '2021-01-28T14:37:04.291517768+00:00'
        d['spawn-time'] = '2021-01-28T14:37:02.247202105+00:00'
        change = pebble.Change.from_dict(d)
        self.assertEqual(change.ready_time, datetime_utc(2021, 1, 28, 14, 37, 4, 291518))
        self.assertEqual(change.spawn_time, datetime_utc(2021, 1, 28, 14, 37, 2, 247202))


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

        yaml = """description: The quick brown fox!
services:
  bar:
    command: echo bar
    summary: Bar
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

        self.assertEqual(s.to_yaml(), yaml)
        self.assertEqual(str(s), yaml)


class TestService(unittest.TestCase):
    def _assert_empty(self, service, name):
        self.assertEqual(service.name, name)
        self.assertEqual(service.summary, '')
        self.assertEqual(service.description, '')
        self.assertEqual(service.default, '')
        self.assertEqual(service.override, '')
        self.assertEqual(service.command, '')
        self.assertEqual(service.after, [])
        self.assertEqual(service.before, [])
        self.assertEqual(service.requires, [])
        self.assertEqual(service.environment, {})
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
            'default': 'Dee Fault',
            'override': 'override',
            'command': 'echo sum mary',
            'after': ['a1', 'a2'],
            'before': ['b1', 'b2'],
            'requires': ['r1', 'r2'],
            'environment': {'k1': 'v1', 'k2': 'v2'},
        }
        s = pebble.Service('Name 2', d)
        self.assertEqual(s.name, 'Name 2')
        self.assertEqual(s.description, 'The lazy quick brown')
        self.assertEqual(s.default, 'Dee Fault')
        self.assertEqual(s.override, 'override')
        self.assertEqual(s.command, 'echo sum mary')
        self.assertEqual(s.after, ['a1', 'a2'])
        self.assertEqual(s.before, ['b1', 'b2'])
        self.assertEqual(s.requires, ['r1', 'r2'])
        self.assertEqual(s.environment, {'k1': 'v1', 'k2': 'v2'})

        self.assertEqual(s.to_dict(), d)

        # Ensure pebble.Service has made copies of mutable objects
        s.after.append('a3')
        s.before.append('b3')
        s.requires.append('r3')
        s.environment['k3'] = 'v3'
        self.assertEqual(s.after, ['a1', 'a2', 'a3'])
        self.assertEqual(s.before, ['b1', 'b2', 'b3'])
        self.assertEqual(s.requires, ['r1', 'r2', 'r3'])
        self.assertEqual(s.environment, {'k1': 'v1', 'k2': 'v2', 'k3': 'v3'})
        self.assertEqual(d['after'], ['a1', 'a2'])
        self.assertEqual(d['before'], ['b1', 'b2'])
        self.assertEqual(d['requires'], ['r1', 'r2'])
        self.assertEqual(d['environment'], {'k1': 'v1', 'k2': 'v2'})


class MockClient(pebble.Client):
    """Mock Pebble client that simply records reqeusts and returns stored responses."""

    def __init__(self):
        self.requests = []
        self.responses = []

    def _request(self, method, path, query=None, body=None):
        self.requests.append((method, path, query, body))
        return self.responses.pop(0)


class MockTime:
    """Mocked versions of time.time() and time.sleep().

    MockTime.sleep() advances the clock and MockTime.time() returns the current time.
    """

    def __init__(self):
        self._time = 0

    def time(self):
        return self._time

    def sleep(self, delay):
        self._time += delay


class TestClient(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.client = MockClient()

    def test_client_init(self):
        pebble.Client(socket_path='foo')  # test that constructor runs
        with self.assertRaises(ValueError):
            pebble.Client()  # socket_path arg required

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
        empty = {
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

    def build_mock_change_dict(self):
        return {
            "id": "70",
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
                        "extra-field": "foo",
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

    def assert_mock_change(self, change):
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
        empty = {
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
                self.build_mock_change_dict(),
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
            "result": self.build_mock_change_dict(),
            "status": "OK",
            "status-code": 200,
            "type": "sync"
        })
        change = self.client.get_change('70')
        self.assert_mock_change(change)
        self.assertEqual(self.client.requests, [
            ('GET', '/v1/changes/70', None, None),
        ])

    def test_abort_change(self):
        self.client.responses.append({
            "result": self.build_mock_change_dict(),
            "status": "OK",
            "status-code": 200,
            "type": "sync"
        })
        change = self.client.abort_change('70')
        self.assert_mock_change(change)
        self.assertEqual(self.client.requests, [
            ('POST', '/v1/changes/70', None, {'action': 'abort'}),
        ])

    def _services_action_helper(self, action, api_func, services):
        self.client.responses.append({
            "change": "70",
            "result": None,
            "status": "Accepted",
            "status-code": 202,
            "type": "async"
        })
        change = self.build_mock_change_dict()
        change['ready'] = False
        self.client.responses.append({
            "result": change,
            "status": "OK",
            "status-code": 200,
            "type": "sync"
        })
        change = self.build_mock_change_dict()
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
            ('GET', '/v1/changes/70', None, None),
            ('GET', '/v1/changes/70', None, None),
        ])

    def _services_action_async_helper(self, action, api_func, services):
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

    def test_start_services(self):
        def api_func():
            return self.client.start_services(['svc'])
        self._services_action_helper('start', api_func, ['svc'])

        with self.assertRaises(TypeError):
            self.client.start_services(1)

        with self.assertRaises(TypeError):
            self.client.start_services([1])

        with self.assertRaises(TypeError):
            self.client.start_services([['foo']])

    def test_start_services_async(self):
        def api_func(timeout=30):
            return self.client.start_services(['svc'], timeout=timeout)
        self._services_action_async_helper('start', api_func, ['svc'])

    def test_stop_services(self):
        def api_func():
            return self.client.stop_services(['svc'])
        self._services_action_helper('stop', api_func, ['svc'])

        with self.assertRaises(TypeError):
            self.client.stop_services(1)

        with self.assertRaises(TypeError):
            self.client.stop_services([1])

        with self.assertRaises(TypeError):
            self.client.stop_services([['foo']])

    def test_stop_services_async(self):
        def api_func(timeout=30):
            return self.client.stop_services(['svc'], timeout=timeout)
        self._services_action_async_helper('stop', api_func, ['svc'])

    def test_change_error(self):
        self.client.responses.append({
            "change": "70",
            "result": None,
            "status": "Accepted",
            "status-code": 202,
            "type": "async"
        })
        change = self.build_mock_change_dict()
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
            ('GET', '/v1/changes/70', None, None),
        ])

    def test_wait_change_timeout(self):
        with unittest.mock.patch('ops.pebble.time', MockTime()):
            change = self.build_mock_change_dict()
            change['ready'] = False
            for _ in range(3):
                self.client.responses.append({
                    "result": change,
                    "status": "OK",
                    "status-code": 200,
                    "type": "sync"
                })

            with self.assertRaises(pebble.TimeoutError) as cm:
                self.client.wait_change('70', timeout=3, delay=1)
            self.assertIsInstance(cm.exception, pebble.Error)
            self.assertIsInstance(cm.exception, TimeoutError)

            self.assertEqual(self.client.requests, [
                ('GET', '/v1/changes/70', None, None),
                ('GET', '/v1/changes/70', None, None),
                ('GET', '/v1/changes/70', None, None),
            ])

    def test_wait_change_error(self):
        change = self.build_mock_change_dict()
        change['err'] = 'Some kind of service error'
        self.client.responses.append({
            "result": change,
            "status": "OK",
            "status-code": 200,
            "type": "sync"
        })
        # wait_change() itself shouldn't raise an error
        response = self.client.wait_change('70')
        self.assertEqual(response.id, '70')
        self.assertEqual(response.err, 'Some kind of service error')

        self.assertEqual(self.client.requests, [
            ('GET', '/v1/changes/70', None, None),
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

        def build_expected(label, combine):
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
            self.client.add_layer('foo', 42)
        with self.assertRaises(TypeError):
            self.client.add_layer(42, 'foo')

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
        self.assertEqual(plan.raw_yaml, plan_yaml)
        self.assertEqual(len(plan.services), 1)
        self.assertEqual(plan.services['foo'].command, 'echo bar')
        self.assertEqual(plan.services['foo'].override, 'replace')

        self.assertEqual(self.client.requests, [
            ('GET', '/v1/plan', {'format': 'yaml'}, None),
        ])


class TestSocketClient(unittest.TestCase):
    @unittest.skipIf(sys.platform == 'win32', "Unix sockets don't work on Windows")
    def test_socket_not_found(self):
        client = pebble.Client(socket_path='does_not_exist')
        with self.assertRaises(pebble.ConnectionError) as cm:
            client.get_system_info()
        self.assertIsInstance(cm.exception, pebble.Error)

    @unittest.skipIf(sys.platform == 'win32', "Unix sockets don't work on Windows")
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
