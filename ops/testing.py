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

- :class:`ops.testing.Context`, :class:`ops.testing.State`, and other classes
  to represent the simulated Juju environment for state-transition testing.
  These are available when the `ops[testing]` optional extra is installed.
- :class:`ops.testing.Harness`, a deprecated class to set up the simulated environment,
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
    on testing charms, see `Testing <https://documentation.ubuntu.com/ops/latest/explanation/testing/>`_.
"""

# ruff: noqa: F401 (unused import)
# pyright: reportUnusedImport=false

from __future__ import annotations

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
    from scenario import (
        ActiveStatus,
        Address,
        AnyJson,
        BindAddress,
        BlockedStatus,
        CharmEvents,
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
except ImportError:
    pass
else:
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
