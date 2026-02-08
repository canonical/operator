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

"""Run (some) unit tests against a real Pebble server.

Set the RUN_REAL_PEBBLE_TESTS environment variable to run these tests
against a real Pebble server. For example, in one terminal, run Pebble:

$ PEBBLE=~/pebble pebble run --http=:4000
2021-09-20T04:10:34.934Z [pebble] Started daemon

In another terminal, run the tests:

$ source .tox/unit/bin/activate
$ RUN_REAL_PEBBLE_TESTS=1 PEBBLE=~/pebble pytest test/test_real_pebble.py -v
$ deactivate
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid

import pytest

from ops import pebble

from .test_testing import PebbleNoticesMixin, PebbleStorageAPIsTestMixin


def get_socket_path() -> str:
    socket_path = os.getenv('PEBBLE_SOCKET')
    pebble_path = os.getenv('PEBBLE')
    if not socket_path and pebble_path:
        assert isinstance(pebble_path, str)
        socket_path = os.path.join(pebble_path, '.pebble.socket')
    assert socket_path, 'PEBBLE or PEBBLE_SOCKET must be set if RUN_REAL_PEBBLE_TESTS set'
    return socket_path


@pytest.fixture
def client():
    return pebble.Client(socket_path=get_socket_path())


@pytest.mark.skipif(
    os.getenv('RUN_REAL_PEBBLE_TESTS') != '1',
    reason='RUN_REAL_PEBBLE_TESTS not set',
)
class TestRealPebble:
    def test_checks_and_health(self, client: pebble.Client):
        client.add_layer(
            'layer',
            {
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
            },
            combine=True,
        )

        # Checks should all be "up" initially
        checks = client.get_checks()
        assert len(checks) == 3
        assert checks[0].name == 'bad'
        assert checks[0].level == pebble.CheckLevel.READY
        assert checks[0].status == pebble.CheckStatus.UP
        assert checks[0].successes is not None and checks[0].successes >= 0
        assert checks[1].name == 'good'
        assert checks[1].level == pebble.CheckLevel.ALIVE
        assert checks[1].status == pebble.CheckStatus.UP
        assert checks[1].successes is not None and checks[1].successes >= 0
        assert checks[2].name == 'other'
        assert checks[2].level == pebble.CheckLevel.UNSET
        assert checks[2].status == pebble.CheckStatus.UP
        assert checks[2].successes is not None and checks[2].successes >= 0

        # And /v1/health should return "healthy"
        health = self._get_health()
        assert health == {
            'result': {'healthy': True},
            'status': 'OK',
            'status-code': 200,
            'type': 'sync',
        }

        # After two retries the "bad" check should go down
        for _ in range(5):
            checks = client.get_checks()
            bad_check = next(c for c in checks if c.name == 'bad')
            if bad_check.status == pebble.CheckStatus.DOWN:
                break
            time.sleep(0.06)
        else:
            assert False, 'timed out waiting for "bad" check to go down'
        assert bad_check.failures >= 2
        assert bad_check.threshold == 2
        good_check = next(c for c in checks if c.name == 'good')
        assert good_check.status == pebble.CheckStatus.UP

        # And /v1/health should return "unhealthy" (with status HTTP 502)
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            self._get_health()
        assert excinfo.value.code == 502
        health = json.loads(excinfo.value.read())
        assert health == {
            'result': {'healthy': False},
            'status': 'Bad Gateway',
            'status-code': 502,
            'type': 'sync',
        }

        # Then test filtering by check level and by name
        checks = client.get_checks(level=pebble.CheckLevel.ALIVE)
        assert len(checks) == 1
        assert checks[0].name == 'good'
        checks = client.get_checks(names=['good', 'bad'])
        assert len(checks) == 2
        assert checks[0].name == 'bad'
        assert checks[1].name == 'good'

    def _get_health(self):
        f = urllib.request.urlopen('http://localhost:4000/v1/health')
        return json.loads(f.read())

    def test_exec_wait(self, client: pebble.Client):
        process = client.exec(['true'])
        process.wait()

        excinfo: pytest.ExceptionInfo[pebble.ExecError[str]]
        with pytest.raises(pebble.ExecError) as excinfo:  # type: ignore
            process = client.exec(['/bin/sh', '-c', 'exit 42'])
            process.wait()
        assert excinfo.value.exit_code == 42

    def test_exec_wait_output(self, client: pebble.Client):
        process = client.exec(['/bin/sh', '-c', 'echo OUT; echo ERR >&2'])
        out, err = process.wait_output()
        assert out == 'OUT\n'
        assert err == 'ERR\n'

        process = client.exec(['/bin/sh', '-c', 'echo OUT; echo ERR >&2'], encoding=None)
        out, err = process.wait_output()
        assert out == b'OUT\n'
        assert err == b'ERR\n'

        excinfo: pytest.ExceptionInfo[pebble.ExecError[str]]
        with pytest.raises(pebble.ExecError) as excinfo:  # type: ignore
            process = client.exec(['/bin/sh', '-c', 'echo OUT; echo ERR >&2; exit 42'])
            process.wait_output()
        assert excinfo.value.exit_code == 42
        assert excinfo.value.stdout == 'OUT\n'
        assert excinfo.value.stderr == 'ERR\n'

    def test_exec_send_stdin(self, client: pebble.Client):
        process = client.exec(['awk', '{ print toupper($0) }'], stdin='foo\nBar\n')
        out, err = process.wait_output()
        assert out == 'FOO\nBAR\n'
        assert err == ''

        process = client.exec(
            ['awk', '{ print toupper($0) }'],
            stdin=b'foo\nBar\n',
            encoding=None,
        )
        out, err = process.wait_output()
        assert out == b'FOO\nBAR\n'
        assert err == b''

    def test_push_pull(self, client: pebble.Client):
        fname = os.path.join(tempfile.gettempdir(), f'pebbletest-{uuid.uuid4()}')
        content = 'foo\nbar\nbaz-42'
        client.push(fname, content)
        with client.pull(fname) as f:
            data = f.read()
            assert data == content
        os.remove(fname)

    def test_push_pull_path(self, client: pebble.Client, tmp_path: pathlib.Path):
        path = tmp_path / f'pebbletest-{uuid.uuid4()}'
        content = 'foo\nbar\nbaz-42'
        client.push(path, content)
        with client.pull(path) as f:
            data = f.read()
            assert data == content

    @pytest.mark.parametrize('path_type', (str, pathlib.Path))
    def test_list_files_path_type(
        self,
        client: pebble.Client,
        tmp_path: pathlib.Path,
        path_type: type[str] | type[pathlib.Path],
    ):
        (foo := tmp_path / 'foo').touch()
        (bar := tmp_path / 'bar').touch()
        file_infos = client.list_files(path_type(tmp_path))
        assert {f.path for f in file_infos} == {str(foo), str(bar)}

    @pytest.mark.parametrize('path_type', (str, pathlib.Path))
    def test_make_dir_path_type(
        self,
        client: pebble.Client,
        tmp_path: pathlib.Path,
        path_type: type[str] | type[pathlib.Path],
    ):
        path = tmp_path / 'my-dir'
        assert not path.exists()
        client.make_dir(path_type(path))
        assert path.is_dir()

    @pytest.mark.parametrize('path_type', (str, pathlib.Path))
    def test_remove_path_path_type(
        self,
        client: pebble.Client,
        tmp_path: pathlib.Path,
        path_type: type[str] | type[pathlib.Path],
    ):
        path = tmp_path / 'foo'
        path.touch()
        assert path.exists()
        client.remove_path(path_type(path))
        assert not path.exists()

    def test_exec_timeout(self, client: pebble.Client):
        process = client.exec(['sleep', '0.2'], timeout=0.1)
        with pytest.raises(pebble.ChangeError) as excinfo:
            process.wait()
        assert 'timed out' in excinfo.value.err

    def test_exec_working_dir(self, client: pebble.Client):
        with tempfile.TemporaryDirectory() as temp_dir:
            process = client.exec(['pwd'], working_dir=temp_dir)
            out, err = process.wait_output()
            assert out == f'{temp_dir}\n'
            assert err == ''

    def test_exec_working_dir_path(self, client: pebble.Client, tmp_path: pathlib.Path):
        process = client.exec(['pwd'], working_dir=tmp_path)
        out, err = process.wait_output()
        assert out == f'{tmp_path}\n'
        assert err == ''

    def test_exec_environment(self, client: pebble.Client):
        process = client.exec(
            ['/bin/sh', '-c', 'echo $ONE.$TWO.$THREE'],
            environment={'ONE': '1', 'TWO': '2'},
        )
        out, err = process.wait_output()
        assert out == '1.2.\n'
        assert err == ''

    def test_exec_streaming(self, client: pebble.Client):
        process = client.exec(['cat'])
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

        reads: list[str] = list(process.stdout)

        process.wait()

        assert reads == ['one\n', '2\n', 'THREE\n']

    def test_exec_streaming_bytes(self, client: pebble.Client):
        process = client.exec(['cat'], encoding=None)
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

        reads: list[bytes] = list(process.stdout)

        process.wait()

        assert reads == [b'one\n', b'2\n', b'THREE\n']

    def test_log_forwarding(self, client: pebble.Client):
        client.add_layer(
            'log-forwarder',
            {
                'services': {
                    'tired': {
                        'override': 'replace',
                        'command': 'sleep 1',
                    },
                },
                'log-targets': {
                    'pretend-loki': {
                        'type': 'loki',
                        'override': 'replace',
                        'location': 'https://example.com',
                        'services': ['all'],
                        'labels': {'foo': 'bar'},
                    },
                },
            },
            combine=True,
        )
        plan = client.get_plan()
        assert len(plan.log_targets) == 1
        assert plan.log_targets['pretend-loki'].type == 'loki'
        assert plan.log_targets['pretend-loki'].override == 'replace'
        assert plan.log_targets['pretend-loki'].location == 'https://example.com'
        assert plan.log_targets['pretend-loki'].services == ['all']
        assert plan.log_targets['pretend-loki'].labels == {'foo': 'bar'}

    def test_identities(self, client: pebble.Client):
        identities = client.get_identities()
        assert len(identities) == 0

        identities = {
            'web': pebble.Identity.from_dict({
                'access': 'metrics',
                'basic': {
                    'password': '$6$et3kBQywmQQ./htQ$MuUHB8DyxOzZT//NXas0aT.P0j0DJA8fCWvpOJ9kn9O0HIlAvEcAJVGQ6OVr23ndtK9kiNgCnMs2NJtDe/nhC1'  # noqa: E501
                },
            }),
            'alice': pebble.Identity.from_dict({
                'access': 'admin',
                'local': {'user-id': 42},
            }),
        }
        client.replace_identities(identities)
        identities = client.get_identities()
        assert len(identities) == 2
        assert identities['web'].access == pebble.IdentityAccess.METRICS
        assert identities['web'].basic is not None
        assert identities['web'].basic.password == '*****'
        assert identities['alice'].access == pebble.IdentityAccess.ADMIN
        assert identities['alice'].local is not None
        assert identities['alice'].local.user_id == 42

        identities['alice'].local.user_id = 1000
        client.replace_identities(identities)
        identities = client.get_identities()
        assert identities['alice'].local is not None
        assert identities['alice'].local.user_id == 1000

        client.remove_identities({'web', 'alice'})
        identities = client.get_identities()
        assert len(identities) == 0

    def test_temp_files_cleaned_up_on_failed_pull(
        self,
        tmp_path: pathlib.Path,
        client: pebble.Client,
        monkeypatch: pytest.MonkeyPatch,
    ):
        client.push(f'{tmp_path}/test', os.urandom(1024 * 1024))  # chunk size is 16 * 2014
        tf = tempfile.NamedTemporaryFile(delete=False)  # noqa: SIM115
        # Patch get_response to force a ProtocolError exception.
        monkeypatch.setattr(pebble._FilesParser, 'get_response', lambda self: None)  # type: ignore
        # Use our previously created temp dir so we can verify that it gets cleaned up.
        monkeypatch.setattr(tempfile, 'NamedTemporaryFile', lambda *args, **kwargs: tf)  # type: ignore
        with pytest.raises(pebble.ProtocolError):
            client.pull(f'{tmp_path}/test')
        assert not pathlib.Path(tf.name).exists()


@pytest.mark.skipif(
    os.getenv('RUN_REAL_PEBBLE_TESTS') != '1',
    reason='RUN_REAL_PEBBLE_TESTS not set',
)
class TestPebbleStorageAPIsUsingRealPebble(PebbleStorageAPIsTestMixin):
    @pytest.fixture
    def pebble_dir(self):
        pebble_path = os.getenv('PEBBLE')
        assert pebble_path is not None
        pebble_dir = tempfile.mkdtemp(dir=pebble_path)
        yield pebble_dir
        shutil.rmtree(pebble_dir)


@pytest.mark.skipif(
    os.getenv('RUN_REAL_PEBBLE_TESTS') != '1',
    reason='RUN_REAL_PEBBLE_TESTS not set',
)
class TestNoticesUsingRealPebble(PebbleNoticesMixin):
    pass
