from juju.framework import Object, Event, EventBase, EventsBase


class InstallEvent(EventBase): pass
class StartEvent(EventBase): pass
class StopEvent(EventBase): pass
class ConfigChangedEvent(EventBase): pass
class UpdateStatusEvent(EventBase): pass
class UpgradeCharmEvent(EventBase): pass
class PreSeriesUpgradeEvent(EventBase): pass
class PostSeriesUpgradeEvent(EventBase): pass
class LeaderElectedEvent(EventBase): pass
class LeaderSettingsChangedEvent(EventBase): pass


# TODO: This should probably be split to RelationEventBase and StorageEventBase
# and be passed in a model object, rather than just a name
class DynamicEventBase(EventBase):
    def __init__(self, handle, name):
        super().__init__(handle)
        self.name = name

    def snapshot(self):
        return {'name': self.name}

    def restore(self, snapshot):
        self.name = snapshot['name']


class RelationJoinedEvent(DynamicEventBase): pass
class RelationChangedEvent(DynamicEventBase): pass
class RelationDepartedEvent(DynamicEventBase): pass
class RelationBrokenEvent(DynamicEventBase): pass
class StorageAttachedEvent(DynamicEventBase): pass
class StorageDetachingEvent(DynamicEventBase): pass


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

    def __init__(self, metadata, framework, key):
        super().__init__(framework, key)
        self.metadata = metadata

        for role in ('requires', 'provides', 'peers'):
            for relation_name in metadata.get(role, {}).keys():
                self.on.define_event(f'{relation_name}_relation_joined',
                                     RelationJoinedEvent)
                self.on.define_event(f'{relation_name}_relation_changed',
                                     RelationChangedEvent)
                self.on.define_event(f'{relation_name}_relation_departed',
                                     RelationDepartedEvent)
                self.on.define_event(f'{relation_name}_relation_broken',
                                     RelationBrokenEvent)

        for storage_name in metadata.get('storage', {}).keys():
            self.on.define_event(f'{storage_name}_storage_attached',
                                 StorageAttachedEvent)
            self.on.define_event(f'{storage_name}_storage_detaching',
                                 StorageDetachingEvent)
