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
    Mapping,
    cast,
    overload,
)

from .._private import yaml
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

    Args:
        app: Get the relation data for the overall application, not just a unit
        id: The ID of the relation to get data for, or ``None`` to get data for
            the relation that triggered the current hook.
        key: The specific key to get data for, or ``None`` to get all data.
        unit: The unit to get data for, or ``None`` to get data for all units.
    """
    args = ['relation-get', '--format=json']
    if id is not None:
        args.extend(['-r', str(id)])
    if app:
        args.append('--app')
    if key is not None:
        args.append(key)
    if unit is not None:
        args.append(unit)
    result = json.loads(run(*args))
    if key is not None:
        return cast('str', result)
    return cast('dict[str, str]', result)


def relation_ids(name: str) -> list[str]:
    """List all relation IDs for the given endpoint.

    Args:
        name: the endpoint name.
    """
    return cast('list[str]', json.loads(run('relation-ids', name, '--format=json')))


def relation_list(id: int | None = None, *, app: bool = False) -> list[str]:
    """List relation units.

    Note that ``id`` can only be ``None`` if the current hook is a relation
    event, in which case Juju will use the ID of the relation that triggered the
    event.

    Args:
        id: The ID of the relation to list units for, or ``None`` to list units
            for the relation that triggered the current hook.
        app: List remote application instead of participating units.
    """
    args = ['relation-list', '--format=json']
    if app:
        args.append('--app')
    if id is not None:
        args.extend(['-r', str(id)])
    return cast('list[str]', json.loads(run(*args)))


def relation_model_get(id: int | None = None) -> RelationModel:
    """Get details about the model hosting a related application.

    Note that ``id`` can only be ``None`` if the current hook is a relation
    event, in which case Juju will use the ID of the relation that triggered the
    event.

    Args:
        id: The ID of the relation to get data for, or ``None`` to get data for
            the relation that triggered the current hook.
    """
    args = ['relation-model-get', '--format=json']
    if id is not None:
        args.extend(['-r', str(id)])
    return RelationModel._from_dict(cast('RelationModelDict', json.loads(run(*args))))


def relation_set(
    data: Mapping[str, str],
    id: int | None = None,
    *,
    app: bool = False,
):
    """Set relation settings.

    Note that ``id`` can only be ``None`` if the current hook is a relation
    event, in which case Juju will use the ID of the relation that triggered the
    event.

    Args:
        data: The relation data to set.
        id: The ID of the relation to set data for, or ``None`` to set data for
            the relation that triggered the current hook.
        app: Set data for the overall application, not just a unit.
    """
    args = ['relation-set']
    if app:
        args.append('--app')
    if id is not None:
        args.extend(['-r', str(id)])
    args.extend(['--file', '-'])
    content = yaml.safe_dump(data)
    run(*args, input=content)
