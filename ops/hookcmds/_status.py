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
from typing import Literal, overload

from ._types import AppStatus, AppStatusDict, SettableStatusName, StatusDict, UnitStatus
from ._utils import run


# We do not offer an argument to control whether `--include-data` is passed. The
# data is not large (although it does scale linearly with the number of units),
# so the method signature is simpler if it is always included and callers can
# ignore any data they don't need.
@overload
def status_get(*, app: Literal[False] = False) -> UnitStatus: ...
@overload
def status_get(*, app: Literal[True]) -> AppStatus: ...
def status_get(*, app: bool = False) -> AppStatus | UnitStatus:
    """Get a status of a unit or an application.

    For more details, see:
    `Juju | Hook commands | status-get <https://documentation.ubuntu.com/juju/3.6/reference/hook-command/list-of-hook-commands/status-get/>`_

    Args:
        app: Get status for all units of this application if this unit is the leader.
    """
    args = ['--include-data', '--format=json', f'--application={str(app).lower()}']
    stdout = run('status-get', *args)
    if app:
        app_result: AppStatusDict = json.loads(stdout)
        return AppStatus._from_dict(app_result)
    result: StatusDict = json.loads(stdout)
    return UnitStatus._from_dict(result)


def status_set(status: SettableStatusName, message: str | None = None, *, app: bool = False):
    """Set a status of a unit or an application.

    For more details, see:
    `Juju | Hook commands | status-set <https://documentation.ubuntu.com/juju/3.6/reference/hook-command/list-of-hook-commands/status-set/>`_

    Args:
        status: The status to set.
        message: A message to include in the status.
        app: If ``True``, set this status for the application to which the unit belongs.
    """
    args = [f'--application={app}', status]
    if message is not None:
        # The '--' allows messages that start with a hyphen.
        args.extend(['--', message])
    run('status-set', *args)
