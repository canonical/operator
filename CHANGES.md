# 2.8.0

* Added `Unit.reboot()` and `Harness.reboot_count``
* Added `RelationMeta.optional`
* The type of a `Handle`'s `key` was expanded from `str` to `str|None`
* Narrowed types of `app` and `unit` in relation events to exclude `None` where applicable

# 2.7.0

* Added Unit.set_ports()
* Type checks now allow comparing a `JujuVersion` to a `str`
* Renamed `OpenPort` to `Port` (`OpenPort` remains as an alias)
