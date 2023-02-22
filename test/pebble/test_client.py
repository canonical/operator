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

import cgi
import email.parser
import io
import json
import signal
import unittest
import unittest.mock
import unittest.util

import ops.pebble as pebble

from . import fake_pebble
from .common import MockClient, MockTime, build_mock_change_dict, datetime_nzdt

# Ensure unittest diffs don't get truncated like "[17 chars]"
unittest.util._MAX_LENGTH = 1000


class TestMultipartParser(unittest.TestCase):
    class _Case:
        def __init__(
                self,
                name,
                data,
                want_headers,
                want_bodies,
                want_bodies_done,
                max_boundary=14,
                max_lookahead=8 * 1024,
                error=''):
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
                headers = []
                bodies = []
                bodies_done = []

                def handle_header(data):
                    headers.append(bytes(data))
                    bodies.append(b'')
                    bodies_done.append(False)

                def handle_body(data, done=False):
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
                        self.fail('unexpected error:', err)
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
        change = self.client.get_change('70')
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

    def test_replan_services(self):
        self._services_action_helper('replan', self.client.replan_services, [])

    def test_replan_services_async(self):
        self._services_action_async_helper('replan', self.client.replan_services, [])

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

    def test_restart_services(self):
        def api_func():
            return self.client.restart_services(['svc'])
        self._services_action_helper('restart', api_func, ['svc'])

        with self.assertRaises(TypeError):
            self.client.restart_services(1)

        with self.assertRaises(TypeError):
            self.client.restart_services([1])

        with self.assertRaises(TypeError):
            self.client.restart_services([['foo']])

    def test_restart_services_async(self):
        def api_func(timeout=30):
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

    def test_wait_change_success(self, timeout=30.0):
        change = build_mock_change_dict()
        self.client.responses.append({
            "result": change,
            "status": "OK",
            "status-code": 200,
            "type": "sync"
        })

        response = self.client.wait_change('70', timeout=timeout)
        self.assertEqual(response.id, '70')
        self.assertTrue(response.ready)

        self.assertEqual(self.client.requests, [
            ('GET', '/v1/changes/70/wait', {'timeout': '4.000s'}, None),
        ])

    def test_wait_change_success_timeout_none(self):
        self.test_wait_change_success(timeout=None)

    def test_wait_change_success_multiple_calls(self):
        def timeout_response(n):
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

        response = self.client.wait_change('70')
        self.assertEqual(response.id, '70')
        self.assertTrue(response.ready)

        self.assertEqual(self.client.requests, [
            ('GET', '/v1/changes/70/wait', {'timeout': '4.000s'}, None),
            ('GET', '/v1/changes/70/wait', {'timeout': '4.000s'}, None),
        ])

        self.assertEqual(self.time.time(), 4)

    def test_wait_change_success_polled(self, timeout=30.0):
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

        response = self.client.wait_change('70', timeout=timeout, delay=1)
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
        def timeout_response(n):
            self.time.sleep(n)  # simulate passing of time due to wait_change call
            raise pebble.APIError({}, 504, "Gateway Timeout", "timed out")

        self.client.responses.append(lambda: timeout_response(4))
        self.client.responses.append(lambda: timeout_response(2))

        with self.assertRaises(pebble.TimeoutError) as cm:
            self.client.wait_change('70', timeout=6)
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
            self.client.wait_change('70', timeout=3, delay=1)
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
        response = self.client.wait_change('70')
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

        # combine is a keyword-only arg (should be combine=True)
        with self.assertRaises(TypeError):
            self.client.add_layer('foo', {}, True)

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
        self.client.responses.append(({'Content-Type': 'ct'}, b''))
        with self.assertRaises(pebble.ProtocolError) as cm:
            self.client.pull('/etc/hosts')
        self.assertIsInstance(cm.exception, pebble.Error)
        self.assertEqual(str(cm.exception),
                         "expected Content-Type 'multipart/form-data', got 'ct'")

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

    def _test_push_str(self, source):
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

    def _test_push_bytes(self, source):
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

    def _parse_write_multipart(self, content_type, body):
        ctype, options = cgi.parse_header(content_type)
        self.assertEqual(ctype, 'multipart/form-data')
        boundary = options['boundary']

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
            self.client.send_signal('SIGHUP', [1, 2])

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
