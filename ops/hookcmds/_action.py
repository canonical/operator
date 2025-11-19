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

import json
from collections.abc import Mapping
from typing import Any, overload

from ._utils import run


def format_result_dict(
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
        >>> format_result_dict(test_dict)
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

        if isinstance(value, Mapping):
            output_ = format_result_dict(value, key, output_)
        elif key in output_:
            raise ValueError(
                f"duplicate key detected in dictionary passed to 'action-set': {key!r}"
            )
        else:
            output_[key] = value

    return output_


def action_fail(message: str | None = None):
    """Set action fail status with message.

    For more details, see:
    `Juju | Hook commands | action-fail <https://documentation.ubuntu.com/juju/3.6/reference/hook-command/list-of-hook-commands/action-fail/>`_

    Args:
        message: the failure error message. Juju will provide a default message
            if one is not provided.
    """
    args: list[str] = []
    if message is not None:
        # The '--' allows messages that start with a hyphen.
        args.extend(['--', message])
    run('action-fail', *args)


@overload
def action_get() -> dict[str, Any]: ...
@overload
def action_get(key: str) -> Any: ...
def action_get(key: str | None = None) -> dict[str, Any] | Any:
    """Get action parameters.

    ``action_get`` returns the value of the parameter at the given key. If a
    dotted key (for example foo.bar) is passed, ``action_get`` will recurse into
    the parameter map as needed.

    For more details, see:
    `Juju | Hook commands | action-get <https://documentation.ubuntu.com/juju/3.6/reference/hook-command/list-of-hook-commands/action-get/>`_

    Args:
        key: The key of the action parameter to retrieve. If not provided, all
            parameters will be returned.
    """
    args = ['--format=json']
    if key is not None:
        args.append(key)
    stdout = run('action-get', *args)
    if key is not None:
        return json.loads(stdout)
    result: dict[str, Any] = json.loads(stdout)
    return result


def action_log(message: str):
    """Record a progress message for the current action.

    For more details, see:
    `Juju | Hook commands | action-log <https://documentation.ubuntu.com/juju/3.6/reference/hook-command/list-of-hook-commands/action-log/>`_

    Args:
        message: The progress message to provide to the Juju user.
    """
    # The '--' allows messages that start with a hyphen.
    run('action-log', '--', message)


def action_set(results: Mapping[str, Any]):
    """Set action results.

    For more details, see:
    `Juju | Hook commands | action-set <https://documentation.ubuntu.com/juju/3.6/reference/hook-command/list-of-hook-commands/action-set/>`_

    Args:
        results: The results map of the action, provided to the Juju user.
    """
    # The Juju action-set hook command cannot interpret nested dicts, so we use a
    # helper to flatten out any nested dict structures into a dotted notation.
    flat_results = format_result_dict(results)
    run('action-set', *[f'{k}={v}' for k, v in flat_results.items()])
