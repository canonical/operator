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
import datetime
import json
import pathlib
import subprocess
import uuid
from collections.abc import Generator
from typing import Any, Literal

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


def test_run_error(run: Run):
    run.handle(['juju-log', '--log-level', 'INFO', '--', 'msg'], returncode=1, stderr='error msg')
    with pytest.raises(hookcmds.Error) as excinfo:
        hookcmds.juju_log('msg')
    assert excinfo.value.returncode == 1
    assert excinfo.value.stderr == 'error msg'


def test_action_fail(run: Run):
    run.handle(['action-fail'])
    hookcmds.action_fail()


def test_action_fail_with_message(run: Run):
    run.handle(['action-fail', '--', 'oh no!'])
    hookcmds.action_fail('oh no!')


def test_action_get(run: Run):
    run.handle(['action-get', '--format=json'], stdout='{"foo": "bar"}')
    params = hookcmds.action_get()
    assert params == {'foo': 'bar'}


def test_action_get_key(run: Run):
    run.handle(['action-get', '--format=json', 'baz'], stdout='"qux"')
    param = hookcmds.action_get('baz')
    assert param == 'qux'


def test_action_get_non_string_key(run: Run):
    run.handle(['action-get', '--format=json', 'baz'], stdout='42')
    param = hookcmds.action_get('baz')
    assert param == 42


def test_action_log(run: Run):
    run.handle(['action-log', '--', 'progress update'])
    hookcmds.action_log('progress update')


def test_action_set(run: Run):
    run.handle(['action-set', 'foo=bar', 'baz=qux'])
    hookcmds.action_set({'foo': 'bar', 'baz': 'qux'})


def test_action_set_nested(run: Run):
    run.handle(['action-set', 'foo=bar', 'baz.baz2=qux'])
    hookcmds.action_set({'foo': 'bar', 'baz': {'baz2': 'qux'}})


def test_app_version_set(run: Run):
    run.handle(['application-version-set', '--', '1.2.3'])
    hookcmds.app_version_set('1.2.3')


def test_close_port(run: Run):
    run.handle(['close-port', 'icmp'])
    hookcmds.close_port('icmp')


def test_close_port_endpoints(run: Run):
    run.handle(['close-port', '--endpoints', 'ep1,ep2', '8080/tcp'])
    hookcmds.close_port(protocol='tcp', port=8080, endpoints=['ep1', 'ep2'])


def test_close_port_str_endpoint(run: Run):
    run.handle(['close-port', '--endpoints', 'ep1', '8080/tcp'])
    hookcmds.close_port(protocol='tcp', port=8080, endpoints='ep1')


def test_close_port_single(run: Run):
    run.handle(['close-port', '8080/tcp'])
    hookcmds.close_port(protocol='tcp', port=8080)


def test_close_port_range(run: Run):
    run.handle(['close-port', '8080-8090/tcp'])
    hookcmds.close_port(protocol='tcp', port=8080, to_port=8090)


def test_config_get(run: Run):
    run.handle(['config-get', '--format=json'], stdout='{"foo": "bar"}')
    result = hookcmds.config_get()
    assert result == {'foo': 'bar'}


def test_config_get_key(run: Run):
    run.handle(['config-get', '--format=json', 'baz'], stdout='42')
    result = hookcmds.config_get('baz')
    assert result == 42


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


def test_credential_get_all(run: Run):
    cred = {
        'auth-type': 'certificate',
        'attrs': {'client-cert': 'foo', 'client-key': 'bar', 'server-cert': 'baz'},
        'redacted': ['foo'],
    }
    spec: dict[str, Any] = {
        'type': 'cloud',
        'name': 'test',
        'region': 'pacific',
        'endpoint': 'end',
        'identity-endpoint': 'id-end',
        'storage-endpoint': 'stor-end',
        'credential': cred,
        'cacertificates': ['cert1', 'cert2'],
        'skip-tls-verify': True,
        'is-controller-cloud': True,
    }
    run.handle(['credential-get', '--format=json'], stdout=json.dumps(spec))
    result = hookcmds.credential_get()
    assert result.type == 'cloud'
    assert result.name == 'test'
    assert result.region == 'pacific'
    assert result.endpoint == 'end'
    assert result.identity_endpoint == 'id-end'
    assert result.storage_endpoint == 'stor-end'
    assert result.credential is not None
    assert result.credential.auth_type == 'certificate'
    assert result.credential.attributes == {
        'client-cert': 'foo',
        'client-key': 'bar',
        'server-cert': 'baz',
    }
    assert result.credential.redacted == ['foo']
    assert result.ca_certificates == ['cert1', 'cert2']
    assert result.skip_tls_verify is True
    assert result.is_controller_cloud is True


def test_goal_state(run: Run):
    gs = {
        'units': {'my-unit/0': {'status': 'active', 'since': '2026-01-04 06:29:46Z'}},
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
    run.handle(['juju-log', '--log-level', 'INFO', '--', 'msg'])
    hookcmds.juju_log('msg')


def test_juju_log_level(run: Run):
    run.handle(['juju-log', '--log-level', 'DEBUG', '--', 'debug msg'])
    hookcmds.juju_log('debug msg', level='DEBUG')


def test_juju_reboot(run: Run):
    run.handle(['juju-reboot'])
    hookcmds.juju_reboot()


def test_juju_reboot_now(run: Run, monkeypatch: pytest.MonkeyPatch):
    run.handle(['juju-reboot', '--now'])
    hookcmds.juju_reboot(now=True)


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
    run.handle(['network-get', '--format=json', 'bind'], stdout=json.dumps(net))
    result = hookcmds.network_get('bind')
    assert result.bind_addresses[0].mac_address == 'aa:bb'
    assert result.bind_addresses[0].interface_name == 'eth0'
    assert result.bind_addresses[0].addresses[0].hostname == 'host'
    assert result.bind_addresses[0].addresses[0].value == '127.0.0.1'
    assert result.bind_addresses[0].addresses[0].cidr == '127.0.0.0/24'
    assert result.egress_subnets[0] == '127.0.0.0/24'
    assert result.ingress_addresses[0] == '127.0.0.1'


def test_network_get_relation_id(run: Run):
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
    run.handle(['network-get', '--format=json', '-r', '123', 'bind'], stdout=json.dumps(net))
    hookcmds.network_get('bind', relation_id=123)


def test_open_port(run: Run):
    run.handle(['open-port', 'icmp'])
    hookcmds.open_port('icmp')


def test_open_port_endpoints(run: Run):
    run.handle(['open-port', '--endpoints', 'ep1,ep2', '8080/tcp'])
    hookcmds.open_port(protocol='tcp', port=8080, endpoints=['ep1', 'ep2'])


def test_open_port_str_endpoint(run: Run):
    run.handle(['open-port', '--endpoints', 'ep1', '8080/tcp'])
    hookcmds.open_port(protocol='tcp', port=8080, endpoints='ep1')


def test_open_port_single(run: Run):
    run.handle(['open-port', '8080/tcp'])
    hookcmds.open_port(protocol='tcp', port=8080)


def test_open_port_range(run: Run):
    run.handle(['open-port', '8080-8090/tcp'])
    hookcmds.open_port(protocol='tcp', port=8080, to_port=8090)


def test_opened_ports(run: Run):
    run.handle(
        ['opened-ports', '--format=json'],
        stdout='["8080/tcp", "icmp", "8081-8090/udp", "80"]',
    )
    result = hookcmds.opened_ports()
    assert result[0].port == 8080
    assert result[0].protocol == 'tcp'
    assert result[1].port is None
    assert result[1].protocol == 'icmp'
    assert result[2].port == 8081
    assert result[2].to_port == 8090
    assert result[2].protocol == 'udp'
    assert result[3].port == 80
    assert result[3].protocol == 'tcp'


def test_opened_ports_endpoints(run: Run):
    run.handle(
        ['opened-ports', '--endpoints', '--format=json'],
        stdout='["8080/tcp (ep1,ep2)"]',
    )
    result = hookcmds.opened_ports(endpoints=True)
    assert result[0].port == 8080
    assert result[0].protocol == 'tcp'
    assert result[0].endpoints == ['ep1', 'ep2']


@pytest.mark.parametrize('id', [None, 123])
@pytest.mark.parametrize('app', [False, True])
@pytest.mark.parametrize('unit', [None, 'myapp/0'])
def test_relation_get(run: Run, id: int | None, app: bool, unit: str | None):
    cmd = ['relation-get', '--format=json']
    if id:
        cmd.extend(['-r', str(id)])
    if app:
        cmd.append('--app')
    if unit:
        cmd.extend(['-', unit])
    run.handle(cmd, stdout='{"foo": "bar"}')
    result = hookcmds.relation_get(id=id, app=app, unit=unit)
    assert result == {'foo': 'bar'}


@pytest.mark.parametrize('id', [None, 123])
@pytest.mark.parametrize('app', [False, True])
@pytest.mark.parametrize('unit', [None, 'myapp/0'])
def test_relation_get_key(run: Run, id: int | None, app: bool, unit: str | None):
    cmd = ['relation-get', '--format=json']
    if id:
        cmd.extend(['-r', str(id)])
    if app:
        cmd.append('--app')
    if unit:
        cmd.extend(['baz', unit])
    else:
        cmd.append('baz')
    run.handle(cmd, stdout='"qux"')
    result = hookcmds.relation_get(key='baz', id=id, app=app, unit=unit)
    assert result == 'qux'


def test_relation_get_dash():
    with pytest.raises(ValueError):
        hookcmds.relation_get(key='-')


def test_relation_ids(run: Run):
    run.handle(['relation-ids', 'db', '--format=json'], stdout='["rel:1"]')
    result = hookcmds.relation_ids('db')
    assert result == ['rel:1']


@pytest.mark.parametrize('id', [None, 123])
@pytest.mark.parametrize('app', [False, True])
def test_relation_list(run: Run, id: int | None, app: bool):
    cmd = ['relation-list', '--format=json']
    if app:
        cmd.append('--app')
    if id is not None:
        cmd.extend(['-r', str(id)])
    run.handle(cmd, stdout='["unit/0"]')
    result = hookcmds.relation_list(id=id, app=app)
    assert result == ['unit/0']


@pytest.mark.parametrize('id', [None, 123])
def test_relation_model_get(run: Run, id: int | None):
    data = {'uuid': str(uuid.uuid4())}
    cmd = ['relation-model-get', '--format=json']
    if id is not None:
        cmd.extend(['-r', str(id)])
    run.handle(cmd, stdout=json.dumps(data))
    result = hookcmds.relation_model_get(id=id)
    assert str(result.uuid) == data['uuid']


@pytest.mark.parametrize('id', [None, 123])
@pytest.mark.parametrize('app', [False, True])
def test_relation_set(run: Run, mock_file: NamedTemporaryFile, id: int | None, app: bool):
    cmd = ['relation-set']
    if id is not None:
        cmd.extend(['-r', str(id)])
    if app:
        cmd.append('--app')
    cmd.extend(['--file', '-'])
    run.handle(cmd)
    hookcmds.relation_set({'foo': 'bar'}, id=id, app=app)
    assert run.calls[0].stdin == '{"foo": "bar"}'


def test_resource_get(run: Run):
    run.handle(['resource-get', 'res'], stdout='/path/to/resource')
    result = hookcmds.resource_get('res')
    assert str(result) == '/path/to/resource'


def test_secret_add(run: Run, mock_temp_dir: str):
    run.handle(
        ['secret-add', '--owner', 'application', f'foo#file={mock_temp_dir}/foo'],
        stdout='secretid',
    )
    result = hookcmds.secret_add({'foo': 'bar'})
    assert result == 'secretid'


@pytest.mark.parametrize('owner', ['application', 'unit'])
def test_secret_add_with_metadata(
    run: Run, mock_temp_dir: str, owner: Literal['application', 'unit']
):
    run.handle(
        [
            'secret-add',
            '--label',
            'mylabel',
            '--description',
            'mydesc',
            '--expire',
            '3d',
            '--rotate',
            'quarterly',
            '--owner',
            owner,
            f'foo#file={mock_temp_dir}/foo',
        ],
        stdout='secretid',
    )
    result = hookcmds.secret_add(
        {'foo': 'bar'},
        label='mylabel',
        description='mydesc',
        expire='3d',
        rotate='quarterly',
        owner=owner,
    )
    assert result == 'secretid'


def test_secret_add_date(run: Run, mock_temp_dir: str):
    run.handle(
        [
            'secret-add',
            '--expire',
            '2025-12-31T23:59:59Z',
            '--owner',
            'application',
            f'foo#file={mock_temp_dir}/foo',
        ],
        stdout='secretid',
    )
    result = hookcmds.secret_add(
        {'foo': 'bar'},
        expire=datetime.datetime(2025, 12, 31, 23, 59, 59, tzinfo=datetime.timezone.utc),
    )
    assert result == 'secretid'


@pytest.mark.parametrize('peek,refresh', [(False, False), (False, True), (True, False)])
def test_secret_get_by_id(run: Run, peek: bool, refresh: bool):
    cmd = ['secret-get', '--format=json', 'secret:123']
    if peek:
        cmd.append('--peek')
    if refresh:
        cmd.append('--refresh')
    run.handle(cmd, stdout='{"foo": "bar"}')
    # The type: ignore is needed here, because pyright can't tell that we will
    # not be passing both values as True (which would be invalid).
    result = hookcmds.secret_get(id='secret:123', peek=peek, refresh=refresh)  # type: ignore
    assert result == {'foo': 'bar'}


@pytest.mark.parametrize('peek,refresh', [(False, False), (False, True), (True, False)])
def test_secret_get_by_label(run: Run, peek: bool, refresh: bool):
    cmd = ['secret-get', '--format=json', '--label', 'lbl']
    if peek:
        cmd.append('--peek')
    if refresh:
        cmd.append('--refresh')
    run.handle(cmd, stdout='{"foo": "bar"}')
    # The type: ignore is needed here, because pyright can't tell that we will
    # not be passing both values as True (which would be invalid).
    result = hookcmds.secret_get(label='lbl', peek=peek, refresh=refresh)  # type: ignore
    assert result == {'foo': 'bar'}


@pytest.mark.parametrize('peek,refresh', [(False, False), (False, True), (True, False)])
def test_secret_get_set_label(run: Run, peek: bool, refresh: bool):
    cmd = ['secret-get', '--format=json', 'secret:123', '--label', 'lbl']
    if peek:
        cmd.append('--peek')
    if refresh:
        cmd.append('--refresh')
    run.handle(cmd, stdout='{"foo": "bar"}')
    result = hookcmds.secret_get(id='secret:123', label='lbl', peek=peek, refresh=refresh)  # type: ignore
    assert result == {'foo': 'bar'}


def test_secret_grant(run: Run):
    run.handle(['secret-grant', '--relation', '1', 'id'])
    hookcmds.secret_grant('id', 1)


def test_secret_grant_unit(run: Run):
    run.handle(['secret-grant', '--relation', '1', '--unit', 'myapp/0', 'id'])
    hookcmds.secret_grant('id', 1, unit='myapp/0')


def test_secret_ids(run: Run):
    run.handle(['secret-ids', '--format=json'], stdout='["id1", "id2"]')
    result = hookcmds.secret_ids()
    assert result == ['id1', 'id2']


def test_secret_info_get_id(run: Run):
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


def test_secret_info_get_label(run: Run):
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
    run.handle(['secret-info-get', '--format=json', '--label', 'lbl'], stdout=json.dumps(info))
    result = hookcmds.secret_info_get(label='lbl')
    assert result.id == '123'
    assert result.label == 'lbl'


def test_secret_remove(run: Run):
    run.handle(['secret-remove', 'id'])
    hookcmds.secret_remove('id')


def test_secret_remove_revision(run: Run):
    run.handle(['secret-remove', 'id', '--revision', '2'])
    hookcmds.secret_remove('id', revision=2)


@pytest.mark.parametrize('relation_id', [None, 123])
@pytest.mark.parametrize('app', [None, 'remote-app'])
@pytest.mark.parametrize('unit', [None, 'myapp/0'])
def test_secret_revoke(run: Run, relation_id: int | None, app: str | None, unit: str | None):
    cmd = ['secret-revoke']
    if relation_id is not None:
        cmd.extend(['--relation', str(relation_id)])
    if app is not None:
        cmd.extend(['--app', app])
    if unit is not None:
        cmd.extend(['--unit', unit])
    cmd.append('secret:id')
    run.handle(cmd)
    hookcmds.secret_revoke('secret:id', relation_id=relation_id, app=app, unit=unit)


def test_secret_set(run: Run, mock_temp_dir: str):
    run.handle([
        'secret-set',
        '--owner',
        'application',
        'secret:123',
        f'foo#file={mock_temp_dir}/foo',
    ])
    hookcmds.secret_set('secret:123', content={'foo': 'bar'})


@pytest.mark.parametrize('owner', ['application', 'unit'])
def test_secret_set_with_metadata(
    run: Run, mock_temp_dir: str, owner: Literal['application', 'unit']
):
    run.handle(
        [
            'secret-set',
            '--label',
            'mylabel',
            '--description',
            'mydesc',
            '--expire',
            '3d',
            '--rotate',
            'quarterly',
            '--owner',
            owner,
            'secret:id',
            f'foo#file={mock_temp_dir}/foo',
        ],
        stdout='secretid',
    )
    hookcmds.secret_set(
        'secret:id',
        content={'foo': 'bar'},
        label='mylabel',
        description='mydesc',
        expire='3d',
        rotate='quarterly',
        owner=owner,
    )


def test_secret_set_date(run: Run, mock_temp_dir: str):
    run.handle(
        [
            'secret-set',
            '--expire',
            '2025-12-31T23:59:59Z',
            '--owner',
            'application',
            'secret:id',
            f'foo#file={mock_temp_dir}/foo',
        ],
        stdout='secretid',
    )
    hookcmds.secret_set(
        'secret:id',
        content={'foo': 'bar'},
        expire=datetime.datetime(2025, 12, 31, 23, 59, 59, tzinfo=datetime.timezone.utc),
    )


def test_state_delete(run: Run):
    run.handle(['state-delete', 'foo'])
    hookcmds.state_delete('foo')


def test_state_get(run: Run):
    run.handle(['state-get', '--format=json'], stdout='{"foo": "bar"}')
    result = hookcmds.state_get(None)
    assert result == {'foo': 'bar'}


def test_state_get_key(run: Run):
    run.handle(['state-get', '--format=json', 'foo'], stdout='"bar"')
    result = hookcmds.state_get('foo')
    assert result == 'bar'


def test_state_set(run: Run):
    run.handle(['state-set', '--file', '-'])
    hookcmds.state_set({'foo': 'bar'})


def test_status_get_unit(run: Run):
    unit: hookcmds._types.StatusDict = {'status': 'active', 'message': 'ok', 'status-data': {}}
    run.handle(
        ['status-get', '--include-data', '--format=json', '--application=false'],
        stdout=json.dumps(unit),
    )
    result = hookcmds.status_get(app=False)
    assert result.status == 'active'


def test_status_get_app(run: Run):
    app: hookcmds._types.AppStatusDict = {
        'application-status': {
            'message': 'all good',
            'status': 'active',
            'status-data': {},
        },
        'units': {
            'myapp/0': {'status': 'active', 'message': 'ok', 'status-data': {}},
        },
    }
    run.handle(
        ['status-get', '--include-data', '--format=json', '--application=true'],
        stdout=json.dumps(app),
    )
    result = hookcmds.status_get(app=True)
    assert result.status == 'active'
    assert result.message == 'all good'
    assert tuple(result.units) == ('myapp/0',)
    assert result.units['myapp/0'].status == 'active'
    assert result.units['myapp/0'].message == 'ok'


def test_status_set(run: Run):
    run.handle(['status-set', '--application=False', 'active', '--', 'msg'])
    hookcmds.status_set('active', 'msg')


def test_status_set_app(run: Run):
    run.handle(['status-set', '--application=True', 'active', '--', 'msg'])
    hookcmds.status_set('active', 'msg', app=True)


def test_status_set_no_message(run: Run):
    run.handle(['status-set', '--application=False', 'waiting'])
    hookcmds.status_set('waiting')


def test_storage_add(run: Run):
    run.handle(['storage-add', 'foo=1'])
    hookcmds.storage_add({'foo': 1})


def test_storage_add_multiple(run: Run):
    run.handle(['storage-add', 'foo=99'])
    hookcmds.storage_add({'foo': 99})


def test_storage_add_multiple_storages(run: Run):
    run.handle(['storage-add', 'foo=2', 'bar=3'])
    hookcmds.storage_add({'foo': 2, 'bar': 3})


def test_storage_get(run: Run):
    storage = {'kind': 'block', 'location': '/path/to/storage'}
    run.handle(['storage-get', '--format=json'], stdout=json.dumps(storage))
    result = hookcmds.storage_get()
    assert result.kind == 'block'
    assert result.location == pathlib.Path('/path/to/storage')


def test_storage_get_id(run: Run):
    storage = {'kind': 'block', 'location': '/path/to/storage'}
    run.handle(['storage-get', '--format=json', '-s', 'stor/1'], stdout=json.dumps(storage))
    result = hookcmds.storage_get('stor/1')
    assert result.kind == 'block'
    assert result.location == pathlib.Path('/path/to/storage')


def test_storage_list(run: Run):
    run.handle(['storage-list', '--format=json'], stdout='["stor/1", "stor/2"]')
    result = hookcmds.storage_list()
    assert result == ['stor/1', 'stor/2']


def test_storage_list_named(run: Run):
    run.handle(['storage-list', '--format=json', 'stor'], stdout='["stor/1", "stor/2"]')
    result = hookcmds.storage_list('stor')
    assert result == ['stor/1', 'stor/2']


@pytest.mark.parametrize(
    'timestamp,expected',
    [
        # Juju 3.6 format (no fractional seconds)
        (
            '2026-01-05T23:28:38Z',
            datetime.datetime(2026, 1, 5, 23, 28, 38, tzinfo=datetime.timezone.utc),
        ),
        # Juju 4.0 format (8 digits)
        (
            '2026-01-05T23:34:25.50029526Z',
            datetime.datetime(2026, 1, 5, 23, 34, 25, 500295, tzinfo=datetime.timezone.utc),
        ),
        # 5 digits (reported in https://github.com/canonical/operator/issues/2263)
        (
            '2026-04-10T18:34:45.65844+00:00',
            datetime.datetime(2026, 4, 10, 18, 34, 45, 658440, tzinfo=datetime.timezone.utc),
        ),
        # Edge case: 1 digit
        (
            '2026-01-05T23:34:25.1Z',
            datetime.datetime(2026, 1, 5, 23, 34, 25, 100000, tzinfo=datetime.timezone.utc),
        ),
        # Edge case: 9 digits (nanosecond precision)
        (
            '2026-01-05T23:34:25.123456789Z',
            datetime.datetime(2026, 1, 5, 23, 34, 25, 123457, tzinfo=datetime.timezone.utc),
        ),
    ],
)
def test_secret_expiry_formats(timestamp: str, expected: datetime.datetime):
    secret_info = hookcmds.SecretInfo._from_dict({'test-id': {'revision': 1, 'expiry': timestamp}})
    assert secret_info.id == 'test-id'
    assert secret_info.revision == 1
    assert secret_info.expiry == expected
