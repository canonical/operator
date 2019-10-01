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


class Charm(Object):

    on = CharmEvents()
