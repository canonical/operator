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

import datetime
import json
import tempfile
from typing import Any, Literal, overload

from ._types import SecretInfo, SecretRotate
from ._utils import datetime_to_rfc3339, run


# The `--file` parameter is not exposed as we expect the content to be held in
# memory when charming. Under the hood, `--file` is always used, to ensure that
# secret data does not end up in the command line.
def secret_add(
    content: dict[str, str],
    *,
    label: str | None = None,
    description: str | None = None,
    expire: datetime.datetime | str | None = None,
    rotate: SecretRotate | None = None,
    owner: Literal['application', 'unit'] = 'application',
) -> str:
    """Add a new secret.

    For more details, see:
    `Juju | Hook commands | secret-add <https://documentation.ubuntu.com/juju/3.6/reference/hook-command/list-of-hook-commands/secret-add/>`_

    Args:
        content: The content of the secret.
        label: A label used to identify the secret in hooks.
        description: The secret description.
        expire: Either a duration or time when the secret should expire.
        rotate: The secret rotation policy.
        owner: The owner of the secret, either the application or the unit.
    """
    args: list[str] = []
    if label is not None:
        args.extend(['--label', label])
    if description is not None:
        args.extend(['--description', description])
    if expire is not None:
        if isinstance(expire, str):
            args.extend(['--expire', expire])
        else:
            args.extend(['--expire', datetime_to_rfc3339(expire)])
    if rotate is not None:
        args.extend(['--rotate', rotate])
    args.extend(['--owner', owner])
    with tempfile.TemporaryDirectory() as tmp:
        for k, v in content.items():
            with open(f'{tmp}/{k}', mode='w', encoding='utf-8') as f:
                f.write(v)
            args.append(f'{k}#file={tmp}/{k}')
        stdout = run('secret-add', *args)
    return stdout.strip()


# It's possible to provide neither peek nor refresh, or one of them, but not both.
# One or both of id and label must be provided.
@overload
def secret_get(
    *,
    id: str,
    label: str | None = None,
    refresh: Literal[False] = False,
    peek: Literal[False] = False,
) -> dict[str, str]: ...
@overload
def secret_get(
    *,
    id: str | None = None,
    label: str,
    refresh: Literal[False] = False,
    peek: Literal[False] = False,
) -> dict[str, str]: ...
@overload
def secret_get(
    *,
    id: str,
    label: str | None = None,
    refresh: Literal[True],
    peek: Literal[False] = False,
) -> dict[str, str]: ...
@overload
def secret_get(
    *,
    id: str | None = None,
    label: str,
    refresh: Literal[True],
    peek: Literal[False] = False,
) -> dict[str, str]: ...
@overload
def secret_get(
    *,
    id: str,
    label: str | None = None,
    refresh: Literal[False] = False,
    peek: Literal[True],
) -> dict[str, str]: ...
@overload
def secret_get(
    *,
    id: str | None = None,
    label: str,
    refresh: Literal[False] = False,
    peek: Literal[True],
) -> dict[str, str]: ...
def secret_get(
    *,
    id: str | None = None,
    label: str | None = None,
    refresh: bool = False,
    peek: bool = False,
) -> dict[str, str]:
    """Get the content of a secret.

    Either the ID or the label or both must be provided. If both are provided,
    the secret is looked up by ID and the label is set to the one provided.

    For more details, see:
    `Juju | Hook commands | secret-get <https://documentation.ubuntu.com/juju/3.6/reference/hook-command/list-of-hook-commands/secret-get/>`_

    Args:
        id: The ID of the secret to retrieve.
        label: The label of the secret to retrieve.
        peek: Get the latest revision just this time.
        refresh: Get the latest revision and also get this same revision for subsequent calls.
    """
    args: list[str] = []
    if id is not None:
        args.append(id)
    if label is not None:
        args.extend(['--label', label])
    if refresh:
        args.append('--refresh')
    if peek:
        args.append('--peek')
    stdout = run('secret-get', '--format=json', *args)
    result: dict[str, str] = json.loads(stdout)
    return result


def secret_grant(id: str, relation_id: int, *, unit: str | None = None):
    """Grant access to a secret.

    For more details, see:
    `Juju | Hook commands | secret-grant <https://documentation.ubuntu.com/juju/3.6/reference/hook-command/list-of-hook-commands/secret-grant/>`_

    Args:
        id: The ID of the secret to grant access to.
        relation_id: The relation with which to associate the grant.
        unit: If provided, limit access to just that unit.
    """
    args = ['--relation', str(relation_id)]
    if unit is not None:
        args.extend(['--unit', str(unit)])
    args.append(id)
    run('secret-grant', *args)


def secret_ids() -> list[str]:
    """Retrieve IDs for secrets owned by the application.

    For more details, see:
    `Juju | Hook commands | secret-ids <https://documentation.ubuntu.com/juju/3.6/reference/hook-command/list-of-hook-commands/secret-ids/>`_
    """
    stdout = run('secret-ids', '--format=json')
    result: list[str] = json.loads(stdout)
    return result


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
    """Get a secret's metadata info.

    Either the ID or the label must be provided.

    For more details, see:
    `Juju | Hook commands | secret-info-get <https://documentation.ubuntu.com/juju/3.6/reference/hook-command/list-of-hook-commands/secret-info-get/>`_

    Args:
        id: The ID of the secret to retrieve.
        label: The label of the secret to retrieve.
    """
    args = ['--format=json']
    if id is not None:
        args.append(id)
    if label is not None:
        args.extend(['--label', label])
    stdout = run('secret-info-get', *args)
    result: dict[str, Any] = json.loads(stdout)
    return SecretInfo._from_dict(result)


def secret_remove(id: str, *, revision: int | None = None):
    """Remove an existing secret.

    For more details, see:
    `Juju | Hook commands | secret-remove <https://documentation.ubuntu.com/juju/3.6/reference/hook-command/list-of-hook-commands/secret-remove/>`_

    Args:
        id: The ID of the secret to remove.
        revision: The revision of the secret to remove. If not provided, all
            revisions are removed.
    """
    args = [id]
    if revision is not None:
        args.extend(['--revision', str(revision)])
    run('secret-remove', *args)


def secret_revoke(
    id: str, *, relation_id: int | None, app: str | None = None, unit: str | None = None
):
    """Revoke access to a secret.

    For more details, see:
    `Juju | Hook commands | secret-revoke <https://documentation.ubuntu.com/juju/3.6/reference/hook-command/list-of-hook-commands/secret-revoke/>`_

    Args:
        id: The ID of the secret.
        relation_id: The relation for which to revoke the grant.
        app: Revoke access from all units in that application.
        unit: Revoke access from just this unit.
    """
    args: list[str] = []
    if relation_id is not None:
        args.extend(['--relation', str(relation_id)])
    if app is not None:
        args.extend(['--app', app])
    if unit is not None:
        args.extend(['--unit', unit])
    args.append(id)
    run('secret-revoke', *args)


def secret_set(
    id: str,
    *,
    content: dict[str, str] | None = None,
    label: str | None = None,
    description: str | None = None,
    expire: datetime.datetime | str | None = None,
    rotate: SecretRotate | None = None,
    owner: Literal['application', 'unit'] = 'application',
):
    """Update an existing secret.

    For more details, see:
    `Juju | Hook commands | secret-set <https://documentation.ubuntu.com/juju/3.6/reference/hook-command/list-of-hook-commands/secret-set/>`_

    Args:
        id: The ID of the secret to update.
        content: The content of the secret.
        label: A label used to identify the secret in hooks.
        description: The secret description.
        expire: Either a duration or time when the secret should expire.
        rotate: The secret rotation policy.
        owner: The owner of the secret, either the application or the unit.
    """
    args: list[str] = []
    if label is not None:
        args.extend(['--label', label])
    if description is not None:
        args.extend(['--description', description])
    if expire is not None:
        if isinstance(expire, str):
            args.extend(['--expire', expire])
        else:
            args.extend(['--expire', datetime_to_rfc3339(expire)])
    if rotate is not None:
        args.extend(['--rotate', rotate])
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
        run('secret-set', *args)
