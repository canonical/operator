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

from __future__ import annotations

import dataclasses
import typing
from pathlib import Path
from typing import Any, Mapping, TypeAlias

from .jujuversion import JujuVersion


@dataclasses.dataclass(frozen=True)
class _JujuContext:
    """_JujuContext collects information from environment variables named 'JUJU_*'.

    Source: https://documentation.ubuntu.com/juju/3.6/reference/hook/#hook-execution.
    The HookVars function: https://github.com/juju/juju/blob/3.6/worker/uniter/runner/context/context.go#L1398.
    Only a subset of the above source, because these are what are used in ops.
    """

    action_name: str | None = None
    """The action's name.

    For example 'backup' (from JUJU_ACTION_NAME).
    """

    action_uuid: str | None = None
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

    debug_at: set[str] = dataclasses.field(default_factory=set[str])
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

    notice_id: str | None = None
    """The ID of the notice.

    For example '1', (from JUJU_NOTICE_ID).
    """

    notice_key: str | None = None
    """The key of the notice.

    For example 'example.com/a', (from JUJU_NOTICE_KEY).
    """

    notice_type: str | None = None
    """The type of the notice.

    For example 'custom' (from JUJU_NOTICE_TYPE).
    """

    pebble_check_name: str | None = None
    """The name of the pebble check.

    For example 'http-check' (from JUJU_PEBBLE_CHECK_NAME).
    """

    relation_departing_unit_name: str | None = None
    """The unit that is departing a relation.

    For example 'remote/42' (from JUJU_DEPARTING_UNIT).
    """

    relation_name: str | None = None
    """The name of the relation.

    For example 'database' (from JUJU_RELATION).
    """

    relation_id: int | None = None
    """The id of the relation.

    For example 1 (integer) if the original environment variable's value is 'database:1'
    (from JUJU_RELATION_ID).
    """

    remote_app_name: str | None = None
    """The name of the remote app.

    For example 'remoteapp1' (from JUJU_REMOTE_APP).
    """

    remote_unit_name: str | None = None
    """The name of the remote unit.

    For example 'remoteapp1/0' (from JUJU_REMOTE_UNIT).
    """

    secret_id: str | None = None
    """The ID of the secret.

    For example 'secret:dcc7aa9c-7202-4da6-8d5f-0fbbaa4e1a41' (from JUJU_SECRET_ID).
    """

    secret_label: str | None = None
    """The label of the secret.

    For example 'db-password' (from JUJU_SECRET_LABEL).
    """

    secret_revision: int | None = None
    """The revision of the secret.

    For example 42 (integer) (from JUJU_SECRET_REVISION).
    """

    storage_name: str | None = None
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

    workload_name: str | None = None
    """The name of the workload.

    For example 'workload' (from JUJU_WORKLOAD_NAME).
    """

    @classmethod
    def from_dict(cls, env: Mapping[str, Any]) -> _JujuContext:
        kwargs: _JujuContextKwargs = {}
        # simple keys that copy the environment variable without modification
        simple_keys: tuple[SimpleKeys, ...] = typing.get_args(SimpleKeys)
        for key in simple_keys:
            if val := env.get(f'JUJU_{key.upper()}'):
                kwargs[key] = val
        # keys that do something a little fancier
        if juju_charm_dir := env.get('JUJU_CHARM_DIR'):
            kwargs['charm_dir'] = Path(juju_charm_dir).resolve()
        if 'JUJU_DEBUG' in env:
            kwargs['debug'] = True
        if juju_debug_at := env.get('JUJU_DEBUG_AT'):
            kwargs['debug_at'] = {x.strip() for x in juju_debug_at.split(',')}
        if juju_departing_unit := env.get('JUJU_DEPARTING_UNIT'):
            kwargs['relation_departing_unit_name'] = juju_departing_unit
        if juju_relation := env.get('JUJU_RELATION'):
            kwargs['relation_name'] = juju_relation
        if juju_relation_id := env.get('JUJU_RELATION_ID'):
            kwargs['relation_id'] = int(juju_relation_id.split(':')[-1])
        if juju_remote_app := env.get('JUJU_REMOTE_APP'):
            kwargs['remote_app_name'] = juju_remote_app
        if juju_remote_unit := env.get('JUJU_REMOTE_UNIT'):
            kwargs['remote_unit_name'] = juju_remote_unit
        if juju_secret_revision := env.get('JUJU_SECRET_REVISION'):
            kwargs['secret_revision'] = int(juju_secret_revision)
        if juju_storage_id := env.get('JUJU_STORAGE_ID'):
            kwargs['storage_name'] = juju_storage_id.partition('/')[0]
        if juju_version := env.get('JUJU_VERSION'):
            kwargs['version'] = JujuVersion(juju_version)
        return _JujuContext(**kwargs)


class _JujuContextKwargs(typing.TypedDict, total=False):
    action_name: str
    action_uuid: str
    charm_dir: Path
    debug: bool
    debug_at: set[str]
    dispatch_path: str
    model_name: str
    model_uuid: str
    notice_id: str
    notice_key: str
    notice_type: str
    pebble_check_name: str
    relation_departing_unit_name: str
    relation_name: str
    relation_id: int
    remote_app_name: str
    remote_unit_name: str
    secret_id: str
    secret_label: str
    secret_revision: int
    storage_name: str
    unit_name: str
    version: JujuVersion
    workload_name: str


SimpleKeys: TypeAlias = typing.Literal[
    'action_name',
    'action_uuid',
    'dispatch_path',
    'model_name',
    'model_uuid',
    'notice_id',
    'notice_key',
    'notice_type',
    'pebble_check_name',
    'secret_id',
    'secret_label',
    'unit_name',
    'workload_name',
]
