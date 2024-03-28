# 2.12.0 - 28 Mar 2024

## Features

* feat(Model): support credential-get hook tool in both model and harness (#1152)
* feat(Harness): add some support for user secrets (#1167)

## Fixes

* fix: add_relation consistency check and default network (#1138)
* fix(framework): add warning on lost observer weakref (#1142)
* fix(pebble)!: change select=all to users=all for pebble get_notices (#1146)
* fix: inspect the correct signature when validating observe arguments (#1147)
* fix(harness): don't error out when attempting attaching storage before begin (#1150)
* fix(model): change model.relation.app type from optional to mandatory (#1151)
* fix(pebble): catch socket.timeout exception in pebble.Client.exec() (#1155)
* fix(Harness): remove special-casing for `get_relation` in leader-elected (#1156)

## Documentation

* docs: use 'integrate with' rather than 'relate to' (#1145)
* docs(testing): update code samples in ops.testing from unittest to pytest style (#1157)
* docs: adjust change log entries, and update HACKING.md to match (#1159)
* docs: update read the docs to canonical starter pack (#1163, #1164, #1165)
* docs(Harness): add a paragraph on peer relations in add_relation (#1168)

## Tooling

* chore: Refactor main.py to add a new _Manager class (#1085)
* chore: adjust version number to work on the 2.12.0 release (#1141)
* chore: adjust the imports so that both ruff and isort pass (#1143)

# 2.11.0 - 29 Feb 2024

## Features

* `StopEvent`, `RemoveEvent`, and all `LifeCycleEvent`s are no longer deferrable, and will raise a `RuntimeError` if `defer()` is called on the event object (#1122)
* Add `ActionEvent.id`, exposing the JUJU_ACTION_UUID environment variable (#1124)
* Add support for creating `pebble.Plan` objects by passing in a `pebble.PlanDict`, the
  ability to compare two `Plan` objects with `==`, and the ability to create an empty Plan with `Plan()` (#1134)

## Fixes

* The remote app name (and its databag) is now consistently available in relation-broken events (#1130)

## Documentation

* Improve the `can_connect()` API documentation (#1123)

## Tooling

* Use ruff for linting (#1120, #1139, #1114)

# 2.10.0 - 31 Jan 2024

## Features

* Add support for Pebble Notices (`PebbleCustomNoticeEvent`, `get_notices`, and so on) (#1086, #1100)
* Add `Relation.active`, and excluded inactive relations from `Model.relations` (#1091)
* Add full support for charm metadata v2 (in particular, extended `ContainerMeta`,
  and various info links in `CharmMeta`) (#1106)
* When handling actions, print uncaught exceptions to stderr (#1087)
* Raise `ModelError` in Harness if an invalid status is set (#1107)

## Fixes

* Add Pebble log targets and checks to testing plans (#1111)
* CollectStatusEvent is now a LifecycleEvent (#1080)

## Documentation

* Update README to reflect charmcraft init changes (#1089)
* Add information on pushing locked/bind-mount files (#1094)
* Add instructions for using a custom version of ops to HACKING (#1092)

## Tooling

* Use pyproject.toml for building (#1068)
* Update to the latest version of Pyright (#1105)

# 2.9.0 - 30 Nov 2023

## Features

* Add log target support to `ops.pebble` layers and plans (#1074)
* Add `Harness.run_action()`, `testing.ActionOutput`, and `testing.ActionFailed` (#1053)

## Fixes

* Secret owners no longer auto-peek, and can use refresh, in Harness, and corrected secret access for non-leaders (#1067, #1076)
* Test suite adjustments to pass with Python 3.12 (#1081)

## Documentation

* Refresh README (#1052)
* Clarify how custom events are emitted (#1072)
* Fix the `Harness.get_filesystem_root` example (#1065)

# 2.8.0 - 25 Oct 2023

## Features

* Add `Unit.reboot()` and `Harness.reboot_count` (#1041)
* Add `RelationMeta.optional` (#1038)
* Raise a clearer exception when the Pebble socket is missing (#1049)

## Fixes

* The type of a `Handle`'s `key` was expanded from `str` to `str|None`
* Narrow types of `app` and `unit` in relation events to exclude `None` where applicable
* `push_path` and `pull_path` now include empty directories (#1024)
* Harness's `evaluate_status` resets collected statuses (#1048)

## Documentation

* Notes that status changes are immediate (#1029)
* Clarifies `set_results` maximum size (#1047)
* Expands documentation on when exceptions may be raised (#1044)
* Makes `pebble.Client.remove_path` and `Container.remove_path` docs consistent (#1031)

## Tooling

* Adds type hinting across the test suite (#1017, #1015, #1022, #1023, #1025, #1028, #1030, #1018, #1034, #1032)

# 2.7.0 - 29 Sept 2023

## Features

* Adds Unit.set_ports() (#1005)
* Type checks now allow comparing a `JujuVersion` to a `str`
* Rename `OpenPort` to `Port` (`OpenPort` remains as an alias)

## Documentation

* Reduces the amount of detail in open/close port methods (#1006)
* Removes you/your from docstrings (#1003)
* Minor improvements to HACKING (#1016)

## Tooling

* Extends the use of type hints in the test suite (#1008, #1009, #1011, #1012, #1013, #1014, #1004)
