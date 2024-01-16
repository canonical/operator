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
