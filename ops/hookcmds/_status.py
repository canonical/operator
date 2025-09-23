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
    Literal,
    cast,
    overload,
)

from ._types import AppStatus, AppStatusDict, SettableStatusName, StatusDict, UnitStatus
from ._utils import run


@overload
def status_get(*, app: Literal[False] = False) -> UnitStatus: ...
@overload
def status_get(*, app: Literal[True]) -> AppStatus: ...
def status_get(*, app: bool = False) -> AppStatus | UnitStatus:
    """Get a status of a unit or an application.

    Args:
        app: Get status for all units of this application if this unit is the leader.
    """
    args = ['status-get', '--include-data', '--format=json', f'--application={str(app).lower()}']
    result = json.loads(run(*args))
    if app:
        app_status = cast('AppStatusDict', result['application-status'])
        return AppStatus._from_dict(app_status)
    return UnitStatus._from_dict(cast('StatusDict', result))


def status_set(status: SettableStatusName, message: str = '', *, app: bool = False):
    """Set a status of a unit or an application.

    Args:
        status: The status to set.
        message: A message to include in the status.
        app: If ``True``, set this status for the application to which the unit belongs.
    """
    args = ['status-set', f'--application={app}', status]
    if message is not None:
        args.append(message)
    run(*args)
