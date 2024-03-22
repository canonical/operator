# 2.11.0

Features:

* `StopEvent`, `RemoveEvent`, and all `LifeCycleEvent`s are no longer deferrable, and will raise a `RuntimeError` if `defer()` is called on the event object (#1122)
* Added `ActionEvent.id`, exposing the JUJU_ACTION_UUID environment variable (#1124)
* Added support for creating `pebble.Plan` objects by passing in a `pebble.PlanDict`, the
  ability to compare two `Plan` objects with `==`, and the ability to create an empty Plan with `Plan()` (#1134)

Fixes:

* The remote app name (and its databag) is now consistently available in relation-broken events (#1130)

Documentation:

* Improved the `can_connect()` API documentation (#1123)

Tooling:

* Use ruff for linting (#1120, #1139, #1114)

# 2.10.0

Features:

* Added support for Pebble Notices (`PebbleCustomNoticeEvent`, `get_notices`, and so on) (#1086, #1100)
* Added `Relation.active`, and excluded inactive relations from `Model.relations` (#1091)
* Added full support for charm metadata v2 (in particular, extended `ContainerMeta`,
  and various info links in `CharmMeta`) (#1106)
* When handling actions, print uncaught exceptions to stderr (#1087)
* Raise `ModelError` in Harness if an invalid status is set (#1107)

Fixes:

* Added Pebble log targets and checks to testing plans (#1111)
* CollectStatusEvent is now a LifecycleEvent (#1080)

Documentation:

* Update README to reflect charmcraft init changes (#1089)
* Add information on pushing locked/bind-mount files (#1094)
* Add instructions for using a custom version of ops to HACKING (#1092)

Tooling:

* Use pyproject.toml for building (#1068)
* Update to the latest version of Pyright (#1105)

# 2.9.0

Features:

* Added log target support to `ops.pebble` layers and plans (#1074)
* Added `Harness.run_action()`, `testing.ActionOutput`, and `testing.ActionFailed` (#1053)

Fixes:

* Secret owners no longer auto-peek, and can use refresh, in Harness, and corrected secret access for non-leaders (#1067, #1076)
* Test suite adjustments to pass with Python 3.12 (#1081)

Documentation:

* Refreshed README (#1052)
* Clarify how custom events are emitted (#1072)
* Fixed the `Harness.get_filesystem_root` example (#1065)

# 2.8.0

Features:

* Added `Unit.reboot()` and `Harness.reboot_count` (#1041)
* Added `RelationMeta.optional` (#1038)
* Clearer exception when the Pebble socket is missing (#1049)

Fixes:

* The type of a `Handle`'s `key` was expanded from `str` to `str|None`
* Narrowed types of `app` and `unit` in relation events to exclude `None` where applicable
* `push_path` and `pull_path` now include empty directories (#1024)
* Harness's `evaluate_status` resets collected statuses (#1048)

Documentation:

* Noted that status changes are immediate (#1029)
* Clarified `set_results` maximum size (#1047)
* Expanded documentation on when exceptions may be raised (#1044)
* Made `pebble.Client.remove_path` and `Container.remove_path` docs consistent (#1031)

Tooling:

* Added type hinting across the test suite (#1017, #1015, #1022, #1023, #1025, #1028, #1030, #1018, #1034, #1032)

# 2.7.0

Features:

* Added Unit.set_ports() (#1005)
* Type checks now allow comparing a `JujuVersion` to a `str`
* Renamed `OpenPort` to `Port` (`OpenPort` remains as an alias)

Documentation:

* Reduce the amount of detail in open/close port methods (#1006)
* Remove you/your from docstrings (#1003)
* Minor improvements to HACKING (#1016)

Tooling:

* Extend the use of type hints in the test suite (#1008, #1009, #1011, #1012, #1013, #1014, #1004)
