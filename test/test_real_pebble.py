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
import socket
import stat
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable, Generator
from typing import cast

import pytest

import ops
import ops.testing
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

    @pytest.mark.parametrize('name', ['trailing ', 'trailing\t', 'crème'])
    def test_push_pull_name_with_whitespace_or_non_ascii(
        self, client: pebble.Client, tmp_path: pathlib.Path, name: str
    ):
        path = tmp_path / name
        content = 'foo\nbar\nbaz-42'
        client.push(path, content)
        with client.pull(path) as f:
            assert f.read() == content

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

    @pytest.mark.parametrize(
        'name',
        [
            'back\\slash',  # \s isn't a tspecial, so this worked before the fix too.
            'back\\;slash',
            'back\\"slash',
            'back\\\\slash',
            'trailing\\',
        ],
    )
    def test_push_pull_awkward_name(
        self, client: pebble.Client, tmp_path: pathlib.Path, name: str
    ):
        path = tmp_path / name
        content = 'foo\nbar\nbaz-42'
        client.push(path, content)
        assert path.read_text() == content
        with client.pull(path) as f:
            assert f.read() == content

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

    def test_exec_wait_timeout_reaps_io_threads(self, client: pebble.Client):
        # Regression test for canonical/operator#2556.
        #
        # Repro: the orphaned grandchild keeps the exec's stdio pipe open, so
        # the change can't finish even after Pebble kills the command at the
        # 0.1s timeout, and the wait then times out client-side.
        #
        # Before the fix, the I/O threads were left blocked on the websockets,
        # and being non-daemon they hung interpreter shutdown. This test
        # asserts that after wait_output() raises TimeoutError, the I/O
        # threads exit promptly.
        process = client.exec(['/bin/sh', '-c', 'setsid sleep 3 & sleep 3'], timeout=0.1)
        with pytest.raises(pebble.TimeoutError):
            process.wait_output()
        for thread in process._threads:
            thread.join(timeout=2)
        assert [t.name for t in process._threads if t.is_alive()] == []

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
                    'password': '$6$et3kBQywmQQ./htQ$MuUHB8DyxOzZT//NXas0aT.P0j0DJA8fCWvpOJ9kn9O0HIlAvEcAJVGQ6OVr23ndtK9kiNgCnMs2NJtDe/nhC1'  # ruff: ignore[line-too-long]
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
        tf = tempfile.NamedTemporaryFile(delete=False)  # ruff: ignore[open-file-with-context-handler]
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


# A callable that performs one filesystem operation. Its arguments are a
# Pebble client (or a charm's Container, which exposes the same methods
# over the mock client) and a resolver that turns a path relative to the
# tree root into a path that side understands (an absolute path for real
# Pebble, a container path for the mock).
_CaseRun = Callable[[pebble.Client | ops.Container, Callable[[str], str]], object]

_FS_PATHS = (
    'file',
    'dir',
    'empty',
    'fifo',
    'sock',
    'to_file',
    'to_dir',
    'to_to_file',
    'broken',
    'loop',
    'missing',
    'file/child',
    'to_file/child',
    'broken/child',
    'loop/child',
    'missing/child',
    'fifo/child',
    'ro_dir',
    'ro_dir/f',
    'ro_dir/new',
    'ro_full',
    'ro_full/f',
    'ro_full/new',
    'noaccess_dir',
    'noaccess_dir/child',
    'noaccess_file',
    'noaccess_file/child',
    'readonly_file',
    'readonly_file/child',
)

_FS_PATTERNS = (
    '*.txt',
    '?.txt',
    '[a].txt',
    '[!a].txt',
    '[^a].txt',
    '\\[x\\]',
    '[[]x]',
    '[',
    'a\\',
    '*',
    '',
)


def _pull_file(client: pebble.Client | ops.Container, path: str) -> None:
    with client.pull(path) as file:
        file.read()


_FS_OPS: dict[str, Callable[[pebble.Client | ops.Container, str], object]] = {
    'list': lambda client, path: client.list_files(path),
    'list_itself': lambda client, path: client.list_files(path, itself=True),
    'pull': _pull_file,
    'push': lambda client, path: client.push(path, 'y'),
    'push_parents': lambda client, path: client.push(path, 'y', make_dirs=True),
    'remove': lambda client, path: client.remove_path(path),
    'remove_rec': lambda client, path: client.remove_path(path, recursive=True),
    'make_dir': lambda client, path: client.make_dir(path),
    'make_dir_parents': lambda client, path: client.make_dir(path, make_parents=True),
}

# Cases that currently differ between the testing client and real Pebble,
# mapped to their difference group. Fixing the mock turns a case's strict
# xfail into an xpass failure, so the table cannot silently become stale.
# There are no known differences at the moment; add an entry here when one
# is found (or intentionally left behind), with its group from
# _FS_XFAIL_REASONS.
_FS_XFAIL_GROUPS: dict[tuple[str, str], int] = {}

_FS_XFAIL_REASONS = {
    1: 'group 1: the mock succeeds but real Pebble raises an error',
    2: 'group 2: the mock raises an error but real Pebble succeeds',
    3: 'group 3: the mock raises a different error type or message than real Pebble',
    4: 'group 4: the mock returns a different result than real Pebble',
}

# Phrases in error messages that charms and libraries match on (for example,
# charmlibs-pathops matches 'not a directory'). The mock must word its errors
# like Pebble does ('<op> <path>: <reason>'), so the comparison covers the
# whole set of these phrases found in each message.
_FS_KEY_PHRASES = (
    'not a directory',
    'too many levels of symbolic links',
    'file exists',
    'no such file or directory',
    'syntax error in pattern',
    'can only read a regular file',
    'directory not empty',
    'permission denied',
    'device or resource busy',
)


def _build_fs_tree(root: pathlib.Path) -> None:
    (root / 'file').write_text('x')
    (root / 'dir').mkdir()
    (root / 'dir' / 'a.txt').touch()
    (root / 'dir' / 'b.log').touch()
    (root / 'dir' / '[x]').touch()
    (root / 'dir' / 'link').symlink_to('a.txt')
    (root / 'empty').mkdir()
    (root / 'nonempty').mkdir()
    (root / 'nonempty' / 'f').touch()
    os.mkfifo(root / 'fifo')
    unix_sock = socket.socket(socket.AF_UNIX)
    unix_sock.bind(str(root / 'sock'))
    unix_sock.close()
    for name, target in {
        'to_file': 'file',
        'to_dir': 'dir',
        'to_to_file': 'to_file',
        'broken': 'nope',
        'loop': 'loop',
    }.items():
        (root / name).symlink_to(target)
    # The modes are applied last, so that the content can be created first.
    (root / 'ro_dir').mkdir()
    (root / 'ro_full').mkdir()
    (root / 'ro_full' / 'f').write_text('x')
    (root / 'noaccess_dir').mkdir()
    (root / 'noaccess_file').write_text('x')
    (root / 'readonly_file').write_text('x')
    (root / 'ro_dir').chmod(0o555)
    (root / 'ro_full').chmod(0o555)
    (root / 'noaccess_dir').chmod(0o000)
    (root / 'noaccess_file').chmod(0o000)
    (root / 'readonly_file').chmod(0o444)


def _make_removable(path: pathlib.Path) -> None:
    """Recursively give the owner rwx on a tree, without following symlinks."""
    if path.is_symlink():
        return
    if path.is_dir():
        path.chmod(path.lstat().st_mode | 0o700)
        for child in path.iterdir():
            _make_removable(child)


def _snapshot(root: pathlib.Path) -> dict[str, tuple[object, ...]]:
    """Describe every entry below root: type, symlink target, mode and content.

    Entries that the test user cannot read are recorded without their content
    or listing. FIFOs and sockets are never opened, as that can block.
    """
    entries: dict[str, tuple[object, ...]] = {}

    def visit(path: pathlib.Path) -> None:
        info = path.lstat()
        mode = stat.S_IMODE(info.st_mode)
        key = str(path.relative_to(root))
        if stat.S_ISLNK(info.st_mode):
            entries[key] = ('symlink', mode, os.readlink(path))
        elif stat.S_ISDIR(info.st_mode):
            entries[key] = ('dir', mode)
            try:
                children = sorted(path.iterdir())
            except PermissionError:
                return
            for child in children:
                visit(child)
        elif stat.S_ISREG(info.st_mode):
            try:
                content: bytes | None = path.read_bytes()
            except PermissionError:
                content = None
            entries[key] = ('file', mode, content)
        else:
            entries[key] = ('other', stat.S_IFMT(info.st_mode), mode)

    for child in sorted(root.iterdir()):
        visit(child)
    return entries


def _key_phrases(message: str) -> frozenset[str]:
    return frozenset(phrase for phrase in _FS_KEY_PHRASES if phrase in message)


def _outcome(
    root: pathlib.Path,
    run: _CaseRun,
    client: pebble.Client | ops.Container,
    resolve: Callable[[str], str],
) -> tuple[object, ...]:
    # The filesystem state afterwards is part of the outcome, so a case also
    # fails if one side changed or left behind the wrong thing (including
    # temporary files).
    try:
        value = run(client, resolve)
    except pebble.APIError as error:
        return ('APIError', error.code, _key_phrases(error.message), _snapshot(root))
    except pebble.PathError as error:
        return ('PathError', error.kind, _key_phrases(error.message), _snapshot(root))
    except Exception as error:
        # Errors outside Pebble's API (for example an OSError that the
        # testing client did not translate) are compared by class name.
        return (type(error).__name__, None, _key_phrases(str(error)), _snapshot(root))
    if isinstance(value, list):
        file_infos = cast('list[pebble.FileInfo]', value)
        listing = sorted(
            (
                info.path.removeprefix(str(root)),
                info.name,
                pebble.FileType(info.type).value,
                info.permissions,
            )
            for info in file_infos
        )
        return ('ok', listing, _snapshot(root))
    return ('ok', _snapshot(root))


def _path_case(op: str, path: str) -> _CaseRun:
    return lambda client, resolve: _FS_OPS[op](client, resolve(path))


def _pattern_case(pattern: str) -> _CaseRun:
    return lambda client, resolve: client.list_files(resolve('dir'), pattern=pattern)


def _case_param(name: str, run: _CaseRun, key: tuple[str, str]):
    group = _FS_XFAIL_GROUPS.get(key)
    if group is None:
        return pytest.param(run, id=name)
    reason = _FS_XFAIL_REASONS[group]
    mark = pytest.mark.xfail(strict=True, raises=AssertionError, reason=reason)
    return pytest.param(run, marks=mark, id=name)


def _path_case_runs():
    for path in _FS_PATHS:
        for op in _FS_OPS:
            # pull and push on a FIFO can block real Pebble, and removing a
            # path below a FIFO hangs it until the client times out, so those
            # combinations are not covered here.
            if path == 'fifo' and op in ('pull', 'push', 'push_parents'):
                continue
            if (op, path) == ('remove_rec', 'fifo/child'):
                continue
            yield _case_param(f'{op} {path}', _path_case(op, path), (op, path))


def _make_dir_then_list(client: pebble.Client | ops.Container, resolve: Callable[[str], str]):
    client.make_dir(resolve('zero'), permissions=0)
    return client.list_files(resolve('zero'))


def _make_dir_nested(permissions: int, then_list: str | None = None) -> _CaseRun:
    def run(client: pebble.Client | ops.Container, resolve: Callable[[str], str]):
        client.make_dir(resolve('x/y'), make_parents=True, permissions=permissions)
        if then_list is not None:
            return client.list_files(resolve(then_list), itself=True)

    return run


def _push_then_pull(client: pebble.Client | ops.Container, resolve: Callable[[str], str]):
    client.push(resolve('secret'), 'y', permissions=0o400)
    _pull_file(client, resolve('secret'))


def _sequence_cases():
    cases = {
        'make_dir permissions=0 then list': _make_dir_then_list,
        'make_dir parents permissions=0o555': _make_dir_nested(0o555),
        'make_dir parents permissions=0o700 then list parent itself': _make_dir_nested(
            0o700, then_list='x'
        ),
        'push permissions=0o400 then pull': _push_then_pull,
    }
    return [_case_param(name, run, ('sequence', name)) for name, run in cases.items()]


def _fs_cases():
    return [
        *_path_case_runs(),
        *_sequence_cases(),
        _case_param('remove nonempty', _path_case('remove', 'nonempty'), ('remove', 'nonempty')),
        *(
            _case_param(
                f'list dir pattern={pattern!r}', _pattern_case(pattern), ('pattern', pattern)
            )
            for pattern in _FS_PATTERNS
        ),
    ]


@pytest.fixture(scope='module')
def scenario_context() -> Generator[ops.testing.Context[ops.CharmBase]]:
    yield ops.testing.Context(ops.CharmBase, meta={'name': 'charm', 'containers': {'c': {}}})


@pytest.mark.skipif(
    os.getenv('RUN_REAL_PEBBLE_TESTS') != '1',
    reason='RUN_REAL_PEBBLE_TESTS not set',
)
@pytest.mark.skipif(
    os.geteuid() == 0,
    reason='permission cases need a non-root Pebble, and a root test run would start a root one',
)
class TestMockPebbleFilesystemMatchesRealPebble:
    """Compare the ops.testing mock Pebble client's filesystem behaviour with real Pebble.

    Each case runs the same operation against a real Pebble server and against
    the mock client behind a Scenario container (through the charm's
    Container, the public API charms use), on identical freshly built
    filesystem trees, and compares the outcome: for successes, the result; for
    errors, the exception class, the APIError code or PathError kind, and the
    key phrases in the message that charms match on. Each outcome also
    includes a snapshot of the whole tree afterwards (types, modes, symlink
    targets and contents). Cases that currently differ are marked
    xfail(strict=True) with their difference group.

    The mock models a Pebble running as a non-root user (as `tox -e pebble`
    does), so permission bits are enforced. A root test process would make
    both sides root and bypass them, so the class is skipped then.
    """

    @pytest.mark.parametrize('run', _fs_cases())
    def test_fs_case(
        self,
        client: pebble.Client,
        scenario_context: ops.testing.Context[ops.CharmBase],
        tmp_path: pathlib.Path,
        run: _CaseRun,
    ):
        state = ops.testing.State(containers={ops.testing.Container(name='c', can_connect=True)})
        with scenario_context(scenario_context.on.start(), state=state) as mgr:
            mgr.run()
            # Creating the container also creates the mock client; its
            # filesystem root persists between cases, so reset it by hand.
            # tmp_path is already fresh.
            mock_container = mgr.charm.unit.get_container('c')
            mock_root = state.get_container('c').get_filesystem(scenario_context)
            # Earlier cases may leave unreadable or read-only directories.
            _make_removable(mock_root)
            for child in mock_root.iterdir():
                if child.is_dir() and not child.is_symlink():
                    shutil.rmtree(child)
                else:
                    child.unlink()
            _build_fs_tree(mock_root)
            _build_fs_tree(tmp_path)
            try:
                real = _outcome(tmp_path, run, client, lambda path: str(tmp_path / path))
                mock = _outcome(mock_root, run, mock_container, lambda path: f'/{path}')
            finally:
                # Unreadable directories would stop pytest from cleaning up
                # tmp_path (it only warns, but leaves the files behind).
                _make_removable(tmp_path)
        assert mock == real
