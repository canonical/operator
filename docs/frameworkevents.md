# Framework events


## List

### FrameworkEvents

| Event Name | Description |
|:----------:|:-----------:|
| pre_commit | TODO        |
| commit     | TODO        |


### CharmEvents

| Event Name | Description | type |
|:----------:|:-----------:|:-----|
| install                     | Triggered when the charm is installed on a unit, usually used to install packages and environment for the charm.        | InstallEvent |
| start                       | Triggered after the charm instal step has run. Usually used to finialise configuration, or to start a service        | StartEvent |
| stop                        | Triggered when the charm is being removed | StopEvent |
| update_status               | Triggered when configuration is changed, or when another event triggered an event        | UpdateStatusEvent |
| config_changed              | Triggered when the charm configuration has changed, for example when `juju config` is run. | ConfigChangedEvent |
| upgrade_charm               | UpgradeCharmEvent |
| pre_serires_upgrade         | Triggered when a charm series upgrade is in progress, [See Upgrading Series](https://jaas.ai/docs/upgrading-series#heading--initiating-the-upgrade) | PreSeriesUpgradeEvent |
| post_series_upgrade         | Triggered when the series upgrade is finished, [See Completing the upgrade](https://jaas.ai/docs/upgrading-series#heading--completing-the-upgrade) | PostSeriesUpgradeEvent |
| leader_elected              | Run at least once to signify that juju decided this unit is the leader. | LeaderElectedEvent |
| leader_settings_changed     | Runs when the leader has set values for the other units to respond to. | LeaderSettingsChangedEvent |
