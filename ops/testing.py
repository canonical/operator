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
    on testing charms, see `Charm SDK | Testing <https://juju.is/docs/sdk/testing>`_.
"""

import typing as _typing
from importlib.metadata import PackageNotFoundError as _PackageNotFoundError
from importlib.metadata import version as _get_package_version

from ._private.harness import (
    ActionOutput,
    AppUnitOrName,
    CharmBase,
    CharmMeta,
    CharmType,
    Container,
    ExecArgs,
    ExecHandler,
    ExecProcess,
    ExecResult,
    Harness,
    ReadableBuffer,
    RelationNotFoundError,
    RelationRole,
    YAMLStringOrFile,
    charm,
    framework,
    model,
    pebble,
    storage,
)

# If the 'ops.testing' optional extra is installed, make those
# names available in this namespace.
try:
    _version = _get_package_version('ops-scenario')
except _PackageNotFoundError:
    from ops._private.harness import ActionFailed  # type: ignore
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
        )
        from scenario.context import CharmEvents

        # The Scenario unit testing framework.
        _ = ActiveStatus
        _ = Address
        _ = AnyJson
        _ = BindAddress
        _ = BlockedStatus
        _ = CharmEvents
        _ = CheckInfo
        _ = CloudCredential
        _ = CloudSpec
        _ = Container
        _ = Context
        _ = DeferredEvent
        _ = ErrorStatus
        _ = Exec
        _ = ICMPPort
        _ = JujuLogLine
        _ = MaintenanceStatus
        _ = Manager
        _ = Model
        _ = Mount
        _ = Network
        _ = Notice
        _ = PeerRelation
        _ = Port
        _ = RawDataBagContents
        _ = RawSecretRevisionContents
        _ = Relation
        _ = RelationBase
        _ = Resource
        _ = Secret
        _ = State
        _ = Storage
        _ = StoredState
        _ = SubordinateRelation
        _ = TCPPort
        _ = UDPPort
        _ = UnitID
        _ = UnknownStatus
        _ = WaitingStatus
        _ = errors

        # Handle the name clash between Harness's and Scenario's ActionFailed.
        class ActionFailed(Exception):  # noqa: N818
            """Raised when :code:`event.fail()` is called during an action handler."""

            message: str
            """Optional details of the failure, as provided by :meth:`ops.ActionEvent.fail`."""

            output: ActionOutput
            """Any logs and results set by the Charm.

            When using Context.run, both logs and results will be empty - these
            can be found in Context.action_logs and Context.action_results.
            """

            state: _typing.Optional[State]
            """The Juju state after the action has been run.

            When using Harness.run_action, this will be None.
            """

            def __init__(
                self,
                message: str,
                output: _typing.Optional[ActionOutput] = None,
                *,
                state: _typing.Optional[State] = None,
            ):
                self.message = message
                self.output = ActionOutput([], {}) if output is None else output
                self.state = state

        # Monkeypatch this merged one in so that isinstance checks work.
        import ops._private.harness as _harness

        _harness.ActionFailed = ActionFailed
        import scenario.context as _context
        import scenario.runtime as _runtime

        _context.ActionFailed = ActionFailed  # type: ignore[reportPrivateImportUsage]
        _runtime.ActionFailed = ActionFailed  # type: ignore[reportPrivateImportUsage]
    else:
        from ops._private.harness import ActionFailed  # type: ignore

# The Harness unit testing framework.
_ = ActionFailed  # If Scenario has been installed, then this will be the merged ActionFailed.
_ = ActionOutput
_ = AppUnitOrName
_ = CharmType
_ = ExecArgs
_ = ExecHandler
_ = ExecResult
_ = Harness
_ = ReadableBuffer
_ = YAMLStringOrFile

# Names exposed for backwards compatibility
_ = CharmBase
_ = CharmMeta
_ = Container  # If Scenario has been installed, then this will be scenario.Container.
_ = ExecProcess
_ = RelationNotFoundError
_ = RelationRole
_ = charm
_ = framework
_ = model
_ = pebble
_ = storage
