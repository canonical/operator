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
| install                     | Triggered when the charm is installed on a unit, usually used to install packages and environment for the charm.        |
| start                       | Triggered after the charm instal step has run. Usually used to finialise configuration, or to start a service        |
| update_status               | Triggered when configuration is changed, or when another event triggered an event        |
| config_changed              | TODO        |
| update_charm                | TODO        |
| pre_serires_upgrade         | TODO        |
| post_series_upgrade         | TODO        |
| leader_elected              | TODO        |
| leader_settings_changed     | TODO        |