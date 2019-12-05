from op.framework import Object, Event, EventBase, EventsBase


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
    def __init__(self, handle, relation, app=None, unit=None):
        super().__init__(handle)

        if unit and unit.app != app:
            raise RuntimeError(f'cannot create RelationEvent with application {app} and unit {unit}')

        self.relation = relation
        self.app = app
        self.unit = unit

    def snapshot(self):
        snapshot = {
            'relation_name': self.relation.name,
            'relation_id': self.relation.id,
        }
        if self.app:
            snapshot['app_name'] = self.app.name
        if self.unit:
            snapshot['unit_name'] = self.unit.name
        return snapshot

    def restore(self, snapshot):
        self.relation = self.framework.model.get_relation(snapshot['relation_name'], snapshot['relation_id'])

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

        for relation_name in self.framework.meta.relations:
            relation_name = relation_name.replace('-', '_')
            self.on.define_event(f'{relation_name}_relation_joined', RelationJoinedEvent)
            self.on.define_event(f'{relation_name}_relation_changed', RelationChangedEvent)
            self.on.define_event(f'{relation_name}_relation_departed', RelationDepartedEvent)
            self.on.define_event(f'{relation_name}_relation_broken', RelationBrokenEvent)

        for storage_name in self.framework.meta.storages:
            storage_name = storage_name.replace('-', '_')
            self.on.define_event(f'{storage_name}_storage_attached', StorageAttachedEvent)
            self.on.define_event(f'{storage_name}_storage_detaching', StorageDetachingEvent)


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
        self.storages = {name: StorageMeta(name, storage)
                         for name, storage in raw.get('storage', {}).items()}
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
