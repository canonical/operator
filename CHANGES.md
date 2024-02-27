# 2.11.0

* `StopEvent`, `RemoveEvent`, and all `LifeCycleEvent`s are no longer deferrable, and will raise a `RuntimeError` if `defer()` is called on the event object.
* The remote app name (and its databag) is now consistently available in relation-broken events.
* Added `ActionEvent.id`, exposing the JUJU_ACTION_UUID environment variable.
* Added support for creating `pebble.Plan` objects by passing in a `pebble.PlanDict`, the
  ability to compare two `Plan` objects with `==`, and the ability to create an empty Plan with `Plan()`.

# 2.10.0

* Added support for Pebble Notices (`PebbleCustomNoticeEvent`, `get_notices`, and so on)
* Added `Relation.active`, and excluded inactive relations from `Model.relations`
* Added full support for charm metadata v2 (in particular, extended `ContainerMeta`,
  and various info links in `CharmMeta`)

# 2.9.0

* Added log target support to `ops.pebble` layers and plans
* Added `Harness.run_action()`, `testing.ActionOutput`, and `testing.ActionFailed`

# 2.8.0

* Added `Unit.reboot()` and `Harness.reboot_count``
* Added `RelationMeta.optional`
* The type of a `Handle`'s `key` was expanded from `str` to `str|None`
* Narrowed types of `app` and `unit` in relation events to exclude `None` where applicable

# 2.7.0

* Added Unit.set_ports()
* Type checks now allow comparing a `JujuVersion` to a `str`
* Renamed `OpenPort` to `Port` (`OpenPort` remains as an alias)
