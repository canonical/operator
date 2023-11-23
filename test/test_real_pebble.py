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

import json
import os
import shutil
import tempfile
import threading
import time
import typing
import unittest
import urllib.error
import urllib.request
import uuid

from ops import pebble

from .test_testing import PebbleStorageAPIsTestMixin


# Set the RUN_REAL_PEBBLE_TESTS environment variable to run these tests
# against a real Pebble server. For example, in one terminal, run Pebble:
#
# $ PEBBLE=~/pebble pebble run --http=:4000
# 2021-09-20T04:10:34.934Z [pebble] Started daemon
#
# In another terminal, run the tests:
#
# $ source .tox/unit/bin/activate
# $ RUN_REAL_PEBBLE_TESTS=1 PEBBLE=~/pebble pytest test/test_real_pebble.py -v
# $ deactivate
#
@unittest.skipUnless(os.getenv('RUN_REAL_PEBBLE_TESTS'), 'RUN_REAL_PEBBLE_TESTS not set')
class TestRealPebble(unittest.TestCase):
    def setUp(self):
        socket_path = os.getenv('PEBBLE_SOCKET')
        pebble_path = os.getenv('PEBBLE')
        if not socket_path and pebble_path:
            assert isinstance(pebble_path, str)
            socket_path = os.path.join(pebble_path, '.pebble.socket')
        assert socket_path, 'PEBBLE or PEBBLE_SOCKET must be set if RUN_REAL_PEBBLE_TESTS set'

        self.client = pebble.Client(socket_path=socket_path)

    def test_checks_and_health(self):
        self.client.add_layer('layer', {
            'checks': {
                'bad': {
                    'override': 'replace',
                    'level': 'ready',
                    'period': '50ms',
                    'threshold': 2,
                    'exec': {
                        'command': 'sleep x',
                    },
                },
                'good': {
                    'override': 'replace',
                    'level': 'alive',
                    'period': '50ms',
                    'exec': {
                        'command': 'echo foo',
                    },
                },
                'other': {
                    'override': 'replace',
                    'exec': {
                        'command': 'echo bar',
                    },
                },
            },
        }, combine=True)

        # Checks should all be "up" initially
        checks = self.client.get_checks()
        self.assertEqual(len(checks), 3)
        self.assertEqual(checks[0].name, 'bad')
        self.assertEqual(checks[0].level, pebble.CheckLevel.READY)
        self.assertEqual(checks[0].status, pebble.CheckStatus.UP)
        self.assertEqual(checks[1].name, 'good')
        self.assertEqual(checks[1].level, pebble.CheckLevel.ALIVE)
        self.assertEqual(checks[1].status, pebble.CheckStatus.UP)
        self.assertEqual(checks[2].name, 'other')
        self.assertEqual(checks[2].level, pebble.CheckLevel.UNSET)
        self.assertEqual(checks[2].status, pebble.CheckStatus.UP)

        # And /v1/health should return "healthy"
        health = self._get_health()
        self.assertEqual(health, {
            'result': {'healthy': True},
            'status': 'OK',
            'status-code': 200,
            'type': 'sync',
        })

        # After two retries the "bad" check should go down
        for _ in range(5):
            checks = self.client.get_checks()
            bad_check = [c for c in checks if c.name == 'bad'][0]
            if bad_check.status == pebble.CheckStatus.DOWN:
                break
            time.sleep(0.06)
        else:
            assert False, 'timed out waiting for "bad" check to go down'
        self.assertEqual(bad_check.failures, 2)
        self.assertEqual(bad_check.threshold, 2)
        good_check = [c for c in checks if c.name == 'good'][0]
        self.assertEqual(good_check.status, pebble.CheckStatus.UP)

        # And /v1/health should return "unhealthy" (with status HTTP 502)
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self._get_health()
        self.assertEqual(cm.exception.code, 502)
        health = json.loads(cm.exception.read())
        self.assertEqual(health, {
            'result': {'healthy': False},
            'status': 'Bad Gateway',
            'status-code': 502,
            'type': 'sync',
        })

        # Then test filtering by check level and by name
        checks = self.client.get_checks(level=pebble.CheckLevel.ALIVE)
        self.assertEqual(len(checks), 1)
        self.assertEqual(checks[0].name, 'good')
        checks = self.client.get_checks(names=['good', 'bad'])
        self.assertEqual(len(checks), 2)
        self.assertEqual(checks[0].name, 'bad')
        self.assertEqual(checks[1].name, 'good')

    def _get_health(self):
        f = urllib.request.urlopen('http://localhost:4000/v1/health')
        return json.loads(f.read())

    def test_exec_wait(self):
        process = self.client.exec(['true'])
        process.wait()

        with self.assertRaises(pebble.ExecError) as cm:
            process = self.client.exec(['/bin/sh', '-c', 'exit 42'])
            process.wait()
        self.assertEqual(cm.exception.exit_code, 42)

    def test_exec_wait_output(self):
        process = self.client.exec(['/bin/sh', '-c', 'echo OUT; echo ERR >&2'])
        out, err = process.wait_output()
        self.assertEqual(out, 'OUT\n')
        self.assertEqual(err, 'ERR\n')

        process = self.client.exec(['/bin/sh', '-c', 'echo OUT; echo ERR >&2'], encoding=None)
        out, err = process.wait_output()
        self.assertEqual(out, b'OUT\n')
        self.assertEqual(err, b'ERR\n')

        with self.assertRaises(pebble.ExecError) as cm:
            process = self.client.exec(['/bin/sh', '-c', 'echo OUT; echo ERR >&2; exit 42'])
            process.wait_output()
        self.assertEqual(cm.exception.exit_code, 42)
        self.assertEqual(cm.exception.stdout, 'OUT\n')
        self.assertEqual(cm.exception.stderr, 'ERR\n')

    def test_exec_send_stdin(self):
        process = self.client.exec(['awk', '{ print toupper($0) }'], stdin='foo\nBar\n')
        out, err = process.wait_output()
        self.assertEqual(out, 'FOO\nBAR\n')
        self.assertEqual(err, '')

        process = self.client.exec(['awk', '{ print toupper($0) }'], stdin=b'foo\nBar\n',
                                   encoding=None)
        out, err = process.wait_output()
        self.assertEqual(out, b'FOO\nBAR\n')
        self.assertEqual(err, b'')

    def test_push_pull(self):
        fname = os.path.join(tempfile.gettempdir(), f'pebbletest-{uuid.uuid4()}')
        content = 'foo\nbar\nbaz-42'
        self.client.push(fname, content)
        with self.client.pull(fname) as f:
            data = f.read()
            self.assertEqual(data, content)
        os.remove(fname)

    def test_exec_timeout(self):
        process = self.client.exec(['sleep', '0.2'], timeout=0.1)
        with self.assertRaises(pebble.ChangeError) as cm:
            process.wait()
        self.assertIn('timed out', cm.exception.err)

    def test_exec_working_dir(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            process = self.client.exec(['pwd'], working_dir=temp_dir)
            out, err = process.wait_output()
            self.assertEqual(out, f"{temp_dir}\n")
            self.assertEqual(err, '')

    def test_exec_environment(self):
        process = self.client.exec(['/bin/sh', '-c', 'echo $ONE.$TWO.$THREE'],
                                   environment={'ONE': '1', 'TWO': '2'})
        out, err = process.wait_output()
        self.assertEqual(out, '1.2.\n')
        self.assertEqual(err, '')

    def test_exec_streaming(self):
        process = self.client.exec(['cat'])
        assert process.stdout is not None

        def stdin_thread():
            assert process.stdin is not None
            try:
                for line in ['one\n', '2\n', 'THREE\n']:
                    process.stdin.write(line)
                    process.stdin.flush()
                    time.sleep(0.1)
            finally:
                process.stdin.close()

        threading.Thread(target=stdin_thread).start()

        reads: typing.List[str] = []
        for line in process.stdout:
            reads.append(line)

        process.wait()

        self.assertEqual(reads, ['one\n', '2\n', 'THREE\n'])

    def test_exec_streaming_bytes(self):
        process = self.client.exec(['cat'], encoding=None)
        assert process.stdout is not None

        def stdin_thread():
            assert process.stdin is not None
            try:
                for line in [b'one\n', b'2\n', b'THREE\n']:
                    process.stdin.write(line)
                    process.stdin.flush()
                    time.sleep(0.1)
            finally:
                process.stdin.close()

        threading.Thread(target=stdin_thread).start()

        reads: typing.List[bytes] = []
        for line in process.stdout:
            reads.append(line)

        process.wait()

        self.assertEqual(reads, [b'one\n', b'2\n', b'THREE\n'])

    def test_log_forwarding(self):
        self.client.add_layer("log-forwarder", {
            "services": {
                "tired": {
                    "override": "replace",
                    "command": "sleep 1",
                },
            },
            "log-targets": {
                "pretend-loki": {
                    "type": "loki",
                    "override": "replace",
                    "location": "https://example.com",
                    "services": ["all"],
                    "labels": {"foo": "bar"},
                },
            },
        }, combine=True)
        plan = self.client.get_plan()
        self.assertEqual(len(plan.log_targets), 1)
        self.assertEqual(plan.log_targets["pretend-loki"].type, "loki")
        self.assertEqual(plan.log_targets["pretend-loki"].override, "replace")
        self.assertEqual(plan.log_targets["pretend-loki"].location, "https://example.com")
        self.assertEqual(plan.log_targets["pretend-loki"].services, ["all"])
        self.assertEqual(plan.log_targets["pretend-loki"].labels, {"foo": "bar"})


@unittest.skipUnless(os.getenv('RUN_REAL_PEBBLE_TESTS'), 'RUN_REAL_PEBBLE_TESTS not set')
class TestPebbleStorageAPIsUsingRealPebble(unittest.TestCase, PebbleStorageAPIsTestMixin):
    def setUp(self):
        socket_path = os.getenv('PEBBLE_SOCKET')
        pebble_dir = os.getenv('PEBBLE')
        if not socket_path and pebble_dir:
            socket_path = os.path.join(pebble_dir, '.pebble.socket')
        assert socket_path and pebble_dir, 'PEBBLE must be set if RUN_REAL_PEBBLE_TESTS set'

        self.prefix = tempfile.mkdtemp(dir=pebble_dir)
        self.client = pebble.Client(socket_path=socket_path)

    def tearDown(self):
        shutil.rmtree(self.prefix)

    # Remove this entirely once the associated bug is fixed; it overrides the original test in the
    # test mixin class.
    @unittest.skip('pending resolution of https://github.com/canonical/pebble/issues/80')
    def test_make_dir_with_permission_mask(self):
        pass
