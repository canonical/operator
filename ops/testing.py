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
"""Framework for unit testing charms in a simulated Juju environment.

The module includes:

- :class:`ops.testing.Harness`, a class to set up the simulated environment,
  that provides:

  - :meth:`~ops.testing.Harness.add_relation` method, to declare a relation
    (integration) with another app.
  - :meth:`~ops.testing.Harness.begin` and :meth:`~ops.testing.Harness.cleanup`
    methods to start and end the testing lifecycle.
  - :meth:`~ops.testing.Harness.evaluate_status` method, which aggregates the
    status of the charm after test interactions.
  - :attr:`~ops.testing.Harness.model` attribute, which exposes e.g. the
    :attr:`~ops.Model.unit` attribute for detailed assertions on the unit's state.

.. note::
    Unit testing is only one aspect of a comprehensive testing strategy. For more
    on testing charms, see `Testing <https://ops.readthedocs.io/en/latest/explanation/testing.html>`_.
"""

# ruff: noqa: F401 (unused import)
# pyright: reportUnusedImport=false

from __future__ import annotations

import importlib.metadata

from . import charm, framework, model, pebble, storage
from ._private.harness import (
    ActionFailed,
    ActionOutput,
    AppUnitOrName,
    CharmType,
    ExecArgs,
    ExecHandler,
    ExecResult,
    Harness,
    ReadableBuffer,
    YAMLStringOrFile,
)
from .charm import CharmBase, CharmMeta, RelationRole
from .model import Container, RelationNotFoundError
from .pebble import ExecProcess

# The Harness unit testing framework.
__all__ = [
    'ActionFailed',
    'ActionOutput',
    'AppUnitOrName',
    'CharmType',
    'ExecArgs',
    'ExecHandler',
    'ExecResult',
    'Harness',
    'ReadableBuffer',
    'YAMLStringOrFile',
]

# If the 'ops.testing' optional extra is installed, make those
# names available in this namespace.
try:
    _version = importlib.metadata.version('ops-scenario')
except importlib.metadata.PackageNotFoundError:
    pass
else:
    if _version and int(_version.split('.', 1)[0]) >= 7:
        from scenario import (
            ActiveStatus,
            Address,
            AnyJson,
            BindAddress,
            BlockedStatus,
            CheckInfo,
            CloudCredential,
            CloudSpec,
            Container,
            Context,
            DeferredEvent,
            ErrorStatus,
            Exec,
            ICMPPort,
            JujuLogLine,
            MaintenanceStatus,
            Manager,
            Model,
            Mount,
            Network,
            Notice,
            PeerRelation,
            Port,
            RawDataBagContents,
            RawSecretRevisionContents,
            Relation,
            RelationBase,
            Resource,
            Secret,
            State,
            Storage,
            StoredState,
            SubordinateRelation,
            TCPPort,
            UDPPort,
            UnitID,
            UnknownStatus,
            WaitingStatus,
            errors,
            layer_from_rockcraft,
        )

        # This can be imported in the group above after Scenario exposes it at the top level.
        # https://github.com/canonical/ops-scenario/pull/200
        from scenario.context import CharmEvents

        # The Scenario unit testing framework.
        __all__.extend([
            'ActiveStatus',
            'Address',
            'AnyJson',
            'BindAddress',
            'BlockedStatus',
            'CharmEvents',
            'CheckInfo',
            'CloudCredential',
            'CloudSpec',
            'Container',
            'Context',
            'DeferredEvent',
            'ErrorStatus',
            'Exec',
            'ICMPPort',
            'JujuLogLine',
            'MaintenanceStatus',
            'Manager',
            'Model',
            'Mount',
            'Network',
            'Notice',
            'PeerRelation',
            'Port',
            'RawDataBagContents',
            'RawSecretRevisionContents',
            'Relation',
            'RelationBase',
            'Resource',
            'Secret',
            'State',
            'Storage',
            'StoredState',
            'SubordinateRelation',
            'TCPPort',
            'UDPPort',
            'UnitID',
            'UnknownStatus',
            'WaitingStatus',
            'errors',
            'layer_from_rockcraft',
        ])

        # Until Scenario uses the ops._private.harness.ActionFailed, we need to
        # monkeypatch it in, so that the ops.testing.ActionFailed object is the
        # one that we expect, even if people are mixing Harness and Scenario.
        # https://github.com/canonical/ops-scenario/issues/201
        # This will be the case in the next version of ops-scenario, so this
        # code can be removed as of the release of ops-scenario after 7.0.5.
        # Remember to bump the required version of `ops-scenario` in pyproject.toml
        # at that time as well.
        try:
            import scenario._runtime as _runtime
        except ImportError:
            import scenario.runtime as _runtime  # type: ignore
        import scenario.context as _context

        _context.ActionFailed = ActionFailed  # type: ignore[reportPrivateImportUsage]
        _runtime.ActionFailed = ActionFailed

# Names exposed for backwards compatibility
_compatibility_names = [
    'CharmBase',
    'CharmMeta',
    'Container',  # If Scenario has been installed, then this will be scenario.Container.
    'ExecProcess',
    'RelationNotFoundError',
    'RelationRole',
    'charm',
    'framework',
    'model',
    'pebble',
    'storage',
]
__all__.extend(_compatibility_names)  # type: ignore[reportUnsupportedDunderAll]
