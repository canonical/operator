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

from ._types import Storage
from ._utils import run


def storage_add(counts: Mapping[str, int]):
    """Add storage instances.

    For more details, see:
    `Juju | Hook commands | storage-add <https://documentation.ubuntu.com/juju/3.6/reference/hook-command/list-of-hook-commands/storage-add/>`_

    Args:
        counts: A maps of storage names to the number of instances of that
            storage to create.
    """
    run('storage-add', *(f'{name}={count}' for name, count in counts.items()))


# Juju allows specifying a single attribute to get, but there are only two
# possible attributes at this time, so it doesn't seem worth exposing that.
def storage_get(id: str | None = None) -> Storage:
    """Retrieve information for the storage instance with the specified ID.

    Note that ``id`` can only be ``None`` if the current hook is a storage
    event, in which case Juju will use the ID of the storage that triggered the
    event.

    For more details, see:
    `Juju | Hook commands | storage-get <https://documentation.ubuntu.com/juju/3.6/reference/hook-command/list-of-hook-commands/storage-get/>`_

    Args:
        id: The ID of the storage instance.
    """
    # TODO: It looks like you can pass in a UUID instead of an identifier.
    # The documentation doesn't say how to get that UUID, though.
    args = ['--format=json']
    if id is not None:
        args.extend(['-s', id])
    stdout = run('storage-get', *args)
    result = json.loads(stdout)
    return Storage._from_dict(result)


def storage_list(name: str | None = None) -> list[str]:
    """List storage attached to the unit.

    For more details, see:
    `Juju | Hook commands | storage-list <https://documentation.ubuntu.com/juju/3.6/reference/hook-command/list-of-hook-commands/storage-list/>`_

    Args:
        name: Only list storage with this name.
    """
    args = ['--format=json']
    if name is not None:
        args.append(name)
    stdout = run('storage-list', *args)
    result: list[str] = json.loads(stdout)
    return result
