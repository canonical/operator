# Copyright 2025 Canonical Ltd.
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

from __future__ import annotations

import dataclasses
import ipaddress
import json
import pathlib
import subprocess
import uuid
from typing import Any, Generator

import pytest

from ops import hookcmds

# Call, Run, and NamedTemporaryFile are heavily based on the mocks of the same
# names in Jubilant: https://github.com/canonical/jubilant/blob/main/tests/unit/mocks.py


@dataclasses.dataclass(frozen=True)
class Call:
    args: tuple[str, ...]
    returncode: int
    stdin: str | None
    stdout: str
    stderr: str


class Run:
    """Mock for subprocess.run.

    When subprocess.run is called, the mock returns a subprocess.CompletedProcess
    instance with data passed to :meth:`handle` for those command-line arguments.
    Or, if returncode is nonzero, it raises a subprocess.CalledProcessError.

    This also asserts that the correct keyword args are passed to subprocess.run,
    for example check=True.
    """

    def __init__(self):
        self._commands: dict[tuple[str, ...], tuple[int, str, str]] = {}
        self.calls: list[Call] = []

    def handle(self, args: list[str], *, returncode: int = 0, stdout: str = '', stderr: str = ''):
        """Handle specified command-line args with the given return code, stdout, and stderr."""
        self._commands[tuple(args)] = (returncode, stdout, stderr)

    def __call__(
        self,
        args: list[str],
        check: bool = False,
        capture_output: bool = False,
        encoding: str | None = None,
        input: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        args_tuple = tuple(args)
        assert check is True
        assert capture_output is True
        assert encoding == 'utf-8'
        assert args_tuple in self._commands, f'unhandled command {args}'

        returncode, stdout, stderr = self._commands[args_tuple]
        self.calls.append(
            Call(args=args_tuple, returncode=returncode, stdin=input, stdout=stdout, stderr=stderr)
        )
        if returncode != 0:
            raise subprocess.CalledProcessError(
                returncode=returncode,
                cmd=args,
                output=stdout,
                stderr=stderr,
            )
        return subprocess.CompletedProcess(
            args=args,
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
        )


class NamedTemporaryFile:
    """Mock for tempfile.NamedTemporaryFile.

    Captures any writes to the file. Each call to write
    adds to the *writes* list, and each flush increments the number of flushes.
    """

    def __init__(self):
        self.writes: list[str] = []
        self.num_flushes: int = 0
        self.name = 'path/to/temp_file_name'

    def __call__(self, *args: Any, **kwargs: Any):
        assert 'w+' in args
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args: Any):
        return

    def write(self, data: str) -> None:
        self.writes.append(data)

    def flush(self) -> None:
        self.num_flushes += 1


class TemporaryDirectory:
    """Mock for tempfile.TemporaryDirectory."""

    def __init__(self):
        self.name = 'path/to/temp_dir_name'
        self.files: list[NamedTemporaryFile] = []

    def __call__(self, *args: Any, **kwargs: Any):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args: Any):
        return

    def __str__(self):
        return self.name


@pytest.fixture
def run(monkeypatch: pytest.MonkeyPatch) -> Generator[Run]:
    """Pytest fixture that patches subprocess.run with Run."""
    run_mock = Run()
    monkeypatch.setattr('subprocess.run', run_mock)

    yield run_mock
    assert len(run_mock.calls) >= 1, 'subprocess.run not called'


@pytest.fixture
def mock_file(monkeypatch: pytest.MonkeyPatch) -> Generator[NamedTemporaryFile]:
    """Pytest fixture that patches tempfile.NamedTemporaryFile with File."""
    file_mock = NamedTemporaryFile()
    monkeypatch.setattr('tempfile.NamedTemporaryFile', file_mock)
    yield file_mock


@pytest.fixture
def mock_temp_dir(monkeypatch: pytest.MonkeyPatch) -> Generator[TemporaryDirectory]:
    """Pytest fixture that patches tempfile.TemporaryDirectory and open()."""
    dir_mock = TemporaryDirectory()
    monkeypatch.setattr('tempfile.TemporaryDirectory', dir_mock)

    def mock_open(path: str, *args: Any, **kwargs: Any) -> Any:
        if path.startswith(f'{dir_mock.name}/'):
            file_mock = NamedTemporaryFile()
            file_mock.name = f'{dir_mock.name}/{file_mock.name}'
            dir_mock.files.append(file_mock)
            return file_mock
        return open(path, *args, **kwargs)  # type: ignore

    monkeypatch.setattr('builtins.open', mock_open)

    yield dir_mock


def test_action_fail(run: Run):
    run.handle(['action-fail'])
    hookcmds.action_fail()


def test_action_fail_with_message(run: Run):
    run.handle(['action-fail', 'oh no!'])
    hookcmds.action_fail('oh no!')


def test_action_get(run: Run):
    run.handle(['action-get', '--format=json'], stdout='{"foo": "bar"}')
    params = hookcmds.action_get()
    assert params == {'foo': 'bar'}


def test_action_get_key(run: Run):
    run.handle(['action-get', '--format=json', 'baz'], stdout='"qux"')
    param = hookcmds.action_get('baz')
    assert param == 'qux'


def test_action_log(run: Run):
    run.handle(['action-log', 'progress update'])
    hookcmds.action_log('progress update')


def test_action_set(run: Run):
    run.handle(['action-set', 'foo=bar', 'baz=qux'])
    hookcmds.action_set({'foo': 'bar', 'baz': 'qux'})


def test_application_version_set(run: Run):
    run.handle(['application-version-set', '1.2.3'])
    hookcmds.application_version_set('1.2.3')


def test_close_port(run: Run):
    run.handle(['close-port', '--endpoints', 'ep1', '8080/tcp'])
    hookcmds.close_port(protocol='tcp', port=8080, endpoints='ep1')


def test_config_get(run: Run):
    run.handle(['config-get', '--format=json'], stdout='{"foo": "bar"}')
    result = hookcmds.config_get()
    assert result == {'foo': 'bar'}


def test_credential_get(run: Run):
    cred: dict[str, Any] = {
        'type': 'cloud',
        'name': 'test',
        'region': None,
        'endpoint': None,
        'identity_endpoint': None,
        'storage_endpoint': None,
        'credential': None,
        'ca_certificates': [],
        'skip_tls_verify': False,
        'is_controller_cloud': False,
    }
    run.handle(['credential-get', '--format=json'], stdout=json.dumps(cred))
    result = hookcmds.credential_get()
    assert result.type == 'cloud'
    assert result.name == 'test'


def test_goal_state(run: Run):
    gs = {
        'units': {'my-unit/0': {'status': 'active', 'since': '2025-08-28T13:20:00'}},
        'relations': {},
    }
    run.handle(['goal-state', '--format=json'], stdout=json.dumps(gs))
    result = hookcmds.goal_state()
    assert 'my-unit/0' in result.units
    assert result.units['my-unit/0'].status == 'active'


def test_is_leader(run: Run):
    run.handle(['is-leader', '--format=json'], stdout='true')
    assert hookcmds.is_leader() is True


def test_juju_log(run: Run):
    run.handle(['juju-log', '--log-level', 'INFO', 'msg'])
    hookcmds.juju_log('msg')


def test_juju_reboot(run: Run, monkeypatch: pytest.MonkeyPatch):
    run.handle(['juju-reboot'])
    monkeypatch.setattr('sys.exit', lambda: None)
    hookcmds.juju_reboot()


def test_network_get(run: Run):
    net = {
        'bind-addresses': [
            {
                'mac-address': 'aa:bb',
                'interface-name': 'eth0',
                'addresses': [{'hostname': 'host', 'value': '127.0.0.1', 'cidr': '127.0.0.0/24'}],
            }
        ],
        'egress-subnets': ['127.0.0.0/24'],
        'ingress-addresses': ['127.0.0.1'],
    }
    run.handle(['network-get', 'bind', '--format=json'], stdout=json.dumps(net))
    result = hookcmds.network_get('bind')
    assert result.bind_addresses[0].mac_address == 'aa:bb'
    assert result.bind_addresses[0].interface_name == 'eth0'
    assert result.bind_addresses[0].addresses[0].hostname == 'host'
    assert result.bind_addresses[0].addresses[0].value == ipaddress.ip_address('127.0.0.1')
    assert result.bind_addresses[0].addresses[0].cidr == ipaddress.ip_network('127.0.0.0/24')
    assert result.egress_subnets[0] == ipaddress.ip_network('127.0.0.0/24')
    assert result.ingress_addresses[0] == ipaddress.ip_address('127.0.0.1')


def test_open_port(run: Run):
    run.handle(['open-port', '--endpoints', 'ep1', '8080/tcp'])
    hookcmds.open_port(protocol='tcp', port=8080, endpoints='ep1')


def test_opened_ports(run: Run):
    run.handle(['opened-ports', '--format=json'], stdout='["8080/tcp"]')
    result = hookcmds.opened_ports()
    assert result[0].port == 8080
    assert result[0].protocol == 'tcp'


def test_relation_get(run: Run):
    run.handle(['relation-get', '--format=json'], stdout='{"foo": "bar"}')
    result = hookcmds.relation_get()
    assert result == {'foo': 'bar'}


def test_relation_ids(run: Run):
    run.handle(['relation-ids', 'db', '--format=json'], stdout='["rel:1"]')
    result = hookcmds.relation_ids('db')
    assert result == ['rel:1']


def test_relation_list(run: Run):
    run.handle(['relation-list', '--format=json'], stdout='["unit/0"]')
    result = hookcmds.relation_list()
    assert result == ['unit/0']


def test_relation_model_get(run: Run):
    data = {'uuid': str(uuid.uuid4())}
    run.handle(['relation-model-get', '--format=json'], stdout=json.dumps(data))
    result = hookcmds.relation_model_get()
    assert str(result.uuid) == data['uuid']


def test_relation_set(run: Run, mock_file: NamedTemporaryFile):
    run.handle(['relation-set', '--file', '-'])
    hookcmds.relation_set({'foo': 'bar'})
    assert run.calls[0].stdin == 'foo: bar\n'


def test_resource_get(run: Run):
    run.handle(['resource-get', 'res'], stdout='/path/to/resource')
    result = hookcmds.resource_get('res')
    assert str(result) == '/path/to/resource'


def test_secret_add(run: Run, mock_temp_dir: str):
    run.handle(['secret-add', f'foo#file={mock_temp_dir}/foo'], stdout='secretid')
    result = hookcmds.secret_add({'foo': 'bar'})
    assert result == 'secretid'


def test_secret_get(run: Run):
    run.handle(['secret-get', '--format=json', 'secret:123'], stdout='{"foo": "bar"}')
    result = hookcmds.secret_get(id='secret:123')
    assert result == {'foo': 'bar'}


def test_secret_grant(run: Run):
    run.handle(['secret-grant', '--relation', '1', 'id'])
    hookcmds.secret_grant('id', 1)


def test_secret_ids(run: Run):
    run.handle(['secret-ids', '--format=json'], stdout='["id1", "id2"]')
    result = hookcmds.secret_ids()
    assert result == ['id1', 'id2']


def test_secret_info_get(run: Run):
    info = {
        '123': {
            'label': 'lbl',
            'description': 'desc',
            'expiry': None,
            'rotation': None,
            'rotates': None,
            'revision': 1,
        }
    }
    run.handle(['secret-info-get', '--format=json', 'secret:123'], stdout=json.dumps(info))
    result = hookcmds.secret_info_get(id='secret:123')
    assert result.id == '123'
    assert result.label == 'lbl'


def test_secret_remove(run: Run):
    run.handle(['secret-remove', 'id'])
    hookcmds.secret_remove('id')


def test_secret_revoke(run: Run):
    run.handle(['secret-revoke', 'id'])
    hookcmds.secret_revoke('id', relation_id=None, app=None)


def test_secret_set(run: Run, mock_temp_dir: str):
    run.handle(['secret-set', 'secret:123', f'foo#file={mock_temp_dir}/foo'])
    hookcmds.secret_set('secret:123', content={'foo': 'bar'})


def test_state_delete(run: Run):
    run.handle(['state-delete', 'foo'])
    hookcmds.state_delete('foo')


def test_state_get(run: Run):
    run.handle(['state-get', '--format=json'], stdout='{"foo": "bar"}')
    result = hookcmds.state_get(None)
    assert result == {'foo': 'bar'}


def test_state_set(run: Run):
    run.handle(['state-set', '--file', '-'])
    hookcmds.state_set({'foo': 'bar'})


def test_status_get(run: Run):
    unit: hookcmds._StatusDict = {'status': 'active', 'message': 'ok', 'status-data': {}}
    run.handle(
        ['status-get', '--include-data', '--format=json', '--application=false'],
        stdout=json.dumps(unit),
    )
    result = hookcmds.status_get(app=False)
    assert result.status == 'active'


def test_status_set(run: Run):
    run.handle(['status-set', '--application=False', 'active', 'msg'])
    hookcmds.status_set('active', 'msg')


def test_storage_add(run: Run):
    run.handle(['storage-add', 'foo=1'])
    hookcmds.storage_add('foo')


def test_storage_get(run: Run):
    storage = {'kind': 'block', 'location': '/path/to/storage'}
    run.handle(['storage-get', '--format=json'], stdout=json.dumps(storage))
    result = hookcmds.storage_get()
    assert result.kind == 'block'
    assert result.location == pathlib.Path('/path/to/storage')


def test_storage_list(run: Run):
    run.handle(['storage-list', '--format=json'], stdout='["stor/1", "stor/2"]')
    result = hookcmds.storage_list()
    assert result == ['stor/1', 'stor/2']
