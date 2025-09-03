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

"""Low-level access to the Juju hook commands.

Charm authors should use the :class:`ops.Model` (via ``self.model``) rather than
directly running the hook commands, where possible. This module is primarily
provided to help with developing charming alternatives to the Ops framework.

All methods are 1:1 mapping to Juju hook commands. This is a *low-level* API,
available for charm use, but expected to be used via higher-level wrappers.

See https://documentation.ubuntu.com/juju/3.6/reference/hook-command/ and
https://documentation.ubuntu.com/juju/3.6/reference/hook-command/list-of-hook-commands/
for a list of all Juju hook commands.
"""

from __future__ import annotations

import dataclasses
import datetime
import enum
import ipaddress
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import uuid
from typing import (
    Any,
    Literal,
    Mapping,
    MutableMapping,
    Sequence,
    TypeAlias,
    TypedDict,
    cast,
    overload,
)

from ._private import yaml as _yaml


class Error(Exception):
    """Raised when a hook command exits with a non-zero code."""

    returncode: int
    """Exit status of the child process."""

    cmd: list[str]
    """The full command that was run."""

    stdout: str = ''
    """Stdout output of the child process."""

    stderr: str = ''
    """Stderr output of the child process."""

    def __init__(self, *, returncode: int, cmd: list[str], stdout: str = '', stderr: str = ''):
        self.returncode = returncode
        self.cmd = cmd
        self.stdout = stdout
        self.stderr = stderr
        super().__init__(f'command {cmd!r} exited with status {returncode}')


class SecretRotate(enum.Enum):
    """Secret rotation policies."""

    NEVER = 'never'  # the default in juju
    HOURLY = 'hourly'
    DAILY = 'daily'
    WEEKLY = 'weekly'
    MONTHLY = 'monthly'
    QUARTERLY = 'quarterly'
    YEARLY = 'yearly'


SettableStatusName = Literal['active', 'blocked', 'maintenance', 'waiting']
_ReadOnlyStatusName = Literal['error', 'unknown']
StatusName: TypeAlias = 'SettableStatusName | _ReadOnlyStatusName'


class _AddressDict(TypedDict):
    hostname: str
    value: str
    cidr: str


@dataclasses.dataclass(frozen=True, kw_only=True)
class Address:
    """A Juju space address, found in :class:`BindAddress` objects."""

    hostname: str
    value: ipaddress.IPv4Address | ipaddress.IPv6Address
    cidr: ipaddress.IPv4Network | ipaddress.IPv6Network


_BindAddressDict = TypedDict(
    '_BindAddressDict',
    {'mac-address': str, 'interface-name': str, 'addresses': list[dict[str, str]]},
)


@dataclasses.dataclass(frozen=True, kw_only=True)
class BindAddress:
    """A Juju space bind address, found in :class:`Network` objects."""

    mac_address: str
    interface_name: str
    addresses: list[Address] = dataclasses.field(default_factory=list[Address])


@dataclasses.dataclass(frozen=True, kw_only=True)
class CloudCredential:
    """Credentials to directly interact with a Juju cloud, found in :class:`CloudSpec` objects."""

    auth_type: str
    attrs: dict[str, str] = dataclasses.field(default_factory=dict[str, str])
    redacted: list[str] = dataclasses.field(default_factory=list[str])


@dataclasses.dataclass(frozen=True, kw_only=True)
class CloudSpec:
    """Details about the Juju cloud the charm is deployed to."""

    type: str
    name: str
    region: str | None = None
    endpoint: str | None = None
    identity_endpoint: str | None = None
    storage_endpoint: str | None = None
    credential: CloudCredential | None = None
    ca_certificates: list[str] = dataclasses.field(default_factory=list[str])
    skip_tls_verify: bool = False
    is_controller_cloud: bool = False


class _GoalDict(TypedDict):
    status: str
    since: str


class _GoalStateDict(TypedDict):
    units: dict[str, _GoalDict]
    relations: dict[str, dict[str, _GoalDict]]


@dataclasses.dataclass(frozen=True, kw_only=True)
class Goal:
    """A goal status and when it was last updated, found in :class:`GoalState` objects."""

    status: str
    since: datetime.datetime


@dataclasses.dataclass(frozen=True, kw_only=True)
class GoalState:
    """The units and relations that the model should have, and the status of achieving that."""

    units: dict[str, Goal]
    # The top key is the endpoint/relation name, the second key is the app/unit name.
    relations: dict[str, dict[str, Goal]]


@dataclasses.dataclass(frozen=True, kw_only=True)
class Network:
    """A Juju space."""

    bind_addresses: Sequence[BindAddress]
    egress_subnets: Sequence[ipaddress.IPv4Network | ipaddress.IPv6Network]
    ingress_addresses: Sequence[ipaddress.IPv4Address | ipaddress.IPv6Address]


@dataclasses.dataclass(frozen=True, kw_only=True)
class Port:
    """A port that Juju has opened for the charm."""

    protocol: Literal['tcp', 'udp', 'icmp'] | None
    port: int | None
    to_port: int | None


class _RelationModelDict(TypedDict):
    uuid: str


@dataclasses.dataclass(frozen=True, kw_only=True)
class RelationModel:
    """Details of the model on the remote side of the relation."""

    uuid: uuid.UUID


@dataclasses.dataclass(frozen=True, kw_only=True)
class SecretInfo:
    """Metadata for Juju secrets."""

    revision: int
    id: str = ''
    label: str = ''
    description: str = ''
    expiry: datetime.datetime | None = None
    rotation: SecretRotate | None = None
    rotates: datetime.datetime | None = None


@dataclasses.dataclass(frozen=True, kw_only=True)
class Storage:
    """Metadata for Juju storage."""

    kind: str
    location: pathlib.Path


_UnitStatusDict = TypedDict(
    '_UnitStatusDict', {'message': str, 'status': str, 'status-data': dict[str, Any]}
)
_AppStatusDict = TypedDict(
    '_AppStatusDict',
    {
        'message': str,
        'status': str,
        'status-data': dict[str, Any],
        'units': dict[str, _UnitStatusDict],
    },
)


@dataclasses.dataclass(frozen=True, kw_only=True)
class UnitStatus:
    """The status of a Juju unit."""

    status: str = ''
    message: str = ''
    status_data: dict[str, Any]


@dataclasses.dataclass(frozen=True, kw_only=True)
class AppStatus:
    """The status of a Juju application."""

    status: str = ''
    message: str = ''
    status_data: dict[str, Any]
    units: dict[str, UnitStatus]


@overload
def _run(
    *args: str,
    return_output: Literal[True],
    use_json: Literal[False] = False,
    input_stream: str | None = None,
) -> str: ...
@overload
def _run(
    *args: str,
    return_output: Literal[True],
    use_json: Literal[True] = True,
    input_stream: str | None = None,
) -> Any: ...
@overload
def _run(
    *args: str,
    return_output: Literal[False] = False,
    input_stream: str | None = None,
) -> None: ...
def _run(
    *args: str,
    return_output: bool = False,
    use_json: bool = False,
    input_stream: str | None = None,
) -> str | Any | None:
    kwargs = {
        'capture_output': True,
        'check': True,
        'encoding': 'utf-8',
    }
    if input_stream:
        kwargs.update({'input': input_stream})
    which_cmd = shutil.which(args[0])
    if which_cmd is None:
        raise RuntimeError(f'command not found: {args[0]}')
    args = (which_cmd,) + args[1:]
    if use_json:
        args += ('--format=json',)
    try:
        result = subprocess.run(args, **kwargs)  # type: ignore
    except subprocess.CalledProcessError as e:
        raise Error(returncode=e.returncode, cmd=e.cmd, stdout=e.stdout, stderr=e.stderr) from None
    if not return_output:
        return
    if result.stdout is None:  # type: ignore
        return ''
    text: str = result.stdout  # type: ignore
    if use_json:
        return json.loads(text)  # type: ignore
    return text  # type: ignore


def _format_action_result_dict(
    input: Mapping[str, Any],
    parent_key: str | None = None,
    output: dict[str, str] | None = None,
) -> dict[str, str]:
    """Turn a nested dictionary into a flattened dictionary, using '.' as a key separator.

    This is used to allow nested dictionaries to be translated into the dotted
    format required by the Juju `action-set` hook command in order to set nested
    data on an action.

    Example::

        >>> test_dict = {'a': {'b': 1, 'c': 2}}
        >>> _format_action_result_dict(test_dict)
        {'a.b': 1, 'a.c': 2}

    Arguments:
        input: The dictionary to flatten
        parent_key: The string to prepend to dictionary's keys
        output: The current dictionary to be returned, which may or may not yet
            be completely flat

    Returns:
        A flattened dictionary

    Raises:
        ValueError: if the dict is passed with a mix of dotted/non-dotted keys
            that expand out to result in duplicate keys. For example:
            ``{'a': {'b': 1}, 'a.b': 2}``.
    """
    output_: dict[str, str] = output or {}

    for key, value in input.items():
        if parent_key:
            key = f'{parent_key}.{key}'

        if isinstance(value, MutableMapping):
            value = cast('dict[str, Any]', value)
            output_ = _format_action_result_dict(value, key, output_)
        elif key in output_:
            raise ValueError(
                f"duplicate key detected in dictionary passed to 'action-set': {key!r}"
            )
        else:
            output_[key] = value

    return output_


def action_fail(message: str | None = None):
    """Set action fail status with message."""
    args = ['action-fail']
    if message is not None:
        args.append(message)
    _run(*args)


@overload
def action_get() -> dict[str, Any]: ...
@overload
def action_get(key: str) -> str: ...
def action_get(key: str | None = None) -> dict[str, Any] | str:
    """Get action parameters.

    ``action_get`` returns the value of the parameter at the given key. If a
    dotted key (for example foo.bar) is passed, ``action_get`` will recurse into
    the parameter map as needed.
    """
    args = ['action-get']
    if key is not None:
        args.append(key)
    out = _run(*args, return_output=True, use_json=True)
    return cast('dict[str, Any]', out) if key is None else cast('str', out)


def action_log(message: str):
    """Record a progress message for the current action."""
    _run('action-log', message)


def action_set(results: Mapping[str, Any]):
    """Set action results."""
    # The Juju action-set hook tool cannot interpret nested dicts, so we use a
    # helper to flatten out any nested dict structures into a dotted notation.
    flat_results = _format_action_result_dict(results)
    _run('action-set', *[f'{k}={v}' for k, v in flat_results.items()])


def application_version_set(version: str):
    """Specify which version of the application is deployed."""
    _run('application-version-set', version)


def close_port(
    protocol: str | None = None,
    port: int | None = None,
    *,
    to_port: int | None = None,
    endpoints: str | list[str],
):
    """Register a request to close a port or port range."""
    args = ['close-port']
    if endpoints:
        if isinstance(endpoints, str):
            endpoints = [endpoints]
        args.extend(['--endpoints', ','.join(endpoints)])
    if protocol is None and port is None:
        raise ValueError('Either protocol or port must be specified')
    if port is None:
        assert protocol is not None
        args.append(protocol)
    else:
        port_arg = f'{port}-{to_port}' if to_port is not None else str(port)
        if protocol is not None:
            port_arg = f'{port_arg}/{protocol}'
        args.append(port_arg)
    _run(*args)


@overload
def config_get(key: str, all: Literal[False]) -> bool | int | float | str: ...
@overload
def config_get(key: None = None, all: bool = False) -> Mapping[str, bool | int | float | str]: ...
def config_get(
    key: str | None = None,
    all: bool = False,  # noqa: A002 - we're ok shadowing the builtin here.
) -> Mapping[str, bool | int | float | str] | bool | int | float | str:
    """Retrieve application configuration.

    Note that 'secret' type options are returned as string secret IDs.
    """
    args = ['config-get']
    if key is not None and all:
        raise ValueError("Cannot specify both 'key' and 'all'")
    if all:
        args.append('--all')
    if key:
        args.append(key)
    out = _run(*args, return_output=True, use_json=True)
    if key:
        return cast('bool | int | float | str', out)
    return cast('dict[str, bool | int | float | str]', out)


def credential_get() -> CloudSpec:
    """Access cloud credentials."""
    result = _run('credential-get', return_output=True, use_json=True)
    return CloudSpec(**cast('dict[str, Any]', result))


def goal_state() -> GoalState:
    """Print the status of the charm's peers and related units."""
    result = _run('goal-state', return_output=True, use_json=True)
    result = cast('_GoalStateDict', result)
    units: dict[str, Goal] = {}
    for name, unit in result.get('units', {}).items():
        since = datetime.datetime.fromisoformat(unit['since'])
        units[name] = Goal(since=since, status=unit['status'])
    relations: dict[str, dict[str, Goal]] = {}
    for name, relation in result.get('relations', {}).items():
        goals: dict[str, Goal] = {}
        for app_or_unit, data in relation.items():
            since = datetime.datetime.fromisoformat(data['since'])
            goals[app_or_unit] = Goal(since=since, status=data['status'])
        relations[name] = goals
    return GoalState(units=units, relations=relations)


def is_leader() -> bool:
    """Obtain the current leadership status for the unit the charm code is executing on.

    The value is not cached. It is accurate for 30s from the time the method is
    successfully called.
    """
    leader = _run('is-leader', return_output=True, use_json=True)
    return cast('bool', leader)


def juju_log(message: str, level: str = 'INFO'):
    """Write a message to the juju log."""
    _run('juju-log', '--log-level', level, message)


def juju_reboot(now: bool = False):
    """Reboot the host machine."""
    if now:
        _run('juju-reboot', '--now')
        # Juju will kill this process, but to avoid races we force that to be the case.
        sys.exit()
    _run('juju-reboot')


# We could have bind_address: bool=True, egress_subnets: bool=True,
# --ingress-address: bool=True, and could even return just that data if only one
# is specified. However, it seems like it's unlikely there would be a lot of data
# here, and that it's unlikely to be much faster to only get one, so the API is
# a lot simpler if we only support getting all at once (which is the behaviour
# when none of those arguments are specified).
def network_get(binding_name: str, relation_id: int | None = None) -> Network:
    """Get network config.

    Args:
        binding_name: A name of a binding (relation name or extra-binding name).
        relation_id: An optional relation id to get network info for.
    """
    args = ['network-get']
    if relation_id is not None:
        args.extend(['-r', str(relation_id)])
    args.append(binding_name)
    result = cast('dict[str, Any]', _run(*args, return_output=True, use_json=True))
    bind: list[BindAddress] = []
    for bind_data in cast('list[_BindAddressDict]', result['bind-addresses']):
        raw_bind_addresses = [
            cast('_AddressDict', addr) for addr in bind_data.get('addresses', [])
        ]
        bind_addresses = [
            Address(
                hostname=addr['hostname'],
                value=ipaddress.ip_address(addr['value']),
                cidr=ipaddress.ip_network(addr['cidr']),
            )
            for addr in raw_bind_addresses
        ]
        bind.append(
            BindAddress(
                mac_address=bind_data['mac-address'],
                interface_name=bind_data['interface-name'],
                addresses=bind_addresses,
            )
        )
    egress = [ipaddress.ip_network(addr) for addr in result.get('egress-subnets', [])]
    ingress = [ipaddress.ip_address(addr) for addr in result.get('ingress-addresses', [])]
    return Network(bind_addresses=bind, egress_subnets=egress, ingress_addresses=ingress)


def open_port(
    protocol: str | None = None,
    port: int | None = None,
    *,
    to_port: int | None = None,
    endpoints: str | list[str],
):
    """Register a request to open a port or port range."""
    args = ['open-port']
    if endpoints:
        if isinstance(endpoints, str):
            endpoints = [endpoints]
        args.extend(['--endpoints', ','.join(endpoints)])
    if protocol is None and port is None:
        raise ValueError('Either protocol or port must be specified')
    if port is None:
        assert protocol is not None
        args.append(protocol)
    else:
        port_arg = f'{port}-{to_port}' if to_port is not None else str(port)
        if protocol is not None:
            port_arg = f'{port_arg}/{protocol}'
        args.append(port_arg)
    _run(*args)


def opened_ports(endpoints: bool = False) -> list[Port]:
    """List all ports or port ranges opened by the unit."""
    args = ['opened-ports']
    if endpoints:
        args.append('--endpoints')
    output = cast('list[str]', _run(*args, return_output=True, use_json=True))
    ports: list[Port] = []
    for port in output:
        if '/' in port:
            port, protocol = port.split('/', 1)
        else:
            protocol = None
        if '-' in port:
            port, to_port = port.split('-')
            to_port = int(to_port)
        else:
            to_port = None
        if port == 'icmp':
            protocol = port
            port = None
        else:
            port = int(port)
        assert protocol in ('tcp', 'udp', 'icmp')
        ports.append(Port(protocol=protocol, port=port, to_port=to_port))
    return ports


@overload
def relation_get(
    id: int | None = None,
    *,
    unit: str | None = None,
    app: bool = False,
) -> dict[str, str]: ...
@overload
def relation_get(
    id: int | None = None,
    *,
    key: str,
    unit: str | None = None,
    app: bool = False,
) -> str: ...
def relation_get(
    id: int | None = None,
    *,
    key: str | None = None,
    unit: str | None = None,
    app: bool = False,
) -> dict[str, str] | str:
    """Get relation settings.

    Note that ``id`` can only be ``None`` if the current hook is a relation
    event, in which case Juju will use the ID of the relation that triggered the
    event.
    """
    args = ['relation-get']
    if id is not None:
        args.extend(['-r', str(id)])
    if app:
        args.append('--app')
    if key is not None:
        args.append(key)
    if unit is not None:
        args.append(unit)
    result = _run(*args, return_output=True, use_json=True)
    if key is not None:
        return cast('str', result)
    return cast('dict[str, str]', result)


def relation_ids(name: str) -> list[str]:
    """List all relation IDs for the given endpoint."""
    result = _run('relation-ids', name, return_output=True, use_json=True)
    return cast('list[str]', result)


def relation_list(id: int | None = None, *, app: bool = False) -> list[str]:
    """List relation units.

    Note that ``id`` can only be ``None`` if the current hook is a relation
    event, in which case Juju will use the ID of the relation that triggered the
    event.
    """
    args = ['relation-list']
    if app:
        args.append('--app')
    if id is not None:
        args.extend(['-r', str(id)])
    result = _run(*args, return_output=True, use_json=True)
    return cast('list[str]', result)


def relation_model_get(id: int | None = None) -> RelationModel:
    """Get details about the model hosting a related application.

    Note that ``id`` can only be ``None`` if the current hook is a relation
    event, in which case Juju will use the ID of the relation that triggered the
    event.
    """
    args = ['relation-model-get']
    if id is not None:
        args.extend(['-r', str(id)])
    result = cast('_RelationModelDict', _run(*args, return_output=True, use_json=True))
    return RelationModel(uuid=uuid.UUID(result['uuid']))


def relation_set(
    data: Mapping[str, str],
    id: int | None = None,
    *,
    app: bool = False,
    file: pathlib.Path | None = None,
):
    """Set relation settings.

    Note that ``id`` can only be ``None`` if the current hook is a relation
    event, in which case Juju will use the ID of the relation that triggered the
    event.
    """
    args = ['relation-set']
    if app:
        args.append('--app')
    if id is not None:
        args.extend(['-r', str(id)])
    if file is not None:
        data = dict(data)
        with open(file) as f:
            data.update(_yaml.safe_load(f))
    args.extend(['--file', '-'])
    content = _yaml.safe_dump(data)
    _run(*args, input_stream=content)


def resource_get(name: str) -> pathlib.Path:
    """Get the path to the locally cached resource file."""
    out = _run('resource-get', name, return_output=True)
    return pathlib.Path(out.strip())


def secret_add(
    content: dict[str, str],
    *,
    label: str | None = None,
    description: str | None = None,
    expire: datetime.datetime | None = None,
    rotate: SecretRotate | None = None,
    owner: str | None = None,
) -> str:
    """Add a new secret."""
    args: list[str] = []
    if label is not None:
        args.extend(['--label', label])
    if description is not None:
        args.extend(['--description', description])
    if expire is not None:
        args.extend(['--expire', expire.isoformat()])
    if rotate is not None:
        args.extend(['--rotate', rotate.value])
    if owner is not None:
        args.extend(['--owner', owner])
    with tempfile.TemporaryDirectory() as tmp:
        for k, v in content.items():
            with open(f'{tmp}/{k}', mode='w', encoding='utf-8') as f:
                f.write(v)
            args.append(f'{k}#file={tmp}/{k}')
        result = _run('secret-add', *args, return_output=True)
    return result.strip()


@overload
def secret_get(
    *,
    id: str,
    refresh: bool = False,
    peek: bool = False,
) -> dict[str, str]: ...
@overload
def secret_get(
    *,
    label: str,
    refresh: bool = False,
    peek: bool = False,
) -> dict[str, str]: ...
def secret_get(
    *,
    id: str | None = None,
    label: str | None = None,
    refresh: bool = False,
    peek: bool = False,
) -> dict[str, str]:
    """Get the content of a secret."""
    args: list[str] = []
    if id is not None:
        args.append(id)
    if label is not None:
        args.extend(['--label', label])
    if refresh:
        args.append('--refresh')
    if peek:
        args.append('--peek')
    result = _run('secret-get', *args, return_output=True, use_json=True)
    return cast('dict[str, str]', result)


def secret_grant(id: str, relation_id: int, *, unit: str | None = None):
    """Grant access to a secret."""
    args = ['secret-grant', '--relation', str(relation_id)]
    if unit is not None:
        args += ['--unit', str(unit)]
    args.append(id)
    _run(*args)


def secret_ids() -> list[str]:
    """Retrieve IDs for secrets owned by the application."""
    result = _run('secret-ids', return_output=True, use_json=True)
    return cast('list[str]', result)


@overload
def secret_info_get(
    *,
    id: str,
) -> SecretInfo: ...
@overload
def secret_info_get(
    *,
    label: str,
) -> SecretInfo: ...
def secret_info_get(*, id: str | None = None, label: str | None = None) -> SecretInfo:
    """Get a secret's metadata info."""
    args: list[str] = ['secret-info-get']
    if id is not None:
        args.append(id)
    elif label is not None:  # elif because Juju secret-info-get doesn't allow id and label
        args.extend(['--label', label])
    result = _run(*args, return_output=True, use_json=True)
    info_dicts = cast('dict[str, Any]', result)
    id, data = next(iter(info_dicts.items()))  # Juju returns dict of {secret_id: {info}}
    return SecretInfo(
        id=id,
        label=data.get('label'),
        description=data.get('description'),
        expiry=datetime.datetime.fromisoformat(data['expiry']) if data.get('expiry') else None,
        rotation=SecretRotate(data['rotation']) if data.get('rotation') else None,
        rotates=datetime.datetime.fromisoformat(data['rotates']) if data.get('rotates') else None,
        revision=data['revision'],
    )


def secret_remove(id: str, *, revision: int | None = None):
    """Remove an existing secret."""
    args = ['secret-remove', id]
    if revision is not None:
        args.extend(['--revision', str(revision)])
    _run(*args)


def secret_revoke(id: str, *, relation_id: int | None, app: str | None, unit: str | None = None):
    """Revoke access to a secret."""
    args = ['secret-revoke']
    if relation_id is not None:
        args.extend(['--relation', str(relation_id)])
    if app is not None:
        args.extend(['--app', app])
    if unit is not None:
        args.extend(['--unit', unit])
    args.append(id)
    _run(*args)


def secret_set(
    id: str,
    *,
    content: dict[str, str] | None = None,
    label: str | None = None,
    description: str | None = None,
    expire: datetime.datetime | None = None,
    rotate: SecretRotate | None = None,
    owner: str | None = None,
):
    """Update an existing secret."""
    args = ['secret-set']
    if label is not None:
        args.extend(['--label', label])
    if description is not None:
        args.extend(['--description', description])
    if expire is not None:
        args.extend(['--expire', expire.isoformat()])
    if rotate is not None:
        args.extend(['--rotate', rotate.value])
    if owner is not None:
        args.extend(['--owner', owner])
    args.append(id)

    # Always use "key#file" arguments to provide the content to avoid secret data
    # ending up in the command line, where it may be logged and also is visible
    # via /proc.
    with tempfile.TemporaryDirectory() as tmp:
        for k, v in (content or {}).items():
            with open(f'{tmp}/{k}', mode='w', encoding='utf-8') as f:
                f.write(v)
            args.append(f'{k}#file={tmp}/{k}')
        _run(*args)


def state_delete(key: str):
    """Delete server-side-state key value pairs."""
    _run('state-delete', key)


@overload
def state_get(key: str) -> str: ...
@overload
def state_get(key: None) -> dict[str, str]: ...
def state_get(key: str | None) -> dict[str, str] | str:
    """Get server-side-state value."""
    args = ['state-get']
    if key is not None:
        args.append(key)
    result = _run(*args, return_output=True, use_json=True)
    return cast('dict[str, str]', result) if key is None else cast('str', result)


def state_set(data: Mapping[str, str], file: pathlib.Path | None = None):
    """Set server-side-state values."""
    args = ['state-set']
    args.extend(f'{k}={v}' for k, v in data.items())
    if file is not None:
        args.extend(['--file', str(file)])
    _run(*args)


@overload
def status_get(*, include_data: Literal[True], app: Literal[False]) -> UnitStatus: ...
@overload
def status_get(*, include_data: Literal[True], app: Literal[True]) -> AppStatus: ...
@overload
def status_get(*, include_data: Literal[False], app: bool = False) -> str: ...
def status_get(*, include_data: bool = False, app: bool = False) -> AppStatus | UnitStatus | str:
    """Get a status of a unit or an application."""
    args = ['status-get', f'--application={str(app).lower()}']
    if include_data:
        args.append('--include-data')
    result = _run(*args, use_json=True, return_output=True)
    if app:
        app_status = cast('_AppStatusDict', result['application-status'])
        units = {
            name: UnitStatus(
                status=u['status'], message=u['message'], status_data=u['status-data']
            )
            for name, u in app_status.get('units', {}).items()
        }
        return AppStatus(
            status=app_status['status'],
            message=app_status['message'],
            status_data=app_status['status-data'],
            units=units,
        )
    unit_status = cast('_UnitStatusDict', result)
    return UnitStatus(
        status=unit_status['status'],
        message=unit_status['message'],
        status_data=unit_status['status-data'],
    )


def status_set(status: SettableStatusName, message: str = '', *, app: bool = False):
    """Set a status of a unit or an application.

    Args:
        status: The status to set.
        message: The message to set in the status.
        app: A boolean indicating whether the status should be set for a unit or an
            application.
    """
    args = ['status-set', f'--application={app}', status]
    if message is not None:
        args.append(message)
    _run(*args)


def storage_add(name: str, count: int = 1):
    """Add storage instances."""
    _run('storage-add', f'{name}={count}')


@overload
def storage_get(identifier: str | None = None, *, attribute: str) -> str: ...
@overload
def storage_get(identifier: str | None = None) -> Storage: ...
def storage_get(identifier: str | None = None, attribute: str | None = None) -> Storage | str:
    """Retrieve information for the storage instance with the specified ID.

    Note that ``identifier`` can only be ``None`` if the current hook is a
    storage event, in which case Juju will use the ID of the storage that
    triggered the event.
    """
    # TODO: It looks like you can pass in a UUID instead of an identifier.
    args = ['storage-get']
    if identifier is not None:
        args.extend(['-s', identifier])
    if attribute is not None:
        args.append(attribute)
    result = _run(*args, return_output=True, use_json=True)
    if attribute is not None:
        return cast('str', result)
    return Storage(kind=result['kind'], location=pathlib.Path(result['location']))


def storage_list(name: str | None = None) -> list[str]:
    """List storage attached to the unit."""
    args = ['storage-list']
    if name is not None:
        args.append(name)
    storages = _run(*args, return_output=True, use_json=True)
    return cast('list[str]', storages)
