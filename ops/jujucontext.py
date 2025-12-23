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

"""A helper to work with the Juju context."""

from __future__ import annotations

import dataclasses
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .jujuversion import JujuVersion


@dataclasses.dataclass(frozen=True, kw_only=True)
class JujuContext:
    """Provides the Juju hook context, primarily for charming approaches outside of Ops.

    Juju provides context for the hook in the form of environment variables.
    Rather than directly accessing the environment, charms should use
    :meth:`ops.JujuContext.from_environ` to create a ``JujuContext`` object that contains this
    information.

    Most of the information in ``JujuContext`` is exposed through the
    framework. For example :attr:`ops.JujuContext.model_name` is
    :attr:`ops.Model.name`, and :attr:`ops.JujuContext.action_uuid` is
    :attr:`ops.ActionEvent.id`. Typically, charms should not directly use the
    ``JujuContext`` class -- it is primarily provided to support charming
    approaches outside of the Ops framework.
    """

    # Source: https://documentation.ubuntu.com/juju/3.6/reference/hook/#hook-execution.
    # The HookVars function: https://github.com/juju/juju/blob/be9dce813b631a469eb8ca8b5c6bc3c0fe82b954/internal/worker/uniter/runner/context/context.go#L1398
    # Only a subset of the above source, because these are what are used in ops.

    # These variables are expected to be set in all hooks, and have no sensible default.

    dispatch_path: str
    """The dispatch path in the format of 'actions/do-something'.

    For example 'hooks/workload-pebble-ready' (from ``JUJU_DISPATCH_PATH``).
    """

    hook_name: str
    """The name of the hook.

    For example, 'install' (from ``JUJU_HOOK_NAME``). Note that this is the empty
    string for actions, and for relation, storage, and workload hooks the name
    will be prefixed with the name of the relation, storage, or workload.
    """

    model_name: str
    """The name of the model.

    For example 'foo' (from ``JUJU_MODEL_NAME``).
    """

    model_uuid: str
    """The uuid of the model.

    For example 'cdac5656-2423-4388-8f30-41854b4cca7d' (from ``JUJU_MODEL_UUID``).
    """

    unit_name: str
    """The name of the unit.

    For example 'myapp/0' (from ``JUJU_UNIT_NAME``).
    """

    version: JujuVersion
    """The version of Juju.

    For example '3.4.0' (from ``JUJU_VERSION``).
    """

    # These variables are expected to be set in all hooks, but have reasonable defaults.

    availability_zone: str | None = None
    """The availability zone.

    For example, 'zone1' (from ``JUJU_AVAILABILITY_ZONE``).
    """

    charm_dir: Path = dataclasses.field(
        default_factory=lambda: Path(f'{__file__}/../../..').resolve()
    )
    """The directory where the charm is running.

    For example '/var/lib/juju/agents/unit-bare-0/charm' (from ``JUJU_CHARM_DIR``).
    """

    debug: bool = False
    """Debug mode.

    If true, write logs to stderr as well as to juju-log (from ``JUJU_DEBUG``).
    """

    debug_at: set[str] = dataclasses.field(default_factory=set[str])
    """Where you want to stop when debugging.

    For example 'all' (from ``JUJU_DEBUG_AT``).
    """

    machine_id: str | None = None
    """The ID of the machine.

    For example, 1 (from ``JUJU_MACHINE_ID``).
    """

    principal_unit: str | None = None
    """The name of the principal unit.

    For example, 'myapp/0' (from ``JUJU_PRINCIPAL_UNIT``).
    """

    # The remaining variables are all context for specific types of events.

    action_name: str | None = None
    """The action's name, for action events.

    For example 'backup' (from ``JUJU_ACTION_NAME``).
    """

    action_uuid: str | None = None
    """The action's uuid, for action events.

    For example '1' (from ``JUJU_ACTION_UUID``).
    """

    notice_id: str | None = None
    """The ID of the notice, for Pebble notice events.

    For example '1', (from ``JUJU_NOTICE_ID``).
    """

    notice_key: str | None = None
    """The key of the notice, for Pebble notice events.

    For example 'example.com/a', (from ``JUJU_NOTICE_KEY``).
    """

    notice_type: str | None = None
    """The type of the notice, for Pebble notice events.

    For example 'custom' (from ``JUJU_NOTICE_TYPE``).
    """

    pebble_check_name: str | None = None
    """The name of the pebble check, for Pebble check events.

    For example 'http-check' (from ``JUJU_PEBBLE_CHECK_NAME``).
    """

    relation_departing_unit_name: str | None = None
    """The unit that is departing a relation, for relation events.

    For example 'remote/42' (from ``JUJU_DEPARTING_UNIT``).
    """

    relation_name: str | None = None
    """The name of the relation, for relation events.

    For example 'database' (from ``JUJU_RELATION``).
    """

    relation_id: int | None = None
    """The id of the relation, for relation events.

    For example 1 (integer) if the original environment variable's value is 'database:1'
    (from ``JUJU_RELATION_ID``).
    """

    remote_app_name: str | None = None
    """The name of the remote app, for relation events.

    For example 'remoteapp1' (from ``JUJU_REMOTE_APP``).
    """

    remote_unit_name: str | None = None
    """The name of the remote unit, for relation events.

    For example 'remoteapp1/0' (from ``JUJU_REMOTE_UNIT``).
    """

    secret_id: str | None = None
    """The ID of the secret, for secret events.

    For example 'secret:dcc7aa9c-7202-4da6-8d5f-0fbbaa4e1a41' (from ``JUJU_SECRET_ID``).
    """

    secret_label: str | None = None
    """The label of the secret, for secret events.

    For example 'db-password' (from ``JUJU_SECRET_LABEL``).
    """

    secret_revision: int | None = None
    """The revision of the secret, for secret events.

    For example 42 (integer) (from ``JUJU_SECRET_REVISION``).
    """

    storage_index: int | None = None
    """The storage index, for storage events.

    For example 1 (integer) if the original environment variable's value is 'my-storage/1'
    (from ``JUJU_STORAGE_ID``).
    """

    storage_name: str | None = None
    """The storage name, for storage events.

    For example 'my-storage' if the original environment variable's value is 'my-storage/1'
    (from ``JUJU_STORAGE_ID``).
    """

    workload_name: str | None = None
    """The name of the workload, for workload events.

    For example 'workload' (from ``JUJU_WORKLOAD_NAME``).
    """

    @classmethod
    def _from_dict(cls, env: Mapping[str, Any]) -> JujuContext:
        return JujuContext(
            action_name=env.get('JUJU_ACTION_NAME') or None,
            action_uuid=env.get('JUJU_ACTION_UUID') or None,
            availability_zone=env.get('JUJU_AVAILABILITY_ZONE') or None,
            # If JUJU_CHARM_DIR is None or set to an empty string, use Path(f'{__file__}/../../..')
            # as default (assuming the '$JUJU_CHARM_DIR/lib/op/main.py' structure).
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
            hook_name=env.get('JUJU_HOOK_NAME', ''),
            machine_id=env.get('JUJU_MACHINE_ID') or None,
            model_name=env.get('JUJU_MODEL_NAME', ''),
            model_uuid=env.get('JUJU_MODEL_UUID', ''),
            notice_id=env.get('JUJU_NOTICE_ID') or None,
            notice_key=env.get('JUJU_NOTICE_KEY') or None,
            notice_type=env.get('JUJU_NOTICE_TYPE') or None,
            pebble_check_name=env.get('JUJU_PEBBLE_CHECK_NAME') or None,
            principal_unit=env.get('JUJU_PRINCIPAL_UNIT') or None,
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
            storage_index=(
                int(env['JUJU_STORAGE_ID'].split('/')[-1]) if env.get('JUJU_STORAGE_ID') else None
            ),
            storage_name=(
                env.get('JUJU_STORAGE_ID', '').split('/')[0]
                if env.get('JUJU_STORAGE_ID')
                else None
            ),
            unit_name=env.get('JUJU_UNIT_NAME', ''),
            # The meter-status-changed event, triggered by `juju set-meter-status`,
            # does not set JUJU_VERSION, but all other events do. When we drop support
            # for Juju 2 and Juju 3 we can change this to always expect JUJU_VERSION,
            # as that event no longer exists in Juju 4.
            version=JujuVersion(env.get('JUJU_VERSION', '0.0.0')),
            workload_name=env.get('JUJU_WORKLOAD_NAME') or None,
        )

    @classmethod
    def from_environ(cls, environ: Mapping[str, str] | None = None) -> JujuContext:
        """Create a ``JujuContext`` object from the environment.

        If environ is ``None``, ``os.environ`` will be used.

        Raises:
            ValueError: If any required environment variables are missing.
        """
        if environ is None:
            environ = os.environ
        assert environ is not None

        required = (
            'JUJU_DISPATCH_PATH',
            'JUJU_HOOK_NAME',
            'JUJU_MODEL_NAME',
            'JUJU_MODEL_UUID',
            'JUJU_UNIT_NAME',
            'JUJU_VERSION',
        )
        for var in required:
            if var not in environ:
                raise ValueError(f'Missing required environment variable: {var}')

        event = environ['JUJU_HOOK_NAME']
        # These events have no additional context.
        if event in (
            'install',
            'start',
            'stop',
            'remove',
            'config-changed',
            'update-status',
            'upgrade-charm',
            'leader-elected',
        ):
            return cls._from_dict(environ)

        if event in ('secret-changed', 'secret-rotate', 'secret-remove', 'secret-expired'):
            # JUJU_SECRET_LABEL may be missing if the secret does not have a label.
            if 'JUJU_SECRET_ID' not in environ:
                raise ValueError('Missing required environment variable: JUJU_SECRET_ID')
            if (
                event in ('secret-remove', 'secret-expired')
                and 'JUJU_SECRET_REVISION' not in environ
            ):
                raise ValueError('Missing required environment variable: JUJU_SECRET_REVISION')

        if event == '' and environ['JUJU_DISPATCH_PATH'].startswith('actions/'):
            for var in ('JUJU_ACTION_NAME', 'JUJU_ACTION_UUID'):
                if var not in environ:
                    raise ValueError(f'Missing required environment variable: {var}')

        if event.endswith('-pebble-custom-notice'):
            for var in (
                'JUJU_WORKLOAD_NAME',
                'JUJU_NOTICE_ID',
                'JUJU_NOTICE_KEY',
                'JUJU_NOTICE_TYPE',
            ):
                if var not in environ:
                    raise ValueError(f'Missing required environment variable: {var}')

        if event.endswith(('-pebble-check-failed', '-pebble-check-recovered')):
            for var in ('JUJU_WORKLOAD_NAME', 'JUJU_PEBBLE_CHECK_NAME'):
                if var not in environ:
                    raise ValueError(f'Missing required environment variable: {var}')

        if event.endswith('-pebble-ready') and 'JUJU_WORKLOAD_NAME' not in environ:
            raise ValueError('Missing required environment variable: JUJU_WORKLOAD_NAME')

        if (
            event.endswith(('-storage-attached', '-storage-detaching'))
            and 'JUJU_STORAGE_ID' not in environ
        ):
            raise ValueError('Missing required environment variable: JUJU_STORAGE_ID')

        if event.endswith((
            '-relation-created',
            '-relation-joined',
            '-relation-changed',
            '-relation-departed',
            '-relation-broken',
        )):
            for var in ('JUJU_RELATION', 'JUJU_RELATION_ID', 'JUJU_REMOTE_APP'):
                if var not in environ:
                    raise ValueError(f'Missing required environment variable: {var}')
            if (
                event.endswith(('-relation-joined', '-relation-changed', '-relation-departed'))
                and 'JUJU_REMOTE_UNIT' not in environ
            ):
                raise ValueError('Missing required environment variable: JUJU_REMOTE_UNIT')
            if event.endswith('-relation-departed') and 'JUJU_DEPARTING_UNIT' not in environ:
                raise ValueError('Missing required environment variable: JUJU_DEPARTING_UNIT')

        return cls._from_dict(environ)
