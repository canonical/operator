import sys
from pathlib import Path

import yaml

from juju.framework import Object, Event, EventBase, EventsBase


class HookEvent(EventBase):
    pass


class InstallEvent(HookEvent):
    pass

class StartEvent(HookEvent):
    pass

class StopEvent(HookEvent):
    pass

class ConfigChangedEvent(HookEvent):
    pass

class UpdateStatusEvent(HookEvent):
    pass

class UpgradeCharmEvent(HookEvent):
    pass

class PreSeriesUpgradeEvent(HookEvent):
    pass

class PostSeriesUpgradeEvent(HookEvent):
    pass

class LeaderElectedEvent(HookEvent):
    pass

class LeaderSettingsChangedEvent(HookEvent):
    pass


class RelationEvent(HookEvent):
    pass


class RelationJoinedEvent(RelationEvent):
    pass

class RelationChangedEvent(RelationEvent):
    pass

class RelationDepartedEvent(RelationEvent):
    pass

class RelationBrokenEvent(RelationEvent):
    pass


class StorageEvent(HookEvent):
    pass


class StorageAttachedEvent(StorageEvent):
    pass

class StorageDetachingEvent(StorageEvent):
    pass


class CharmEvents(EventsBase):

    install = Event(InstallEvent)
    start = Event(StartEvent)
    stop = Event(StopEvent)
    update_status = Event(UpdateStatusEvent)
    config_changed = Event(ConfigChangedEvent)
    upgrade_charm = Event(UpgradeCharmEvent)
    pre_series_upgrade = Event(PreSeriesUpgradeEvent)
    post_series_upgrade = Event(PostSeriesUpgradeEvent)
    leader_elected = Event(LeaderElectedEvent)
    leader_settings_changed = Event(LeaderSettingsChangedEvent)


class CharmBase(Object):

    on = CharmEvents()

    def __init__(self, framework, key):
        super().__init__(framework, key)

        for relation_name in self.metadata.relations:
            relation_name = relation_name.replace('-', '_')
            self.on.define_event(f'{relation_name}_relation_joined', RelationJoinedEvent)
            self.on.define_event(f'{relation_name}_relation_changed', RelationChangedEvent)
            self.on.define_event(f'{relation_name}_relation_departed', RelationDepartedEvent)
            self.on.define_event(f'{relation_name}_relation_broken', RelationBrokenEvent)

        for storage_name in self.metadata.storage:
            storage_name = storage_name.replace('-', '_')
            self.on.define_event(f'{storage_name}_storage_attached', StorageAttachedEvent)
            self.on.define_event(f'{storage_name}_storage_detaching', StorageDetachingEvent)

    @property
    def charm_env(self):
        return self.framework.charm_env

    @property
    def metadata(self):
        return self.charm_env.metadata

    @property
    def charm_dir(self):
        return self.charm_env.charm_dir


class CharmEnv:
    def __init__(self, env=None, **overrides):
        """Object containing info about the operating environment of the charm.

        Information will be extracted from the given environment variables, but can also be overridden
        via keyword arguments.

        See https://jaas.ai/docs/charm-writing/hook-env#heading--environment-variables for more info.
        """
        env = env or {}
        self.charm_dir = overrides.get('charm_dir', env.get('JUJU_CHARM_DIR'))
        if self.charm_dir is not None:
            self.charm_dir = Path(self.charm_dir)
        self.metadata = overrides.get('metadata')
        if not self.metadata:
            if self.charm_dir:
                with open(self.charm_dir / 'metadata.yaml') as f:
                    self.metadata = CharmMeta(yaml.safe_load(f))
            else:
                self.metadata = CharmMeta()
        # Note: JUJU_HOOK_NAME is not reliably available, only being set during debug-hooks.
        self.hook_name = overrides.get('hook_name', Path(sys.argv[0]).name)
        self.unit_name = overrides.get('unit_name', env.get('JUJU_UNIT_NAME'))
        self.app_name = self.unit_name.split('/')[0] if self.unit_name else ''
        self.relation_name = overrides.get('relation_name', env.get('JUJU_RELATION'))
        self.relation_id = overrides.get('relation_id', env.get('JUJU_RELATION_ID'))
        self.remote_unit_name = overrides.get('remote_unit_name', env.get('JUJU_REMOTE_UNIT'))
        self.availability_zone = overrides.get('availability_zone', env.get('JUJU_AVAILABILITY_ZONE'))
        self.api_addresses = overrides.get('api_addresses', env.get('JUJU_API_ADDRESSES', '').split())
        self.juju_version = overrides.get('juju_version', env.get('JUJU_VERSION'))


class CharmMeta:
    """Object containing the metadata for the charm.

    The maintainers, tags, terms, series, and extra_bindings attributes are all
    lists of strings.  The requires, provides, peers, relations, storage,
    resources, and payloads attributes are all mappings of names to instances
    of the respective RelationMeta, StorageMeta, ResourceMeta, or PayloadMeta.

    The relations attribute is a convenience accessor which includes all of the
    requires, provides, and peers RelationMeta items.  If needed, the role of
    the relation definition can be obtained from its role attribute.
    """
    def __init__(self, raw=None):
        raw = raw or {}
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
        self.requires = {name: RelationMeta('requires', name, rel)
                         for name, rel in raw.get('requires', {}).items()}
        self.provides = {name: RelationMeta('provides', name, rel)
                         for name, rel in raw.get('provides', {}).items()}
        self.peers = {name: RelationMeta('peers', name, rel)
                      for name, rel in raw.get('peers', {}).items()}
        self.relations = {}
        self.relations.update(self.requires)
        self.relations.update(self.provides)
        self.relations.update(self.peers)
        self.storage = {name: StorageMeta(name, store)
                        for name, store in raw.get('storage', {}).items()}
        self.resources = {name: ResourceMeta(name, res)
                          for name, res in raw.get('resources', {}).items()}
        self.payloads = {name: PayloadMeta(name, payload)
                         for name, payload in raw.get('payloads', {}).items()}
        self.extra_bindings = raw.get('extra-bindings', [])


class RelationMeta:
    """Object containing metadata about a relation definition."""
    def __init__(self, role, relation_name, raw):
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
        self.filename = raw['filename']
        self.description = raw.get('description', '')


class PayloadMeta:
    """Object containing metadata about a payload definition."""
    def __init__(self, name, raw):
        self.payload_name = name
        self.type = raw['type']
