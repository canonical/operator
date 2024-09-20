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

from ._private.harness import (
    ActionFailed,
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

# The Harness testing framework.
_ = ActionFailed
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
_ = Container
_ = ExecProcess
_ = RelationNotFoundError
_ = RelationRole
_ = charm
_ = framework
_ = model
_ = pebble
_ = storage
