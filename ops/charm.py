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


def _loadYaml(source):
    if yaml.__with_libyaml__:
        return yaml.load(source, Loader=yaml.CSafeLoader)
    return yaml.load(source, Loader=yaml.SafeLoader)


class HookEvent(EventBase):
    """A base class for events raised by Juju to progress a charm's lifecycle.

    Hooks are callback functions, defined in a Charm, that are invoked
    in response to events raised by Juju. These hooks are the means by
    which a Charm governs the life cycle of its application.

    This class is used to create a type hierarchy of events related to
    hooks, and forms the base of this hierarchy.

    HookEvent subtypes are grouped into the following categories
    - Core lifecycle hooks
    - Relation hooks
    - Storage Charm Hooks
    - Metric Hooks

    """


class ActionEvent(EventBase):
    """A base class for events raised by Juju when a user invokes an Juju Action.

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
    """Represents the `install` hook from Juju.

    The InstallEvent is run at the beginning of a charm lifecycle. The
    hook should be used to perform one-time setup operations, such as
    installing prerequisite software that will not change with
    configuration changes.
    """


class StartEvent(HookEvent):
    """Represents the `start` hook from Juju.

    The StartEvent hook runs immediately after the first ConfigChanged
    hook. It should be used to ensure the charm’s software is
    running. Note that the charm’s software should be configured so as
    to persist through reboots without further intervention on juju’s
    part.
    """


class StopEvent(HookEvent):
    """Represents the `stop` hook from Juju.

    The StopEvent hook runs immediately before the end of the unit’s
    destruction sequence. It should be used to ensure that the charm’s
    software is not running, and will not start again on reboot.
    This hook is called when an application removal is requested by
    the client.
    """


class RemoveEvent(HookEvent):
    """Represents the `remove` hook from Juju.
    """


class ConfigChangedEvent(HookEvent):
    """Represents the `config-changed` hook from Juju.

    The ConfigChanged hook runs in several different situations.

    - immediately after `install`
    - immediately after `upgrade-charm`
    - at least once when the unit agent is restarted (but, if the unit
      is in an error state, it won’t be run until after the error
      state is cleared).
    - after changing charm configuration using the GUI or command line
      interface

    It cannot assume that the software has already been started; it
    should not start stopped software, but should (if appropriate)
    restart running software to take configuration changes into
    account.
    """


class UpdateStatusEvent(HookEvent):
    """Represents the `update-status` hook from Juju.

    The UpdateStatus hook provides constant feedback to the user about
    the status of the application the charm is modeling. The charm is
    run by Juju at regular intervals, and gives authors an opportunity
    to run code that gets the “health” of the application.
    """


class UpgradeCharmEvent(HookEvent):
    """Represents the `upgrade-charm` hook from Juju.

    This will be triggered when a user has run `juju upgrade-charm`.
    It is run after Juju has unpacked the upgraded charm code, and so
    this event will be handled with new code.

    The UpgradeCharmEvent hook runs immediately after any upgrade
    operation that does not itself interrupt an existing error
    state. It should be used to reconcile local state written by some
    other version of the charm into whatever form it needs to take to
    be manipulated by the current version.
    """


class PreSeriesUpgradeEvent(HookEvent):
    """Represents the `pre-series-upgrade` hook from Juju.

    This happens when a user has run `juju upgrade-series MACHINE prepare` and
    will fire for each unit that is running on the machine, telling them that
    the user is preparing to upgrade the Machine's series.

    Once all units on a machine have run `pre-series-upgrade`, the
    user will initiate the steps to actually upgrade the machine.
    When the upgrade has been completed, the
    :class:`PostSeriesUpgradeEvent` will fire.
    """


class PostSeriesUpgradeEvent(HookEvent):
    """Represents the `post-series-upgrade` hook from Juju.

    This is run after the user has done a distribution upgrade (or
    rolled back and kept the same series). It is called in response to
    `juju upgrade-series MACHINE complete`. Charms are expected to do
    whatever steps are necessary to reconfigure their applications for
    the new series.
    """


class LeaderElectedEvent(HookEvent):
    """Represents the `leader-elected` hook from Juju.

    Juju will trigger this when a new leader unit is chosen for a
    given application.

    The LeaderElectedHook is run at least once to signify that Juju
    decided this unit is the leader. Authors can use this hook to take
    action if the protocols for leadership, consensus, raft, or quorum
    require one unit to assert leadership. If the election process is
    done internally to the application, other code should be used to
    signal the leader to Juju.
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

    Juju executes the collect-metrics hook every five minutes for the
    lifetime of the unit. Use the `add_metric` method of this class to
    send measurements to Juju.

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

    Relation lifecycle events are generated when application units
    participate in relations.  Units can only participate in relations
    after they’re been "started", and before they’ve been
    "stopped". Within that time window, the unit may participate in
    several different relations at a time, including multiple
    relations with the same name.

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

    This is triggered whenever a new unit of a related application
    joins the relation.  The RelationJoinedEvent is run only when that
    remote unit is first observed by the unit. It should be used to
    `relation-set` any local unit settings that can be determined
    using no more than the name of the joining unit and the remote
    private-address setting, which is always available when the
    relation is created and is by convention not deleted.
    """


class RelationChangedEvent(RelationEvent):
    """Represents the `relation-changed` hook from Juju.

    This is triggered whenever there is a change to the data bucket
    for a related application or unit. Look at
    `event.relation.data[event.unit/app]` to see the new information.

    RelationChangedEvent is always run once, after
    RelationJoinedEvent, and will subsequently be run whenever that
    remote unit changes its settings for the relation. It should be
    the only hook that relies upon remote relation settings from
    `relation-get`, and it should not error if the settings are
    incomplete, since it can be guaranteed that when the remote unit
    changes its settings, the hook will be run again.

    The settings that be querried, or set, are determined by the
    relation’s interface.
    """


class RelationDepartedEvent(RelationEvent):
    """Represents the `relation-departed` hook from Juju.

    This is the inverse of the RelationJoinedEvent, representing when
    a unit is leaving the relation (the unit is being removed, the app
    is being removed, the relation is being removed). It is fired once
    for each unit that is going away.

    When the remote unit is known to be leaving the relation, this
    will result in the RelationChangedEvent hook to run at least once,
    after which the RelationDepartedEvent hook will run. The
    RelationDepartedEvent hook is run once only. Once the
    RelationDepartedEvent hook has run no further RelationChangedEvent
    hooks will be run.

    The RelationDepartedEvent hook should be used to remove all
    references to the departing remote unit, because there’s no
    guarantee that it’s still part of the system; it’s perfectly
    probable (although not guaranteed) that the system running that
    unit has already shut down.

    Once all necessary RelationDepartedEvent hooks have been run for
    such a relation, the unit agent will run the final relation hook,
    the RelationBrokenEvent hook.
    """


class RelationBrokenEvent(RelationEvent):
    """Represents the `relation-broken` hook from Juju.

    If a relation is being removed (`juju remove-relation` or `juju
    remove-application`), once all the units have been removed,
    RelationBrokenEvent will fire to signal that the relationship has
    been fully terminated.

    The RelationBrokenEvent hook indicates that the current relation
    is no longer valid, and that the charm’s software must be
    configured as though the relation had never existed. It will only
    be called after every necessary RelationDepartedEvent hook has
    been run. If the RelationBrokenEvent hook is being executed, it is
    gauranteed that no remote units are currently known locally.
    """


class StorageEvent(HookEvent):
    """Base class representing Storage related events.

    Juju can provide a variety of storage to charms. The charms can
    define several different types of storage that are allocated from
    Juju. Changes in state of storage trigger sub-types of
    StorageEvent hooks.
    """


class StorageAttachedEvent(StorageEvent):
    """Represents the `storage-attached` hook from Juju.

    Called when new storage is available for the charm to use.

    StorageAttachedEvent hook allows the charm to run code when
    storage has been added. The StorageAttachedEvent hooks will be run
    before the install hook, so that the installation routine may use
    the storage. The name prefix of this hook will depend on the
    storage key defined in the `metadata.yaml` file.
    """


class StorageDetachingEvent(StorageEvent):
    """Represents the `storage-detaching` hook from Juju.

    Called when storage a charm has been using, is going away.

    StorageDetachingEvent hook allows the charm to run code before
    storage is removed. The StorageDetachingEvent hooks will be run
    before storage is detached, and always before the stop hook is
    run, to allow the charm to gracefully release resources before
    they are removed and before the unit terminates. The name prefix
    of the hook will depend on the storage key defined in the
    `metadata.yaml` file.
    """


class CharmEvents(ObjectEvents):
    """Events generated by Juju pertaining to application lifecycle.

    This class is used to create an event descriptor (`self.on`)
    attribute for a Charm class that inherits from CharmBase. The
    event descriptor may be used to setup event handlers for
    corresponding events.

    By default the following events will be provided through
    CharmBase:

    ```
    self.on.install
    self.on.start
    self.on.remove
    self.on.update_status
    self.on.config_changed
    self.on.upgrade_charm
    self.on.pre_series_upgrade
    self.on.post_series_upgrade
    self.on.leader_elected
    self.on.collect_metrics
    ```

    In addition to these named relation and storage events may also be
    defined, depending on the Charm's metadata (`metadata.yaml`).
    These named events are created by CharmBase using Charm Metadata.
    The named events may be accessed as
    ```
    self.on[<name>].<relation_or_storage_event>
    ```
    """

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

    CharmBase is used to create a charms. This is done by inheriting
    from CharmBase and customising the sub class as required. So to
    create your own charm, say "MyCharm" define a charm class and
    setup the required event handlers (hooks) in its constructor as
    shown below

    ```
    import logging

    from ops.charm import CharmBase
    from ops.main import main

    logger = logging.getLogger(__name__)

    def MyCharm(CharmBase):
        def __init__(self, *args):
            logger.debug('Initializing Charm')

            super().__init__(*args)

            self.framework.observe(self.on.config_changed, self._on_config_changed)
            self.framework.observe(self.on.stop, self._on_stop)
            ....

    if __name__ == "__main__":
        main(MyCharm)
    ```

    As shown, in the example above, a charm class is instantiated by
    ops.main.main() rather than Charm authors directly instantiating a
    Charm.

    Args:
        framework: The framework responsible for managing the Model and events for this
            Charm.
        key: Ignored; will remove after deprecation period of the signature change.

    """

    on = CharmEvents()

    def __init__(self, framework: Framework, key: typing.Optional = None):
        super().__init__(framework, None)

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
        meta = _loadYaml(metadata)
        raw_actions = {}
        if actions is not None:
            raw_actions = _loadYaml(actions)
        return cls(meta, raw_actions)


class RelationRole(enum.Enum):
    """An annotation for a Charm's Role in a Relations

    For each relation a Charms role may be
    - A Peer
    - A consumer in the relation ('requires')
    - A producer in the relation ('provides')
    """
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
    """Object containing metadata about a storage definition.

    Attributes:
    storage_name: Name of storage
    type: Storage type
    description: A text description of the storage
    read_only: Is the storage read only
    minimum_size: Minimum size of storage
    location: Mount point of storage
    multiple_range: Range of numeric qualifiers when multiple storage units are used
    """

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
    """Object containing metadata about a resource definition.

    Attributes:
    resource_name: Name of resource
    filename: Name of file
    description: A text description of resource
    """

    def __init__(self, name, raw):
        self.resource_name = name
        self.type = raw['type']
        self.filename = raw.get('filename', None)
        self.description = raw.get('description', '')


class PayloadMeta:
    """Object containing metadata about a payload definition.

    Attributes:
    payload_name: Name of payload
    type: Payload Type
    """

    def __init__(self, name, raw):
        self.payload_name = name
        self.type = raw['type']


class ActionMeta:
    """Object containing metadata about an action's definition.

    Attributes:
    """

    def __init__(self, name, raw=None):
        raw = raw or {}
        self.name = name
        self.title = raw.get('title', '')
        self.description = raw.get('description', '')
        self.parameters = raw.get('params', {})  # {<parameter name>: <JSON Schema definition>}
        self.required = raw.get('required', [])  # [<parameter name>, ...]
