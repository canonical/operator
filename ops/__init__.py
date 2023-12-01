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

"""The ops library: a Python framework for writing Juju charms.

The ops library is a Python framework (`available on PyPI`_) for developing
and testing Juju charms in a consistent way, using standard Python constructs
to allow for clean, maintainable, and reusable code.

A charm is an operator -- business logic encapsulated in a reusable software
package that automates every aspect of an application's life.

Charms written with ops support Kubernetes using Juju's "sidecar charm"
pattern, as well as charms that deploy to Linux-based machines and containers.

Charms should do one thing and do it well. Each charm drives a single
application and can be integrated with other charms to deliver a complex
system. A charm handles creating the application in addition to scaling,
configuration, optimisation, networking, service mesh, observability, and other
day-2 operations specific to the application.

The ops library is part of the Charm SDK (the other part being Charmcraft).
Full developer documentation for the Charm SDK is available at
https://juju.is/docs/sdk.

To learn more about Juju, visit https://juju.is/docs/olm.

.. _available on PyPI: https://pypi.org/project/ops/
"""

# The "from .X import Y" imports below don't explicitly tell Pyright (or MyPy)
# that those symbols are part of the public API, so we have to add __all__.
__all__ = [
    '__version__',
    'main',
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
    'ContainerMeta',
    'ContainerStorageMeta',
    'HookEvent',
    'InstallEvent',
    'LeaderElectedEvent',
    'LeaderSettingsChangedEvent',
    'PayloadMeta',
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

    # From jujuversion.py
    'JujuVersion',

    # From model.py
    'ActiveStatus',
    'Application',
    'Binding',
    'BindingMapping',
    'BlockedStatus',
    'CheckInfoMapping',
    'ConfigData',
    'Container',
    'ContainerMapping',
    'ErrorStatus',
    'InvalidStatusError',
    'LazyMapping',
    'MaintenanceStatus',
    'Model',
    'ModelError',
    'MultiPushPullError',
    'Network',
    'NetworkInterface',
    'OpenedPort',
    'Port',
    'Pod',
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
from . import pebble  # type: ignore # noqa: F401

# Also import charm explicitly. This is not strictly necessary as the
# "from .charm" import automatically does that, but be explicit since this
# import was here previously
from . import charm  # type: ignore # noqa: F401

# Import the main module, which we've overriden in main.py to be callable.
# This allows "import ops; ops.main(Charm)" to work as expected.
from . import main  # type: ignore # noqa: F401

# Explicitly import names from submodules so users can just "import ops" and
# then use them as "ops.X".
from .charm import (  # noqa: F401
    ActionEvent,
    ActionMeta,
    CharmBase,
    CharmEvents,
    CharmMeta,
    CollectMetricsEvent,
    CollectStatusEvent,
    ConfigChangedEvent,
    ContainerMeta,
    ContainerStorageMeta,
    HookEvent,
    InstallEvent,
    LeaderElectedEvent,
    LeaderSettingsChangedEvent,
    PayloadMeta,
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

from .framework import (  # noqa: F401
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

from .jujuversion import JujuVersion  # noqa: F401

from .model import (  # noqa: F401 E402
    ActiveStatus,
    Application,
    Binding,
    BindingMapping,
    BlockedStatus,
    CheckInfoMapping,
    ConfigData,
    Container,
    ContainerMapping,
    ErrorStatus,
    InvalidStatusError,
    LazyMapping,
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

from .version import version as __version__  # noqa: F401 E402
