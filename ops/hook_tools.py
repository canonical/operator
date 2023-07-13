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

"""Wrappers for juju hook tools."""

import datetime
import json
import math
import re
import shutil
import subprocess
import tempfile
import typing
from pathlib import Path
from typing import (
    Any,
    Dict,
    Iterable,
    List,
    Literal,
    Mapping,
    MutableMapping,
    Optional,
    Set,
    Union,
)

from ops._private import yaml

if typing.TYPE_CHECKING:
    from typing_extensions import TypedDict

    _ConfigOption = TypedDict('_ConfigOption', {
        'type': Literal['string', 'int', 'float', 'boolean'],
        'description': str,
        'default': Union[str, int, float, bool],
    })

    _StatusDict = TypedDict('_StatusDict', {'status': str, 'message': str})

    # relation data is a string key: string value mapping so far as the
    # controller is concerned
    _RelationDataContent_Raw = Dict[str, str]

    _AddressDict = TypedDict('_AddressDict', {
        'address': str,  # Juju < 2.9
        'value': str,  # Juju >= 2.9
        'cidr': str
    })
    _BindAddressDict = TypedDict('_BindAddressDict', {
        'interface-name': str,
        'addresses': List[_AddressDict]
    })
    _NetworkDict = TypedDict('_NetworkDict', {
        'bind-addresses': List[_BindAddressDict],
        'ingress-addresses': List[str],
        'egress-subnets': List[str]
    })


class HookError(Exception):
    """Raised when a subprocess call fails."""


def _run(*args: str, return_output: bool = False,
         use_json: bool = False, input_stream: Optional[str] = None
         ) -> Union[str, Any, None]:
    kwargs = dict(stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, encoding='utf-8')
    if input_stream:
        kwargs.update({"input": input_stream})
    which_cmd = shutil.which(args[0])
    if which_cmd is None:
        raise RuntimeError(f'command not found: {args[0]}')
    args = (which_cmd,) + args[1:]
    if use_json:
        args += ('--format=json',)
    # TODO(benhoyt): all the "type: ignore"s below kinda suck, but I've
    #                been fighting with Pyright for half an hour now...
    try:
        result = subprocess.run(args, **kwargs)  # type: ignore
    except subprocess.CalledProcessError as e:
        raise HookError(e.stderr)
    if return_output:
        if result.stdout is None:  # type: ignore
            return ''
        else:
            text: str = result.stdout  # type: ignore
            if use_json:
                return json.loads(text)  # type: ignore
            else:
                return text  # type: ignore


_ACTION_RESULT_KEY_REGEX = re.compile(r'^[a-z0-9](([a-z0-9-.]+)?[a-z0-9])?$')


def _format_action_result_dict(input: Dict[str, Any],
                               parent_key: Optional[str] = None,
                               output: Optional[Dict[str, str]] = None
                               ) -> Dict[str, str]:
    """Turn a nested dictionary into a flattened dictionary, using '.' as a key seperator.

    This is used to allow nested dictionaries to be translated into the dotted format required by
    the Juju `action-set` hook tool in order to set nested data on an action.

    Additionally, this method performs some validation on keys to ensure they only use permitted
    characters.

    Example::

        >>> test_dict = {'a': {'b': 1, 'c': 2}}
        >>> _format_action_result_dict(test_dict)
        {'a.b': 1, 'a.c': 2}

    Arguments:
        input: The dictionary to flatten
        parent_key: The string to prepend to dictionary's keys
        output: The current dictionary to be returned, which may or may not yet be completely flat

    Returns:
        A flattened dictionary with validated keys

    Raises:
        ValueError: if the dict is passed with a mix of dotted/non-dotted keys that expand out to
            result in duplicate keys. For example: {'a': {'b': 1}, 'a.b': 2}. Also raised if a dict
            is passed with a key that fails to meet the format requirements.
    """
    output_: Dict[str, str] = output or {}

    for key, value in input.items():
        # Ensure the key is of a valid format, and raise a ValueError if not
        if not isinstance(key, str):
            # technically a type error, but for consistency with the
            # other exceptions raised on key validation...
            raise ValueError(f'invalid key {key!r}; must be a string')
        if not _ACTION_RESULT_KEY_REGEX.match(key):
            raise ValueError("key '{!r}' is invalid: must be similar to 'key', 'some-key2', or "
                             "'some.key'".format(key))

        if parent_key:
            key = f"{parent_key}.{key}"

        if isinstance(value, MutableMapping):
            value = typing.cast(Dict[str, Any], value)
            output_ = _format_action_result_dict(value, key, output_)
        elif key in output_:
            raise ValueError("duplicate key detected in dictionary passed to 'action-set': {!r}"
                             .format(key))
        else:
            output_[key] = value  # type: ignore

    return output_


class _Validator:
    """Provides facilities for validating inputs and formatting them for model backends."""

    METRIC_KEY_REGEX = re.compile(r'^[a-zA-Z](?:[a-zA-Z0-9-_]*[a-zA-Z0-9])?$')

    @classmethod
    def validate_metric_key(cls, key: str):
        if cls.METRIC_KEY_REGEX.match(key) is None:
            raise HookError(
                f'invalid metric key {key!r}: must match {cls.METRIC_KEY_REGEX.pattern}')

    @classmethod
    def validate_metric_label(cls, label_name: str):
        if cls.METRIC_KEY_REGEX.match(label_name) is None:
            raise HookError(
                'invalid metric label name {!r}: must match {}'.format(
                    label_name, cls.METRIC_KEY_REGEX.pattern))

    @classmethod
    def format_metric_value(cls, value: Union[int, float]):
        if not isinstance(value, (int, float)):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise HookError('invalid metric value {!r} provided:'
                            ' must be a positive finite float'.format(value))

        if math.isnan(value) or math.isinf(value) or value < 0:
            raise HookError('invalid metric value {!r} provided:'
                            ' must be a positive finite float'.format(value))
        return str(value)

    @classmethod
    def validate_label_value(cls, label: str, value: str):
        # Label values cannot be empty, contain commas or equal signs as those are
        # used by add-metric as separators.
        if not value:
            raise HookError(
                f'metric label {label} has an empty value, which is not allowed')
        v = str(value)
        if re.search('[,=]', v) is not None:
            raise HookError(
                f'metric label values must not contain "," or "=": {label}={value!r}')


def relation_ids(relation_name: str) -> List[int]:
    rel_ids = _run('relation-ids', relation_name, return_output=True, use_json=True)
    rel_ids = typing.cast(Iterable[str], rel_ids)
    return [int(rel_id.split(':')[-1]) for rel_id in rel_ids]


def relation_list(relation_id: int) -> List[str]:
    rel_list = _run('relation-list', '-r', str(relation_id),
                    return_output=True, use_json=True)
    return typing.cast(List[str], rel_list)


def relation_list_app(relation_id: int) -> str:
    rel_id = _run('relation-list', '-r', str(relation_id), '--app',
                  return_output=True, use_json=True)
    # if it returned anything at all, it's a str.
    return typing.cast(str, rel_id)


def relation_get(relation_id: int, member_name: str, is_app: bool
                 ) -> '_RelationDataContent_Raw':
    args = ['relation-get', '-r', str(relation_id), '-', member_name]
    if is_app:
        args.append('--app')

    raw_data_content = _run(*args, return_output=True, use_json=True)
    return typing.cast('_RelationDataContent_Raw', raw_data_content)


def relation_set(relation_id: int, key: str, value: str, is_app: bool) -> None:
    args = ['relation-set', '-r', str(relation_id)]
    if is_app:
        args.append('--app')
    args.extend(["--file", "-"])

    content = yaml.safe_dump({key: value})
    _run(*args, input_stream=content)


def config_get() -> Dict[str, '_ConfigOption']:
    out = _run('config-get', return_output=True, use_json=True)
    return typing.cast(Dict[str, '_ConfigOption'], out)


def is_leader() -> bool:
    return typing.cast(bool, _run('is-leader', return_output=True, use_json=True))


def resource_get(resource_name: str) -> str:
    out = _run('resource-get', resource_name, return_output=True)
    return typing.cast(str, out).strip()


def pod_spec_set(spec: Mapping[str, Any],
                 k8s_resources: Optional[Mapping[str, Any]] = None):
    tmpdir = Path(tempfile.mkdtemp('-pod-spec-set'))
    try:
        spec_path = tmpdir / 'spec.yaml'
        with spec_path.open("wt", encoding="utf8") as f:
            yaml.safe_dump(spec, stream=f)
        args = ['--file', str(spec_path)]
        if k8s_resources:
            k8s_res_path = tmpdir / 'k8s-resources.yaml'
            with k8s_res_path.open("wt", encoding="utf8") as f:
                yaml.safe_dump(k8s_resources, stream=f)
            args.extend(['--k8s-resources', str(k8s_res_path)])
        _run('pod-spec-set', *args)
    finally:
        shutil.rmtree(str(tmpdir))


def status_get(*, is_app: bool = False) -> '_StatusDict':
    """Get a status of a unit or an application.

    Args:
        is_app: A boolean indicating whether the status should be retrieved for a unit
            or an application.
    """
    content = _run(
        'status-get', '--include-data', f'--application={is_app}',
        use_json=True,
        return_output=True)
    # Unit status looks like (in YAML):
    # message: 'load: 0.28 0.26 0.26'
    # status: active
    # status-data: {}
    # Application status looks like (in YAML):
    # application-status:
    #   message: 'load: 0.28 0.26 0.26'
    #   status: active
    #   status-data: {}
    #   units:
    #     uo/0:
    #       message: 'load: 0.28 0.26 0.26'
    #       status: active
    #       status-data: {}

    if is_app:
        content = typing.cast(Dict[str, Dict[str, str]], content)
        app_status = content['application-status']
        return {'status': app_status['status'],
                'message': app_status['message']}
    else:
        return typing.cast('_StatusDict', content)


def status_set(status: str, message: str = '', *, is_app: bool = False) -> None:
    """Set a status of a unit or an application.

    Args:
        status: The status to set.
        message: The message to set in the status.
        is_app: A boolean indicating whether the status should be set for a unit or an
                application.
    """
    if not isinstance(is_app, bool):
        raise TypeError('is_app parameter must be boolean')
    _run('status-set', f'--application={is_app}', status, message)


def storage_list(name: str) -> List[int]:
    storages = _run('storage-list', name, return_output=True, use_json=True)
    storages = typing.cast(List[str], storages)
    return [int(s.split('/')[1]) for s in storages]


def storage_get(storage_name_id: str, attribute: str) -> str:
    if not len(attribute) > 0:  # assume it's an empty string.
        raise RuntimeError('calling storage_get with `attribute=""` will return a dict '
                           'and not a string. This usage is not supported.')
    out = _run('storage-get', '-s', storage_name_id, attribute,
               return_output=True, use_json=True)
    return typing.cast(str, out)


def storage_add(name: str, count: int = 1) -> None:
    if not isinstance(count, int) or isinstance(count, bool):
        raise TypeError(f'storage count must be integer, got: {count} ({type(count)})')
    _run('storage-add', f'{name}={count}')


def action_get() -> Dict[str, Any]:
    out = _run('action-get', return_output=True, use_json=True)
    return typing.cast(Dict[str, Any], out)


def action_set(results: Dict[str, Any]) -> None:
    # The Juju action-set hook tool cannot interpret nested dicts, so we use a helper to
    # flatten out any nested dict structures into a dotted notation, and validate keys.
    flat_results = _format_action_result_dict(results)
    _run('action-set', *[f"{k}={v}" for k, v in flat_results.items()])


def action_log(message: str) -> None:
    _run('action-log', message)


def action_fail(message: str = '') -> None:
    _run('action-fail', message)


def application_version_set(version: str) -> None:
    _run('application-version-set', '--', version)


def juju_log(level: str, message: str) -> None:
    """Pass a log message on to the juju logger."""
    _run('juju-log', '--log-level', level, "--", message)


def network_get(binding_name: str, relation_id: Optional[int] = None) -> '_NetworkDict':
    """Return network info provided by network-get for a given binding.

    Args:
        binding_name: A name of a binding (relation name or extra-binding name).
        relation_id: An optional relation id to get network info for.
    """
    cmd = ['network-get', binding_name]
    if relation_id is not None:
        cmd.extend(['-r', str(relation_id)])
    network = _run(*cmd, return_output=True, use_json=True)
    return typing.cast('_NetworkDict', network)


def add_metrics(metrics: Mapping[str, Union[int, float]],
                labels: Optional[Mapping[str, str]] = None) -> None:
    cmd: List[str] = ['add-metric']
    if labels:
        label_args: List[str] = []
        for k, v in labels.items():
            _Validator.validate_metric_label(k)
            _Validator.validate_label_value(k, v)
            label_args.append(f'{k}={v}')
        cmd.extend(['--labels', ','.join(label_args)])

    metric_args: List[str] = []
    for k, v in metrics.items():
        _Validator.validate_metric_key(k)
        metric_value = _Validator.format_metric_value(v)
        metric_args.append(f'{k}={metric_value}')
    cmd.extend(metric_args)
    _run(*cmd)


def goal_state() -> Dict[str, Dict[str, Any]]:
    app_state = _run('goal-state', return_output=True, use_json=True)
    return typing.cast(Dict[str, Dict[str, Any]], app_state)


def secret_get(*,
               id: Optional[str] = None,
               label: Optional[str] = None,
               refresh: bool = False,
               peek: bool = False) -> Dict[str, str]:
    args: List[str] = []
    if id is not None:
        args.append(id)
    if label is not None:
        args.extend(['--label', label])
    if refresh:
        args.append('--refresh')
    if peek:
        args.append('--peek')
    # IMPORTANT: Don't call shared _run_for_secret method here; we want to
    # be extra sensitive inside secret_get to ensure we never
    # accidentally log or output secrets, even if _run_for_secret changes.
    result = _run('secret-get', *args, return_output=True, use_json=True)
    return typing.cast(Dict[str, str], result)


def secret_info_get(*,
                    id: Optional[str] = None,
                    label: Optional[str] = None) -> Dict[str, Any]:
    args: List[str] = []
    if id is not None:
        args.append(id)
    elif label is not None:  # elif because Juju secret-info-get doesn't allow id and label
        args.extend(['--label', label])
    result = _run('secret-info-get', *args, return_output=True, use_json=True)
    return typing.cast(Dict[str, Any], result)


def secret_set(id: str, *,
               content: Optional[Dict[str, str]] = None,
               label: Optional[str] = None,
               description: Optional[str] = None,
               expire: Optional[datetime.datetime] = None,
               rotate: Optional[str] = None):
    args = [id]
    if label is not None:
        args.extend(['--label', label])
    if description is not None:
        args.extend(['--description', description])
    if expire is not None:
        args.extend(['--expire', expire.isoformat()])
    if rotate is not None:
        args += ['--rotate', rotate]
    if content is not None:
        # The content has already been validated with Secret._validate_content
        for k, v in content.items():
            args.append(f'{k}={v}')
    _run('secret-set', *args, return_output=False, use_json=False)


def secret_add(content: Dict[str, str], *,
               label: Optional[str] = None,
               description: Optional[str] = None,
               expire: Optional[datetime.datetime] = None,
               rotate: Optional[str] = None,
               owner: Optional[str] = None) -> str:
    args: List[str] = []
    if label is not None:
        args.extend(['--label', label])
    if description is not None:
        args.extend(['--description', description])
    if expire is not None:
        args.extend(['--expire', expire.isoformat()])
    if rotate is not None:
        args += ['--rotate', rotate]
    if owner is not None:
        args += ['--owner', owner]
    # The content has already been validated with Secret._validate_content
    for k, v in content.items():
        args.append(f'{k}={v}')
    result = _run('secret-add', *args, return_output=True, use_json=False)
    secret_id = typing.cast(str, result)
    return secret_id.strip()


def secret_grant(id: str, relation_id: int, *, unit: Optional[str] = None):
    args = [id, '--relation', str(relation_id)]
    if unit is not None:
        args += ['--unit', str(unit)]
    _run('secret-grant', *args, return_output=False, use_json=False)


def secret_revoke(id: str, relation_id: int, *, unit: Optional[str] = None):
    args = [id, '--relation', str(relation_id)]
    if unit is not None:
        args += ['--unit', str(unit)]
    _run('secret-revoke', *args, return_output=False, use_json=False)


def secret_remove(id: str, *, revision: Optional[int] = None):
    args = [id]
    if revision is not None:
        args.extend(['--revision', str(revision)])
    _run('secret-remove', *args, return_output=False, use_json=False)


def open_port(protocol: str, port: Optional[int] = None):
    arg = f'{port}/{protocol}' if port is not None else protocol
    _run('open-port', arg)


def close_port(protocol: str, port: Optional[int] = None):
    arg = f'{port}/{protocol}' if port is not None else protocol
    _run('close-port', arg)


def opened_ports() -> Set[str]:
    # We could use "opened-ports --format=json", but it's not really
    # structured; it's just an array of strings which are the lines of the
    # text output, like ["icmp","8081/udp"]. So it's probably just as
    # likely to change as the text output, and doesn't seem any better.
    output = typing.cast(str, _run('opened-ports', return_output=True))
    ports: Set[str] = set()
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        ports.add(line)
    return ports
