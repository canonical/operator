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

"""Low-level access to the Juju hook commands.

Charm authors should use the :class:`ops.Model` (via ``self.model``) rather than
directly running the hook commands, where possible. This module is primarily
provided to help with developing charming alternatives to the Ops framework.

Note: ``hookcmds`` is not covered by the semver policy that applies to the rest
of Ops. We will do our best to avoid breaking changes, but we reserve the right
to make breaking changes within this package if necessary, within the Ops 3.x
series.

All methods are 1:1 mapping to Juju hook commands. This is a *low-level* API,
available for charm use, but expected to be used via higher-level wrappers.

See `Juju | Hook commands <https://documentation.ubuntu.com/juju/3.6/reference/hook-command/>`_
and `Juju | Hook command list <https://documentation.ubuntu.com/juju/3.6/reference/hook-command/list-of-hook-commands/>`_
for a list of all Juju hook commands.
"""

from __future__ import annotations

from ._action import action_fail, action_get, action_log, action_set
from ._other import (
    app_version_set,
    config_get,
    credential_get,
    goal_state,
    is_leader,
    juju_log,
    juju_reboot,
    network_get,
    resource_get,
)
from ._port import close_port, open_port, opened_ports
from ._relation import relation_get, relation_ids, relation_list, relation_model_get, relation_set
from ._secret import (
    secret_add,
    secret_get,
    secret_grant,
    secret_ids,
    secret_info_get,
    secret_remove,
    secret_revoke,
    secret_set,
)
from ._state import state_delete, state_get, state_set
from ._status import status_get, status_set
from ._storage import storage_add, storage_get, storage_list
from ._types import (
    Address,
    AppStatus,
    BindAddress,
    CloudCredential,
    CloudSpec,
    Goal,
    GoalState,
    Network,
    Port,
    RelationModel,
    SecretInfo,
    SecretRotate,
    SettableStatusName,
    StatusName,
    Storage,
    UnitStatus,
)
from ._utils import Error

__all__ = [
    'Address',
    'AppStatus',
    'BindAddress',
    'CloudCredential',
    'CloudSpec',
    'Error',
    'Goal',
    'GoalState',
    'Network',
    'Port',
    'RelationModel',
    'SecretInfo',
    'SecretRotate',
    'SettableStatusName',
    'StatusName',
    'Storage',
    'UnitStatus',
    'action_fail',
    'action_get',
    'action_log',
    'action_set',
    'app_version_set',
    'close_port',
    'config_get',
    'credential_get',
    'goal_state',
    'is_leader',
    'juju_log',
    'juju_reboot',
    'network_get',
    'open_port',
    'opened_ports',
    'relation_get',
    'relation_ids',
    'relation_list',
    'relation_model_get',
    'relation_set',
    'resource_get',
    'secret_add',
    'secret_get',
    'secret_grant',
    'secret_ids',
    'secret_info_get',
    'secret_remove',
    'secret_revoke',
    'secret_set',
    'state_delete',
    'state_get',
    'state_set',
    'status_get',
    'status_set',
    'storage_add',
    'storage_get',
    'storage_list',
]
