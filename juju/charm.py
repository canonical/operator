from juju.framework import Object, EventBase, EventsBase


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

    install = InstallEvent
    start = StartEvent
    stop = StopEvent
    update_status = UpdateStatusEvent
    config_changed = ConfigChangedEvent
    upgrade_charm = UpgradeCharmEvent
    pre_series_upgrade = PreSeriesUpgradeEvent
    post_series_upgrade = PostSeriesUpgradeEvent
    leader_elected = LeaderElectedEvent
    leader_settings_changed = LeaderSettingsChangedEvent


class Charm(Object):

    on = CharmEvents()
