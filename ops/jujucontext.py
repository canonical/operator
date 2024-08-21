# Copyright 2024 Canonical Ltd.
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

"""A helper to work with the Juju context and version."""

import dataclasses
from pathlib import Path
from typing import Any, Mapping, Optional, Set

from ops.jujuversion import JujuVersion


@dataclasses.dataclass(frozen=True)
class _JujuContext:
    """_JujuContext collects information from environment variables named 'JUJU_*'.

    Source: https://juju.is/docs/juju/charm-environment-variables.
    The HookVars function: https://github.com/juju/juju/blob/3.6/worker/uniter/runner/context/context.go#L1398.
    Only a subset of the above source, because these are what are used in ops.
    """

    action_name: Optional[str] = None
    """The action's name.

    For example 'backup' (from JUJU_ACTION_NAME).
    """

    action_uuid: Optional[str] = None
    """The action's uuid.

    For example '1' (from JUJU_ACTION_UUID).
    """

    charm_dir: Path = dataclasses.field(
        default_factory=lambda: Path(f'{__file__}/../../..').resolve()
    )
    """The root directory of the charm where it is running.

    For example '/var/lib/juju/agents/unit-bare-0/charm' (from JUJU_CHARM_DIR).

    If JUJU_CHARM_DIR is None or set to an empty string, use Path(f'{__file__}/../../..') as
    default (assuming the '$JUJU_CHARM_DIR/lib/op/main.py' structure).
    """

    debug: bool = False
    """Debug mode.

    If true, write logs to stderr as well as to juju-log (from JUJU_DEBUG).
    """

    debug_at: Set[str] = dataclasses.field(default_factory=set)
    """Where you want to stop when debugging.

    For example 'all' (from JUJU_DEBUG_AT).
    """

    dispatch_path: str = ''
    """The dispatch path in the format of 'actions/do-something'.

    For example 'hooks/workload-pebble-ready' (from JUJU_DISPATCH_PATH).
    """

    model_name: str = ''
    """The name of the model.

    For example 'foo' (from JUJU_MODEL_NAME).
    """

    model_uuid: str = ''
    """The uuid of the model.

    For example 'cdac5656-2423-4388-8f30-41854b4cca7d' (from JUJU_MODEL_UUID).
    """

    notice_id: Optional[str] = None
    """The ID of the notice.

    For example '1', (from JUJU_NOTICE_ID).
    """

    notice_key: Optional[str] = None
    """The key of the notice.

    For example 'example.com/a', (from JUJU_NOTICE_KEY).
    """

    notice_type: Optional[str] = None
    """The type of the notice.

    For example 'custom' (from JUJU_NOTICE_TYPE).
    """

    pebble_check_name: Optional[str] = None
    """The name of the pebble check.

    For example 'http-check' (from JUJU_PEBBLE_CHECK_NAME).
    """

    relation_departing_unit_name: Optional[str] = None
    """The unit that is departing a relation.

    For example 'remote/42' (from JUJU_DEPARTING_UNIT).
    """

    relation_name: Optional[str] = None
    """The name of the relation.

    For example 'database' (from JUJU_RELATION).
    """

    relation_id: Optional[int] = None
    """The id of the relation.

    For example 1 (integer) if the original environment variable's value is 'database:1'
    (from JUJU_RELATION_ID).
    """

    remote_app_name: Optional[str] = None
    """The name of the remote app.

    For example 'remoteapp1' (from JUJU_REMOTE_APP).
    """

    remote_unit_name: Optional[str] = None
    """The name of the remote unit.

    For example 'remoteapp1/0' (from JUJU_REMOTE_UNIT).
    """

    secret_id: Optional[str] = None
    """The ID of the secret.

    For example 'secret:dcc7aa9c-7202-4da6-8d5f-0fbbaa4e1a41' (from JUJU_SECRET_ID).
    """

    secret_label: Optional[str] = None
    """The label of the secret.

    For example 'db-password' (from JUJU_SECRET_LABEL).
    """

    secret_revision: Optional[int] = None
    """The revision of the secret.

    For example 42 (integer) (from JUJU_SECRET_REVISION).
    """

    storage_name: Optional[str] = None
    """The storage name.

    For example 'my-storage' if the original environment variable's value is 'my-storage/1'
    (from JUJU_STORAGE_ID).
    """

    unit_name: str = ''
    """The name of the unit.

    For example 'myapp/0' (from JUJU_UNIT_NAME).
    """

    version: JujuVersion = dataclasses.field(default_factory=lambda: JujuVersion('0.0.0'))
    """The version of Juju.

    For example '3.4.0' (from JUJU_VERSION).
    """

    workload_name: Optional[str] = None
    """The name of the workload.

    For example 'workload' (from JUJU_WORKLOAD_NAME).
    """

    @classmethod
    def from_dict(cls, env: Mapping[str, Any]) -> '_JujuContext':
        return _JujuContext(
            action_name=env.get('JUJU_ACTION_NAME') or None,
            action_uuid=env.get('JUJU_ACTION_UUID') or None,
            charm_dir=(
                Path(env['JUJU_CHARM_DIR']).resolve()
                if env.get('JUJU_CHARM_DIR')
                else Path(f'{__file__}/../../..').resolve()
            ),
            debug='JUJU_DEBUG' in env,
            debug_at=(
                {x.strip() for x in env['JUJU_DEBUG_AT'].split(',')}
                if env.get('JUJU_DEBUG_AT')
                else set()
            ),
            dispatch_path=env.get('JUJU_DISPATCH_PATH', ''),
            model_name=env.get('JUJU_MODEL_NAME', ''),
            model_uuid=env.get('JUJU_MODEL_UUID', ''),
            notice_id=env.get('JUJU_NOTICE_ID') or None,
            notice_key=env.get('JUJU_NOTICE_KEY') or None,
            notice_type=env.get('JUJU_NOTICE_TYPE') or None,
            pebble_check_name=env.get('JUJU_PEBBLE_CHECK_NAME') or None,
            relation_departing_unit_name=env.get('JUJU_DEPARTING_UNIT') or None,
            relation_name=env.get('JUJU_RELATION') or None,
            relation_id=(
                int(env['JUJU_RELATION_ID'].split(':')[-1])
                if env.get('JUJU_RELATION_ID')
                else None
            ),
            remote_app_name=env.get('JUJU_REMOTE_APP') or None,
            remote_unit_name=env.get('JUJU_REMOTE_UNIT') or None,
            secret_id=env.get('JUJU_SECRET_ID') or None,
            secret_label=env.get('JUJU_SECRET_LABEL') or None,
            secret_revision=(
                int(env['JUJU_SECRET_REVISION']) if env.get('JUJU_SECRET_REVISION') else None
            ),
            storage_name=(
                env.get('JUJU_STORAGE_ID', '').split('/')[0]
                if env.get('JUJU_STORAGE_ID')
                else None
            ),
            unit_name=env.get('JUJU_UNIT_NAME', ''),
            version=JujuVersion(env['JUJU_VERSION']),
            workload_name=env.get('JUJU_WORKLOAD_NAME') or None,
        )
