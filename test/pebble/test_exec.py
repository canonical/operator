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

import io
import json
import signal
import tempfile
import unittest

import pytest
import websocket

from ops import pebble

from .common import MockClient, MockTime, build_mock_change_dict


class TestExecError(unittest.TestCase):
    def test_init(self):
        e = pebble.ExecError(['foo'], 42, 'out', 'err')
        self.assertEqual(e.command, ['foo'])
        self.assertEqual(e.exit_code, 42)
        self.assertEqual(e.stdout, 'out')
        self.assertEqual(e.stderr, 'err')

    def test_str(self):
        e = pebble.ExecError(['x'], 1, None, None)
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
        e.STR_MAX_OUTPUT = 5
        self.assertEqual(str(e), "non-zero exit code 2 executing ['foo'], "
                         + "stdout='longo' [truncated], stderr='longe' [truncated]")


class MockWebsocket:
    def __init__(self):
        self.sends = []
        self.receives = []

    def send_binary(self, b):
        self.sends.append(('BIN', b))

    def send(self, s):
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

    def add_responses(self, change_id, exit_code, change_err=None):
        task_id = f"T{change_id}"  # create a task_id based on change_id
        self.client.responses.append({
            'change': change_id,
            'result': {'task-id': task_id},
        })

        change = build_mock_change_dict(change_id)
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

    def build_exec_data(
            self, command, environment=None, working_dir=None, timeout=None,
            user_id=None, user=None, group_id=None, group=None, combine_stderr=False):
        return {
            'command': command,
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
            self.client.exec('foo')
        with self.assertRaises(ValueError):
            self.client.exec([])
        with self.assertRaises(ValueError):
            self.client.exec(['foo'], stdin='s', encoding=None)
        with self.assertRaises(ValueError):
            self.client.exec(['foo'], stdin=b's')
        with self.assertRaises(TypeError):
            self.client.exec(['foo'], stdin=123)
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
        stdio, stderr, _ = self.add_responses('123', 0)
        stdio.receives.append(b'FOO BAR\n')
        stdio.receives.append(b'BAZZ\n')
        stdio.receives.append('{"command":"end"}')

        process = self.client.exec(['awk', '{ print toupper($) }'])
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
        stdio, stderr, _ = self.add_responses('123', 0)
        stdio.receives.append(b'FOO BAR\n')
        stdio.receives.append(b'BAZZ\n')
        stdio.receives.append('{"command":"end"}')

        process = self.client.exec(['awk', '{ print toupper($) }'], encoding=None)
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
            def _connect_websocket(self, change_id, websocket_id):
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

        def send_binary(b):
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
