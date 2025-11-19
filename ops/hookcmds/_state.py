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
from typing import overload

from ._utils import run


def state_delete(key: str):
    """Delete server-side-state key value pairs.

    For more details, see:
    `Juju | Hook commands | state-delete <https://documentation.ubuntu.com/juju/3.6/reference/hook-command/list-of-hook-commands/state-delete/>`_

    Args:
        key: The key of the server-side state to delete.
    """
    run('state-delete', key)


@overload
def state_get(key: str) -> str: ...
@overload
def state_get(key: None) -> dict[str, str]: ...
def state_get(key: str | None) -> dict[str, str] | str:
    """Get server-side-state value.

    For more details, see:
    `Juju | Hook commands | state-get <https://documentation.ubuntu.com/juju/3.6/reference/hook-command/list-of-hook-commands/state-get/>`_

    Args:
        key: The key of the server-side state to get. If ``None``, get all keys
            and values.
    """
    args = ['--format=json']
    if key is not None:
        args.append(key)
    stdout = run('state-get', *args)
    if key is not None:
        key_result: str = json.loads(stdout)
        return key_result
    result: dict[str, str] = json.loads(stdout)
    return result


# We don't offer a `file` argument here as we expect that charms will generally
# have the data to set in memory. We do always use `--file` ourselves, but with
# stdin rather than a real file.
def state_set(data: Mapping[str, str]):
    """Set server-side-state values.

    For more details, see:
    `Juju | Hook commands | state-set <https://documentation.ubuntu.com/juju/3.6/reference/hook-command/list-of-hook-commands/state-set/>`_

    Args:
        data: The key-value pairs to set in the server-side state.
    """
    args = ['--file', '-']
    content = json.dumps(data)
    run('state-set', *args, input=content)
