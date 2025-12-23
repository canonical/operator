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
from typing import Literal, overload

from ._types import RelationModel, RelationModelDict
from ._utils import run


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

    For more details, see:
    `Juju | Hook commands | relation-get <https://documentation.ubuntu.com/juju/3.6/reference/hook-command/list-of-hook-commands/relation-get/>`_

    Args:
        app: Get the relation data for the overall application, not just a unit
        id: The ID of the relation to get data for, or ``None`` to get data for
            the relation that triggered the current hook.
        key: The specific key to get data for, or ``None`` to get all data.
        unit: The unit to get data for, or ``None`` to get data for the unit
            that triggered the current hook.
    """
    if key == '-':
        raise ValueError('To get all keys, pass None for the key argument; "-" is not supported.')
    args = ['--format=json']
    if id is not None:
        args.extend(['-r', str(id)])
    if app:
        args.append('--app')
    if unit and key:
        # If both a unit and a key are provided, the key must come first.
        args.extend([key, unit])
    elif unit and not key:
        # If you provide a unit but no key, we need to put '-' as the key so
        # that Juju knows to provide all keys.
        args.extend(['-', unit])
    elif key:
        # The unit is not required when inside a relation hook other than relation-broken.
        args.append(key)
    stdout = run('relation-get', *args)
    if key is not None:
        key_result: str = json.loads(stdout)
        return key_result
    result: dict[str, str] = json.loads(stdout)
    return result


def relation_ids(name: str) -> list[str]:
    """List all relation IDs for the given endpoint.

    For more details, see:
    `Juju | Hook commands | relation-ids <https://documentation.ubuntu.com/juju/3.6/reference/hook-command/list-of-hook-commands/relation-ids/>`_

    Args:
        name: the endpoint name.
    """
    stdout = run('relation-ids', name, '--format=json')
    result: list[str] = json.loads(stdout)
    return result


@overload
def relation_list(id: int | None = None, *, app: Literal[True]) -> str: ...
@overload
def relation_list(id: int | None = None, *, app: Literal[False] = False) -> list[str]: ...
def relation_list(id: int | None = None, *, app: bool = False) -> str | list[str]:
    """List relation units.

    Note that ``id`` can only be ``None`` if the current hook is a relation
    event, in which case Juju will use the ID of the relation that triggered the
    event.

    For more details, see:
    `Juju | Hook commands | relation-list <https://documentation.ubuntu.com/juju/3.6/reference/hook-command/list-of-hook-commands/relation-list/>`_

    Args:
        id: The ID of the relation to list units for, or ``None`` to list units
            for the relation that triggered the current hook.
        app: List remote application instead of participating units.
    """
    args = ['--format=json']
    if app:
        args.append('--app')
    if id is not None:
        args.extend(['-r', str(id)])
    stdout = run('relation-list', *args)
    if app:
        app_result: list[str] = json.loads(stdout)
        return app_result
    result: str = json.loads(stdout)
    return result


def relation_model_get(id: int | None = None) -> RelationModel:
    """Get details about the model hosting a related application.

    Note that ``id`` can only be ``None`` if the current hook is a relation
    event, in which case Juju will use the ID of the relation that triggered the
    event.

    For more details, see:
    `Juju | Hook commands | relation-model-get <https://documentation.ubuntu.com/juju/3.6/reference/hook-command/list-of-hook-commands/relation-model-get/>`_

    Args:
        id: The ID of the relation to get data for, or ``None`` to get data for
            the relation that triggered the current hook.
    """
    args = ['--format=json']
    if id is not None:
        args.extend(['-r', str(id)])
    stdout = run('relation-model-get', *args)
    result: RelationModelDict = json.loads(stdout)
    return RelationModel._from_dict(result)


# We don't offer a `file` argument here as we expect that charms will generally
# have the data to set in memory. We do always use `--file` ourselves, but with
# stdin rather than a real file.
def relation_set(
    data: Mapping[str, str],
    id: int | None = None,
    *,
    app: bool = False,
):
    """Set relation settings.

    Setting the value for a key to the empty string deletes that key. The data
    is updated with the values provided, not replaced, so any keys that are not
    specified are left unchanged.

    Note that ``id`` can only be ``None`` if the current hook is a relation
    event, in which case Juju will use the ID of the relation that triggered the
    event.

    For more details, see:
    `Juju | Hook commands | relation-set <https://documentation.ubuntu.com/juju/3.6/reference/hook-command/list-of-hook-commands/relation-set/>`_

    Args:
        data: The relation data to set.
        id: The ID of the relation to set data for, or ``None`` to set data for
            the relation that triggered the current hook.
        app: Set data for the overall application, not just a unit.
    """
    args: list[str] = []
    if id is not None:
        args.extend(['-r', str(id)])
    if app:
        args.append('--app')
    args.extend(['--file', '-'])
    content = json.dumps(data)
    run('relation-set', *args, input=content)
