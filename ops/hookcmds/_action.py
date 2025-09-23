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
from typing import (
    Any,
    Mapping,
    cast,
    overload,
)

from ._utils import format_action_result_dict, run


def action_fail(message: str | None = None):
    """Set action fail status with message.

    Args:
        message: the failure error message. Juju will provide a default message
            if one is not provided.
    """
    args = ['action-fail']
    if message is not None:
        args.append(message)
    run(*args)


@overload
def action_get() -> dict[str, Any]: ...
@overload
def action_get(key: str) -> str: ...
def action_get(key: str | None = None) -> dict[str, Any] | str:
    """Get action parameters.

    ``action_get`` returns the value of the parameter at the given key. If a
    dotted key (for example foo.bar) is passed, ``action_get`` will recurse into
    the parameter map as needed.

    Args:
        key: The key of the action parameter to retrieve. If not provided, all
            parameters will be returned.
    """
    args = ['action-get', '--format=json']
    if key is not None:
        args.append(key)
    out = json.loads(run(*args))
    return cast('dict[str, Any]', out) if key is None else cast('str', out)


def action_log(message: str):
    """Record a progress message for the current action.

    Args:
        message: The progress message to provide to the Juju user.
    """
    run('action-log', message)


def action_set(results: Mapping[str, Any]):
    """Set action results.

    Args:
        results: The results map of the action, provided to the Juju user.
    """
    # The Juju action-set hook tool cannot interpret nested dicts, so we use a
    # helper to flatten out any nested dict structures into a dotted notation.
    flat_results = format_action_result_dict(results)
    run('action-set', *[f'{k}={v}' for k, v in flat_results.items()])
