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

"""The Charmed Operator Framework.

The Charmed Operator Framework allows the development of operators in a simple
and straightforward way, using standard Python structures to allow for clean,
maintainable, and reusable code.

A Kubernetes operator is a container that drives lifecycle management,
configuration, integration and daily actions for an application. Operators
simplify software management and operations. They capture reusable app domain
knowledge from experts in a software component that can be shared.

The Charmed Operator Framework extends the "operator pattern" to enable Charmed
Operators, packaged as and often referred to as "charms". Charms are not just
for Kubernetes but also operators for traditional Linux application management.
Operators use an Operator Lifecycle Manager (OLM), like Juju, to coordinate
their work in a cluster. The system uses Golang for concurrent event processing
under the hood, but enables the operators to be written in Python.

Operators should do one thing and do it well. Each operator drives a single
application or service and can be composed with other operators to deliver a
complex application or service. An operator handles instantiation, scaling,
configuration, optimisation, networking, service mesh, observability,
and day-2 operations specific to that application.

Full developer documentation is available at https://juju.is/docs/sdk.
"""

# The isort command wants to rearrange the nicely-formatted imports below;
# just skip it for this file.
# isort:skip_file

# Similarly, Pyright complains that all of these things are unused imports,
# so disable it:
# pyright: reportUnusedImport=false

# Import pebble explicitly. It's the one module we don't import names from below.
from . import pebble  # type: ignore # noqa: F401

# Also import charm explicitly. This is not strictly necessary as the
# "from .charm" import automatically does that, but be explicit since this
# import was here previously
from . import charm  # type: ignore # noqa: F401

# Import the main module, which we've overriden in main.py to be callable.
# This allows "import ops; ops.main(Charm)" to work as expected.
from . import main  # type: ignore # noqa: F401

# Explicitly import names from sub-modules so users can just "import ops" and
# then use them as "ops.X".
from .charm import (  # noqa: F401
    ActionEvent,
    ActionMeta,
    CharmBase,
    CharmEvents,
    CharmMeta,
    CollectMetricsEvent,
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
