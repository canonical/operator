# Copyright 2020 Canonical Ltd.
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

"""The API to respond to Juju events and manage the application.

This API provides core features to your charm, including:

- :class:`~ops.CharmBase`, the base class for charms and :class:`~ops.Object`,
  the base class for charm libraries.
- :class:`~ops.framework.EventBase` class and individual event types, like
  the :class:`~ops.ActionEvent` class.
- :class:`~ops.Framework` class, the main interface for the charm to `ops` library
  infrastructure, including:

  - :attr:`~ops.Framework.on` shorthand property used to
    :meth:`~ops.Framework.observe` and react to Juju events.
  - :attr:`~ops.Framework.model` attribute to get hold of the Model instance.

- :class:`~ops.model.Model` class that represents the Juju model, accessible as
  ``self.model`` in a charm, including:

  - :attr:`~ops.Model.app` attribute, representing the application associated
    with the charm.
  - :attr:`~ops.Model.unit` attribute, representing the unit of the application
    the charm is running on.
  - :attr:`~ops.Model.relations` attribute, which provides access to relations
    (integrations) defined in the charm, allowing interaction with other applications.

- :class:`~ops.Container` class to control Kubernetes workloads, including:

  - :meth:`~ops.Container.add_layer` and :meth:`~ops.Container.replan` methods
    to update Pebble configuration.
  - :meth:`~ops.Container.pull` and :meth:`~ops.Container.push` methods to copy
    data to and from a container, respectively.
  - :meth:`~ops.Container.exec` method to run arbitrary commands inside the
    container.

- :class:`~ops.StatusBase` class and individual status types, like the
  :class:`~ops.ActiveStatus` class.
"""

from __future__ import annotations

# The "from .X import Y" imports below don't explicitly tell Pyright (or MyPy)
# that those symbols are part of the public API, so we have to add __all__.
__all__ = [  # noqa: RUF022 `__all__` is not sorted
    '__version__',
    'main',
    'tracing',
    'pebble',
    # From charm.py
    'ActionEvent',
    'ActionMeta',
    'CharmBase',
    'CharmEvents',
    'CharmMeta',
    'CollectMetricsEvent',
    'CollectStatusEvent',
    'ConfigChangedEvent',
    'ConfigMeta',
    'ContainerBase',
    'ContainerMeta',
    'ContainerStorageMeta',
    'HookEvent',
    'InstallEvent',
    'JujuAssumes',
    'JujuAssumesCondition',
    'LeaderElectedEvent',
    'LeaderSettingsChangedEvent',
    'MetadataLinks',
    'PayloadMeta',
    'PebbleCheckEvent',
    'PebbleCheckFailedEvent',
    'PebbleCheckRecoveredEvent',
    'PebbleCustomNoticeEvent',
    'PebbleNoticeEvent',
    'PebbleReadyEvent',
    'PostSeriesUpgradeEvent',
    'PreSeriesUpgradeEvent',
    'RelationBrokenEvent',
    'RelationChangedEvent',
    'RelationCreatedEvent',
    'RelationDepartedEvent',
    'RelationEvent',
    'RelationJoinedEvent',
    'RelationMeta',
    'RelationRole',
    'RemoveEvent',
    'RemoteModel',
    'ResourceMeta',
    'SecretChangedEvent',
    'SecretEvent',
    'SecretExpiredEvent',
    'SecretRemoveEvent',
    'SecretRotateEvent',
    'StartEvent',
    'StopEvent',
    'StorageAttachedEvent',
    'StorageDetachingEvent',
    'StorageEvent',
    'StorageMeta',
    'UpdateStatusEvent',
    'UpgradeCharmEvent',
    'WorkloadEvent',
    # From framework.py
    'BoundEvent',
    'BoundStoredState',
    'CommitEvent',
    'EventBase',
    'EventSource',
    'Framework',
    'FrameworkEvents',
    'Handle',
    'HandleKind',
    'LifecycleEvent',
    'NoTypeError',
    'Object',
    'ObjectEvents',
    'PreCommitEvent',
    'PrefixedEvents',
    'Serializable',
    'StoredDict',
    'StoredList',
    'StoredSet',
    'StoredState',
    'StoredStateData',
    # From hookcmds.py
    'StatusName',
    # From jujucontext.py
    'JujuContext',
    # From jujuversion.py
    'JujuVersion',
    # From model.py
    'ActiveStatus',
    'Application',
    'Binding',
    'BindingMapping',
    'BlockedStatus',
    'CheckInfoMapping',
    'CloudCredential',
    'CloudSpec',
    'ConfigData',
    'Container',
    'ContainerMapping',
    'ErrorStatus',
    'InvalidStatusError',
    'LazyCheckInfo',
    'LazyMapping',
    'LazyNotice',
    'MaintenanceStatus',
    'Model',
    'ModelError',
    'MultiPushPullError',
    'Network',
    'NetworkInterface',
    'OpenedPort',
    'Pod',
    'Port',
    'Relation',
    'RelationData',
    'RelationDataAccessError',
    'RelationDataContent',
    'RelationDataError',
    'RelationDataTypeError',
    'RelationMapping',
    'RelationNotFoundError',
    'Resources',
    'Secret',
    'SecretInfo',
    'SecretNotFoundError',
    'SecretRotate',
    'ServiceInfoMapping',
    'StatusBase',
    'Storage',
    'StorageMapping',
    'TooManyRelatedAppsError',
    'Unit',
    'UnknownStatus',
    'WaitingStatus',
]

# The isort command wants to rearrange the nicely-formatted imports below;
# just skip it for this file.
# isort:skip_file

# Import pebble explicitly. It's the one module we don't import names from below.
from . import pebble

# Also import charm explicitly. This is not strictly necessary as the
# "from .charm" import automatically does that, but be explicit since this
# import was here previously
from . import charm

from . import _main
from . import main as _legacy_main

# Explicitly import names from submodules so users can just "import ops" and
# then use them as "ops.X".
from .charm import (
    ActionEvent,
    ActionMeta,
    CharmBase,
    CharmEvents,
    CharmMeta,
    CollectMetricsEvent,
    CollectStatusEvent,
    ConfigChangedEvent,
    ConfigMeta,
    ContainerBase,
    ContainerMeta,
    ContainerStorageMeta,
    HookEvent,
    InstallEvent,
    JujuAssumes,
    JujuAssumesCondition,
    LeaderElectedEvent,
    LeaderSettingsChangedEvent,
    MetadataLinks,
    PayloadMeta,
    PebbleCheckEvent,
    PebbleCheckFailedEvent,
    PebbleCheckRecoveredEvent,
    PebbleCustomNoticeEvent,
    PebbleNoticeEvent,
    PebbleReadyEvent,
    PostSeriesUpgradeEvent,
    PreSeriesUpgradeEvent,
    RelationBrokenEvent,
    RelationChangedEvent,
    RelationCreatedEvent,
    RelationDepartedEvent,
    RelationEvent,
    RelationJoinedEvent,
    RelationMeta,
    RelationRole,
    RemoveEvent,
    ResourceMeta,
    SecretChangedEvent,
    SecretEvent,
    SecretExpiredEvent,
    SecretRemoveEvent,
    SecretRotateEvent,
    StartEvent,
    StopEvent,
    StorageAttachedEvent,
    StorageDetachingEvent,
    StorageEvent,
    StorageMeta,
    UpdateStatusEvent,
    UpgradeCharmEvent,
    WorkloadEvent,
)

from .framework import (
    BoundEvent,
    BoundStoredState,
    CommitEvent,
    EventBase,
    EventSource,
    Framework,
    FrameworkEvents,
    Handle,
    HandleKind,
    LifecycleEvent,
    NoTypeError,
    Object,
    ObjectEvents,
    PreCommitEvent,
    PrefixedEvents,
    Serializable,
    StoredDict,
    StoredList,
    StoredSet,
    StoredState,
    StoredStateData,
)

from .hookcmds import StatusName
from .jujucontext import JujuContext
from .jujuversion import JujuVersion

from .model import (
    ActiveStatus,
    Application,
    Binding,
    BindingMapping,
    BlockedStatus,
    CheckInfoMapping,
    CloudCredential,
    CloudSpec,
    ConfigData,
    Container,
    ContainerMapping,
    ErrorStatus,
    InvalidStatusError,
    LazyCheckInfo,
    LazyMapping,
    LazyNotice,
    MaintenanceStatus,
    Model,
    ModelError,
    MultiPushPullError,
    Network,
    NetworkInterface,
    OpenedPort,
    Pod,
    Port,
    Relation,
    RelationData,
    RelationDataAccessError,
    RelationDataContent,
    RelationDataError,
    RelationDataTypeError,
    RelationMapping,
    RelationNotFoundError,
    RemoteModel,
    Resources,
    Secret,
    SecretInfo,
    SecretNotFoundError,
    SecretRotate,
    ServiceInfoMapping,
    StatusBase,
    Storage,
    StorageMapping,
    TooManyRelatedAppsError,
    Unit,
    UnknownStatus,
    WaitingStatus,
)

# NOTE: don't import testing or Harness here, as that's a test-time concern
# rather than a runtime concern.

from .version import version as __version__

try:
    # Note that ops_tracing vendors charm libs that depend on ops.
    # We import it last, after all re-exported symbols.
    import ops_tracing as tracing
except ImportError:
    tracing = None


class _Main:
    def __call__(
        self, charm_class: type[charm.CharmBase], use_juju_for_storage: bool | None = None
    ):
        return _main.main(charm_class=charm_class, use_juju_for_storage=use_juju_for_storage)

    def main(self, charm_class: type[charm.CharmBase], use_juju_for_storage: bool | None = None):
        return _legacy_main.main(
            charm_class=charm_class, use_juju_for_storage=use_juju_for_storage
        )


main = _Main()
"""Set up the charm and dispatch the observed event.

Recommended usage:

.. code-block:: python

    import ops

    class SomeCharm(ops.CharmBase): ...

    if __name__ == "__main__":
        ops.main(SomeCharm)

Args:
    charm_class: the charm class to instantiate and receive the event.
    use_juju_for_storage: whether to use controller-side storage.
        The default is ``False`` for most charms.
        Podspec charms that haven't previously used local storage and that
        are running on a new enough Juju default to controller-side storage,
        and local storage otherwise.
"""
