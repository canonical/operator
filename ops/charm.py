# Copyright 2019-2020 Canonical Ltd.
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

import enum
import os
import pathlib
import typing

import yaml

from ops.framework import Object, EventSource, EventBase, Framework, ObjectEvents
from ops import model


class HookEvent(EventBase):
    """A base class for events that trigger because of a Juju hook firing."""


class ActionEvent(EventBase):
    """A base class for events that trigger when a user asks for an Action to be run.

    To read the parameters for the action, see the instance variable `params`.
    To respond with the result of the action, call `set_results`. To add progress
    messages that are visible as the action is progressing use `log`.

    :ivar params: The parameters passed to the action (read by action-get)
    """

    def defer(self):
        """Action events are not deferable like other events.

        This is because an action runs synchronously and the user is waiting for the result.
        """
        raise RuntimeError('cannot defer action events')

    def restore(self, snapshot: dict) -> None:
        """Used by the operator framework to record the action.

        Not meant to be called directly by Charm code.
        """
        env_action_name = os.environ.get('JUJU_ACTION_NAME')
        event_action_name = self.handle.kind[:-len('_action')].replace('_', '-')
        if event_action_name != env_action_name:
            # This could only happen if the dev manually emits the action, or from a bug.
            raise RuntimeError('action event kind does not match current action')
        # Params are loaded at restore rather than __init__ because
        # the model is not available in __init__.
        self.params = self.framework.model._backend.action_get()

    def set_results(self, results: typing.Mapping) -> None:
        """Report the result of the action.

        Args:
            results: The result of the action as a Dict
        """
        self.framework.model._backend.action_set(results)

    def log(self, message: str) -> None:
        """Send a message that a user will see while the action is running.

        Args:
            message: The message for the user.
        """
        self.framework.model._backend.action_log(message)

    def fail(self, message: str = '') -> None:
        """Report that this action has failed.

        Args:
            message: Optional message to record why it has failed.
        """
        self.framework.model._backend.action_fail(message)


class InstallEvent(HookEvent):
    """Represents the `install` hook from Juju."""


class StartEvent(HookEvent):
    """Represents the `start` hook from Juju."""


class StopEvent(HookEvent):
    """Represents the `stop` hook from Juju."""


class RemoveEvent(HookEvent):
    """Represents the `remove` hook from Juju. """


class ConfigChangedEvent(HookEvent):
    """Represents the `config-changed` hook from Juju."""


class UpdateStatusEvent(HookEvent):
    """Represents the `update-status` hook from Juju."""


class UpgradeCharmEvent(HookEvent):
    """Represents the `upgrade-charm` hook from Juju.

    This will be triggered when a user has run `juju upgrade-charm`. It is run after Juju
    has unpacked the upgraded charm code, and so this event will be handled with new code.
    """


class PreSeriesUpgradeEvent(HookEvent):
    """Represents the `pre-series-upgrade` hook from Juju.

    This happens when a user has run `juju upgrade-series MACHINE prepare` and
    will fire for each unit that is running on the machine, telling them that
    the user is preparing to upgrade the Machine's series (eg trusty->bionic).
    The charm should take actions to prepare for the upgrade (a database charm
    would want to write out a version-independent dump of the database, so that
    when a new version of the database is available in a new series, it can be
    used.)
    Once all units on a machine have run `pre-series-upgrade`, the user will
    initiate the steps to actually upgrade the machine (eg `do-release-upgrade`).
    When the upgrade has been completed, the :class:`PostSeriesUpgradeEvent` will fire.
    """


class PostSeriesUpgradeEvent(HookEvent):
    """Represents the `post-series-upgrade` hook from Juju.

    This is run after the user has done a distribution upgrade (or rolled back
    and kept the same series). It is called in response to
    `juju upgrade-series MACHINE complete`. Charms are expected to do whatever
    steps are necessary to reconfigure their applications for the new series.
    """


class LeaderElectedEvent(HookEvent):
    """Represents the `leader-elected` hook from Juju.

    Juju will trigger this when a new lead unit is chosen for a given application.
    This represents the leader of the charm information (not necessarily the primary
    of a running application). The main utility is that charm authors can know
    that only one unit will be a leader at any given time, so they can do
    configuration, etc, that would otherwise require coordination between units.
    (eg, selecting a password for a new relation)
    """


class LeaderSettingsChangedEvent(HookEvent):
    """Represents the `leader-settings-changed` hook from Juju.

    Deprecated. This represents when a lead unit would call `leader-set` to inform
    the other units of an application that they have new information to handle.
    This has been deprecated in favor of using a Peer relation, and having the
    leader set a value in the Application data bag for that peer relation.
    (see :class:`RelationChangedEvent`).
    """


class CollectMetricsEvent(HookEvent):
    """Represents the `collect-metrics` hook from Juju.

    Note that events firing during a CollectMetricsEvent are currently
    sandboxed in how they can interact with Juju. To report metrics
    use :meth:`.add_metrics`.
    """

    def add_metrics(self, metrics: typing.Mapping, labels: typing.Mapping = None) -> None:
        """Record metrics that have been gathered by the charm for this unit.

        Args:
            metrics: A collection of {key: float} pairs that contains the
              metrics that have been gathered
            labels: {key:value} strings that can be applied to the
                metrics that are being gathered
        """
        self.framework.model._backend.add_metrics(metrics, labels)


class RelationEvent(HookEvent):
    """A base class representing the various relation lifecycle events.

    Charmers should not be creating RelationEvents directly. The events will be
    generated by the framework from Juju related events. Users can observe them
    from the various `CharmBase.on[relation_name].relation_*` events.

    Attributes:
        relation: The Relation involved in this event
        app: The remote application that has triggered this event
        unit: The remote unit that has triggered this event. This may be None
              if the relation event was triggered as an Application level event
    """

    def __init__(self, handle, relation, app=None, unit=None):
        super().__init__(handle)

        if unit is not None and unit.app != app:
            raise RuntimeError(
                'cannot create RelationEvent with application {} and unit {}'.format(app, unit))

        self.relation = relation
        self.app = app
        self.unit = unit

    def snapshot(self) -> dict:
        """Used by the framework to serialize the event to disk.

        Not meant to be called by Charm code.
        """
        snapshot = {
            'relation_name': self.relation.name,
            'relation_id': self.relation.id,
        }
        if self.app:
            snapshot['app_name'] = self.app.name
        if self.unit:
            snapshot['unit_name'] = self.unit.name
        return snapshot

    def restore(self, snapshot: dict) -> None:
        """Used by the framework to deserialize the event from disk.

        Not meant to be called by Charm code.
        """
        self.relation = self.framework.model.get_relation(
            snapshot['relation_name'], snapshot['relation_id'])

        app_name = snapshot.get('app_name')
        if app_name:
            self.app = self.framework.model.get_app(app_name)
        else:
            self.app = None

        unit_name = snapshot.get('unit_name')
        if unit_name:
            self.unit = self.framework.model.get_unit(unit_name)
        else:
            self.unit = None


class RelationCreatedEvent(RelationEvent):
    """Represents the `relation-created` hook from Juju.

    This is triggered when a new relation to another app is added in Juju. This
    can occur before units for those applications have started. All existing
    relations should be established before start.
    """


class RelationJoinedEvent(RelationEvent):
    """Represents the `relation-joined` hook from Juju.

    This is triggered whenever a new unit of a related application joins the relation.
    (eg, a unit was added to an existing related app, or a new relation was established
    with an application that already had units.)
    """


class RelationChangedEvent(RelationEvent):
    """Represents the `relation-changed` hook from Juju.

    This is triggered whenever there is a change to the data bucket for a related
    application or unit. Look at `event.relation.data[event.unit/app]` to see the
    new information.
    """


class RelationDepartedEvent(RelationEvent):
    """Represents the `relation-departed` hook from Juju.

    This is the inverse of the RelationJoinedEvent, representing when a unit
    is leaving the relation (the unit is being removed, the app is being removed,
    the relation is being removed). It is fired once for each unit that is
    going away.
    """


class RelationBrokenEvent(RelationEvent):
    """Represents the `relation-broken` hook from Juju.

    If a relation is being removed (`juju remove-relation` or `juju remove-application`),
    once all the units have been removed, RelationBrokenEvent will fire to signal
    that the relationship has been fully terminated.
    """


class StorageEvent(HookEvent):
    """Base class representing Storage related events."""


class StorageAttachedEvent(StorageEvent):
    """Represents the `storage-attached` hook from Juju.

    Called when new storage is available for the charm to use.
    """


class StorageDetachingEvent(StorageEvent):
    """Represents the `storage-detaching` hook from Juju.

    Called when storage a charm has been using is going away.
    """


class CharmEvents(ObjectEvents):
    """The events that are generated by Juju in response to the lifecycle of an application."""

    install = EventSource(InstallEvent)
    start = EventSource(StartEvent)
    stop = EventSource(StopEvent)
    remove = EventSource(RemoveEvent)
    update_status = EventSource(UpdateStatusEvent)
    config_changed = EventSource(ConfigChangedEvent)
    upgrade_charm = EventSource(UpgradeCharmEvent)
    pre_series_upgrade = EventSource(PreSeriesUpgradeEvent)
    post_series_upgrade = EventSource(PostSeriesUpgradeEvent)
    leader_elected = EventSource(LeaderElectedEvent)
    leader_settings_changed = EventSource(LeaderSettingsChangedEvent)
    collect_metrics = EventSource(CollectMetricsEvent)


class CharmBase(Object):
    """Base class that represents the Charm overall.

    Usually this initialization is done by ops.main.main() rather than Charm authors
    directly instantiating a Charm.

    Args:
        framework: The framework responsible for managing the Model and events for this
            Charm.
        key: Arbitrary key to distinguish this instance of CharmBase from another.
            Generally is None when initialized by the framework. For charms instantiated by
            main.main(), this is currenly None.
    """

    on = CharmEvents()

    def __init__(self, framework: Framework, key: typing.Optional[str]):
        """Initialize the Charm with its framework and application name.

        """
        super().__init__(framework, key)

        for relation_name in self.framework.meta.relations:
            relation_name = relation_name.replace('-', '_')
            self.on.define_event(relation_name + '_relation_created', RelationCreatedEvent)
            self.on.define_event(relation_name + '_relation_joined', RelationJoinedEvent)
            self.on.define_event(relation_name + '_relation_changed', RelationChangedEvent)
            self.on.define_event(relation_name + '_relation_departed', RelationDepartedEvent)
            self.on.define_event(relation_name + '_relation_broken', RelationBrokenEvent)

        for storage_name in self.framework.meta.storages:
            storage_name = storage_name.replace('-', '_')
            self.on.define_event(storage_name + '_storage_attached', StorageAttachedEvent)
            self.on.define_event(storage_name + '_storage_detaching', StorageDetachingEvent)

        for action_name in self.framework.meta.actions:
            action_name = action_name.replace('-', '_')
            self.on.define_event(action_name + '_action', ActionEvent)

    @property
    def app(self) -> model.Application:
        """Application that this unit is part of."""
        return self.framework.model.app

    @property
    def unit(self) -> model.Unit:
        """Unit that this execution is responsible for."""
        return self.framework.model.unit

    @property
    def meta(self) -> 'CharmMeta':
        """CharmMeta of this charm.
        """
        return self.framework.meta

    @property
    def charm_dir(self) -> pathlib.Path:
        """Root directory of the Charm as it is running.
        """
        return self.framework.charm_dir


class CharmMeta:
    """Object containing the metadata for the charm.

    This is read from metadata.yaml and/or actions.yaml. Generally charms will
    define this information, rather than reading it at runtime. This class is
    mostly for the framework to understand what the charm has defined.

    The maintainers, tags, terms, series, and extra_bindings attributes are all
    lists of strings.  The requires, provides, peers, relations, storage,
    resources, and payloads attributes are all mappings of names to instances
    of the respective RelationMeta, StorageMeta, ResourceMeta, or PayloadMeta.

    The relations attribute is a convenience accessor which includes all of the
    requires, provides, and peers RelationMeta items.  If needed, the role of
    the relation definition can be obtained from its role attribute.

    Attributes:
        name: The name of this charm
        summary: Short description of what this charm does
        description: Long description for this charm
        maintainers: A list of strings of the email addresses of the maintainers
                     of this charm.
        tags: Charm store tag metadata for categories associated with this charm.
        terms: Charm store terms that should be agreed to before this charm can
               be deployed. (Used for things like licensing issues.)
        series: The list of supported OS series that this charm can support.
                The first entry in the list is the default series that will be
                used by deploy if no other series is requested by the user.
        subordinate: True/False whether this charm is intended to be used as a
                     subordinate charm.
        min_juju_version: If supplied, indicates this charm needs features that
                          are not available in older versions of Juju.
        requires: A dict of {name: :class:`RelationMeta` } for each 'requires' relation.
        provides: A dict of {name: :class:`RelationMeta` } for each 'provides' relation.
        peers: A dict of {name: :class:`RelationMeta` } for each 'peer' relation.
        relations: A dict containing all :class:`RelationMeta` attributes (merged from other
                   sections)
        storages: A dict of {name: :class:`StorageMeta`} for each defined storage.
        resources: A dict of {name: :class:`ResourceMeta`} for each defined resource.
        payloads: A dict of {name: :class:`PayloadMeta`} for each defined payload.
        extra_bindings: A dict of additional named bindings that a charm can use
                        for network configuration.
        actions: A dict of {name: :class:`ActionMeta`} for actions that the charm has defined.
    Args:
        raw: a mapping containing the contents of metadata.yaml
        actions_raw: a mapping containing the contents of actions.yaml
    """

    def __init__(self, raw: dict = {}, actions_raw: dict = {}):
        self.name = raw.get('name', '')
        self.summary = raw.get('summary', '')
        self.description = raw.get('description', '')
        self.maintainers = []
        if 'maintainer' in raw:
            self.maintainers.append(raw['maintainer'])
        if 'maintainers' in raw:
            self.maintainers.extend(raw['maintainers'])
        self.tags = raw.get('tags', [])
        self.terms = raw.get('terms', [])
        self.series = raw.get('series', [])
        self.subordinate = raw.get('subordinate', False)
        self.min_juju_version = raw.get('min-juju-version')
        self.requires = {name: RelationMeta(RelationRole.requires, name, rel)
                         for name, rel in raw.get('requires', {}).items()}
        self.provides = {name: RelationMeta(RelationRole.provides, name, rel)
                         for name, rel in raw.get('provides', {}).items()}
        self.peers = {name: RelationMeta(RelationRole.peer, name, rel)
                      for name, rel in raw.get('peers', {}).items()}
        self.relations = {}
        self.relations.update(self.requires)
        self.relations.update(self.provides)
        self.relations.update(self.peers)
        self.storages = {name: StorageMeta(name, storage)
                         for name, storage in raw.get('storage', {}).items()}
        self.resources = {name: ResourceMeta(name, res)
                          for name, res in raw.get('resources', {}).items()}
        self.payloads = {name: PayloadMeta(name, payload)
                         for name, payload in raw.get('payloads', {}).items()}
        self.extra_bindings = raw.get('extra-bindings', {})
        self.actions = {name: ActionMeta(name, action) for name, action in actions_raw.items()}

    @classmethod
    def from_yaml(
            cls, metadata: typing.Union[str, typing.TextIO],
            actions: typing.Optional[typing.Union[str, typing.TextIO]] = None):
        """Instantiate a CharmMeta from a YAML description of metadata.yaml.

        Args:
            metadata: A YAML description of charm metadata (name, relations, etc.)
                This can be a simple string, or a file-like object. (passed to `yaml.safe_load`).
            actions: YAML description of Actions for this charm (eg actions.yaml)
        """
        meta = yaml.safe_load(metadata)
        raw_actions = {}
        if actions is not None:
            raw_actions = yaml.safe_load(actions)
        return cls(meta, raw_actions)


class RelationRole(enum.Enum):
    peer = 'peer'
    requires = 'requires'
    provides = 'provides'

    def is_peer(self) -> bool:
        """Return whether the current role is peer.

        A convenience to avoid having to import charm.
        """
        return self is RelationRole.peer


class RelationMeta:
    """Object containing metadata about a relation definition.

    Should not be constructed directly by Charm code. Is gotten from one of
    :attr:`CharmMeta.peers`, :attr:`CharmMeta.requires`, :attr:`CharmMeta.provides`,
    or :attr:`CharmMeta.relations`.

    Attributes:
        role: This is one of peer/requires/provides
        relation_name: Name of this relation from metadata.yaml
        interface_name: Optional definition of the interface protocol.
        scope: "global" or "container" scope based on how the relation should be used.
    """

    def __init__(self, role: RelationRole, relation_name: str, raw: dict):
        if not isinstance(role, RelationRole):
            raise TypeError("role should be a Role, not {!r}".format(role))
        self.role = role
        self.relation_name = relation_name
        self.interface_name = raw['interface']
        self.scope = raw.get('scope')


class StorageMeta:
    """Object containing metadata about a storage definition."""

    def __init__(self, name, raw):
        self.storage_name = name
        self.type = raw['type']
        self.description = raw.get('description', '')
        self.shared = raw.get('shared', False)
        self.read_only = raw.get('read-only', False)
        self.minimum_size = raw.get('minimum-size')
        self.location = raw.get('location')
        self.multiple_range = None
        if 'multiple' in raw:
            range = raw['multiple']['range']
            if '-' not in range:
                self.multiple_range = (int(range), int(range))
            else:
                range = range.split('-')
                self.multiple_range = (int(range[0]), int(range[1]) if range[1] else None)


class ResourceMeta:
    """Object containing metadata about a resource definition."""

    def __init__(self, name, raw):
        self.resource_name = name
        self.type = raw['type']
        self.filename = raw.get('filename', None)
        self.description = raw.get('description', '')


class PayloadMeta:
    """Object containing metadata about a payload definition."""

    def __init__(self, name, raw):
        self.payload_name = name
        self.type = raw['type']


class ActionMeta:
    """Object containing metadata about an action's definition."""

    def __init__(self, name, raw=None):
        raw = raw or {}
        self.name = name
        self.title = raw.get('title', '')
        self.description = raw.get('description', '')
        self.parameters = raw.get('params', {})  # {<parameter name>: <JSON Schema definition>}
        self.required = raw.get('required', [])  # [<parameter name>, ...]
