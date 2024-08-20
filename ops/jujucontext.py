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
import os
import re
from functools import total_ordering
from pathlib import Path
from typing import Any, Mapping, Optional, Union


@total_ordering
class JujuVersion:
    """Helper to work with the Juju version.

    It knows how to parse the ``JUJU_VERSION`` environment variable, and
    exposes different capabilities according to the specific version. It also
    allows users to compare ``JujuVersion`` instances with ``<`` and ``>``
    operators.
    """

    _pattern_re = re.compile(
        r"""^
    (?P<major>\d{1,9})\.(?P<minor>\d{1,9})       # <major> and <minor> numbers are always there
    ((?:\.|-(?P<tag>[a-z]+))(?P<patch>\d{1,9}))? # sometimes with .<patch> or -<tag><patch>
    (\.(?P<build>\d{1,9}))?$                     # and sometimes with a <build> number.
    """,
        re.VERBOSE,
    )

    def __init__(self, version: str):
        m = self._pattern_re.match(version)
        if not m:
            raise RuntimeError(f'"{version}" is not a valid Juju version string')

        d = m.groupdict()
        self.major = int(m.group('major'))
        self.minor = int(m.group('minor'))
        self.tag = d['tag'] or ''
        self.patch = int(d['patch'] or 0)
        self.build = int(d['build'] or 0)

    def __repr__(self):
        if self.tag:
            s = f'{self.major}.{self.minor}-{self.tag}{self.patch}'
        else:
            s = f'{self.major}.{self.minor}.{self.patch}'
        if self.build > 0:
            s += f'.{self.build}'
        return s

    def __eq__(self, other: Union[str, 'JujuVersion']) -> bool:
        if self is other:
            return True
        if isinstance(other, str):
            other = type(self)(other)
        elif not isinstance(other, JujuVersion):
            raise RuntimeError(f'cannot compare Juju version "{self}" with "{other}"')
        return (
            self.major == other.major
            and self.minor == other.minor
            and self.tag == other.tag
            and self.build == other.build
            and self.patch == other.patch
        )

    def __lt__(self, other: Union[str, 'JujuVersion']) -> bool:
        if self is other:
            return False
        if isinstance(other, str):
            other = type(self)(other)
        elif not isinstance(other, JujuVersion):
            raise RuntimeError(f'cannot compare Juju version "{self}" with "{other}"')
        if self.major != other.major:
            return self.major < other.major
        elif self.minor != other.minor:
            return self.minor < other.minor
        elif self.tag != other.tag:
            if not self.tag:
                return False
            elif not other.tag:
                return True
            return self.tag < other.tag
        elif self.patch != other.patch:
            return self.patch < other.patch
        elif self.build != other.build:
            return self.build < other.build
        return False

    @classmethod
    def from_environ(cls) -> 'JujuVersion':
        """Build a version from the ``JUJU_VERSION`` environment variable."""
        v = os.environ.get('JUJU_VERSION')
        if v is None:
            v = '0.0.0'
        return cls(v)

    def has_app_data(self) -> bool:
        """Report whether this Juju version supports app data."""
        return (self.major, self.minor, self.patch) >= (2, 7, 0)

    def is_dispatch_aware(self) -> bool:
        """Report whether this Juju version supports dispatch."""
        return (self.major, self.minor, self.patch) >= (2, 8, 0)

    def has_controller_storage(self) -> bool:
        """Report whether this Juju version supports controller-side storage."""
        return (self.major, self.minor, self.patch) >= (2, 8, 0)

    @property
    def has_secrets(self) -> bool:
        """Report whether this Juju version supports the "secrets" feature."""
        # Juju version 3.0.0 had an initial version of secrets, but:
        # * In 3.0.2, secret-get "--update" was renamed to "--refresh", and
        #   secret-get-info was separated into its own hook tool
        # * In 3.0.3, a bug with observer labels was fixed (juju/juju#14916)
        return (self.major, self.minor, self.patch) >= (3, 0, 3)

    @property
    def supports_open_port_on_k8s(self) -> bool:
        """Report whether this Juju version supports open-port on Kubernetes."""
        # Support added: https://bugs.launchpad.net/juju/+bug/1920960
        return (self.major, self.minor, self.patch) >= (3, 0, 3)

    @property
    def supports_exec_service_context(self) -> bool:
        """Report whether this Juju version supports exec's service_context option."""
        if (self.major, self.minor, self.patch) < (3, 1, 6):
            # First released in 3.1.6
            return False
        if (self.major, self.minor, self.patch) == (3, 2, 0):
            # 3.2.0 was released before Pebble was updated, but all other 3.2
            # releases have the change (3.2.1 tag was never released).
            return False
        return True


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
                Path(f'{__file__}/../../..').resolve()
                if not env.get('JUJU_CHARM_DIR')
                else Path(env['JUJU_CHARM_DIR']).resolve()
            ),
            debug='JUJU_DEBUG' in env,
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
