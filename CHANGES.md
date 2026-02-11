# 2.23.2 - 11 February 2026

## Documentation

* For 2.23, update links and config for switch to documentation.ubuntu.com/ops (#1942)
* For 2.x, fix site title and unstyled error pages (#1945)
* For 2.x, remove .html extensions (#1954)
* For 2.x, fix unstyled error pages (#1973)

# 2.23.1 - 30 July 2025

## Fixes

* Add the remote unit to `Relation.data` but not `Relation.units` (#1928)

## Documentation

* Be consistent with recommending `self.app` and `self.unit` (#1856)
* Add notice about ops 2 and ops 3 (#1867)
* Update title and edit links for ops 2.23 docs (#1885)

## CI

* Hotfix, publish job for ops-tracing (#1865)

# 2.23.0 - 30 June 2025

## Features

* Support for config schema as Python classes (#1741)
* Support for action parameter schema as Python classes (#1756)
* Ops[tracing] compatibility with jhack (#1806)
* Support for relation data schema as Python classes (#1701)
* Add CheckInfo.successes field and .has_run property (#1819)
* Provide a method to create a testing.State from a testing.Context (#1797)
* Expose trace data in testing (#1842)
* Add a helper to generate a Layer from rockcraft.yaml (#1831)

## Fixes

* Correctly load an empty Juju config options map (#1778)
* Fix type annotation of container check_infos in ops.testing (#1784)
* Restrict the version of a dependency, opentelemetry-sdk (#1794)
* Remote unit data is available in relation-departed (#1364)
* Juju allows access to the remote app databag in relation-broken, so Harness should too (#1787)
* Don't use private OpenTelemetry API (#1798)
* Do not return this unit in a mocked peer relation (#1828)
* Testing.PeerRelation properly defaults to no peers (#1832)
* In meter-status-changed JUJU_VERSION is not set (#1840)
* Only provide the units belonging to the app in Relation.units (#1837)

## Documentation

* Remove two best practices, and drop two to tips (#1758)
* Update link to Charmcraft for managing app config (#1763)
* Update link to Juju documentation for setting up deployment (#1781)
* Fix external OTLP link (#1786)
* Distribute the ops-scenario README content across the ops docs (#1773)
* Improve testing.errors.UncaughtCharmError message (#1795)
* In the "manage the charm version" how-to, give an example of using override-build (#1802)
* Small adjustments to the 'how to trace charm code' doc (#1792)
* Replace Harness example and fix links in README (#1820)
* Add httpbin charm from Charmcraft as an example charm (#1743)
* Fix on_collect mistake in sample code (#1829)
* Update code in K8s tutorial, with source in repo (part 2) (#1734)
* Update Loki section on charming zero-to-hero tutorial (#1847)
* Remove expandable boxes of text (#1844)
* Improve httpbin charm by removing defer() and adding collect_status (#1833)
* Move {posargs} to the end of pytest command lines in tox.ini (#1854)

## CI

* Install the ops[tracing] dependencies for the TIOBE action (#1761)
* Add ops-scenario and ops-tracing as explicit installs for TIOBE (#1764)
* Persist credentials for update-charm-pins workflow (#1766)
* Stop smoke testing Charmcraft 2 (#1782)
* Use Charmcraft 3.x for smoke testing 20.04 and 22.04 (#1821)
* Enable xdist for the 'unit' tox environments (#1830)

# 2.22.0 - 29 May 2025

## Features

* Add Juju topology labels (#1744)

## Fixes

* Turn on databag access validation in `__init__` (#1737)
* Allow event suffixes to appear in event names in `ops.testing` (#1754)

## Documentation

* Document how to manage metrics (#1692)
* Link to our docs from the top of our README (#1710)
* Update code in K8s tutorial, with source in repo (part 1) (#1719)
* Update links to juju.is/docs (#1725)
* Fix link in breakpoint output, remove link from Harness error message (#1726)
* Update Matrix channel name to Charm Tech (#1740)
* Rename configurations to configuration (#1746)
* Fix typos in code snippets by @MattiaSarti (#1750)

## CI

* Add `ops[tracing]` integration tests (#1686)
* Pin workflows by hash (#1721)
* Disable alertmanager compatibility tests until upstream fix (#1745)
* Remove explicit scopes and update HACKING.md (#1748)
* Pin trusted workflows by tag (#1752)
* Re-enable `alertmanager-k8s-operator` in observability charm tests (#1753)
* Fix reporting to TIOBE after `ops[tracing]` addition (#1755)

# 2.21.1 - 1 May 2025

## Reverted

* Reverting "run deferred events with fresh charm instances" (#1711)

## Documentation

* Add best practices about status (#1689)

# 2.21.0 - 30 Apr 2025

## Features

* Ops[tracing] (with a first-party charm lib) (#1612)
* Pebble identities (#1672)
* Run deferred events with fresh charm instances (#1631)

## Fixes

* Allow TLS 1.2 in ops-tracing (#1705)
* Try to fix flaky pebble exec test (#1664)

## Documentation

* Add best practice note around using tooling provided by the charmcraft profile (#1700)
* Clarify guidance about designing python modules (#1670)
* Fix a bug in the k8s tutorial doc about unit test (#1688)
* Fix broken link in readme (#1679)
* Fix links to juju docs (#1681)
* Fix tox command in hacking.md (#1661)
* Improve landing page of kubernetes charm tutorial (#1660)

## CI

* Add zizmor to static check github workflows (#1656)
* Change prerelease setting used to add latest ops and scenario (#1682)
* Don't pin release jobs to github environments (#1683)
* Don't run tests within the publish job (#1684)
* Fix smoke test (#1698)
* Post-release versioning, release process update + workflow fix (#1658)
* Rename "tox -e fmt" to "tox -e format" (#1668)

## Tests

* Fix overly specific test that fails sometimes with tracing (#1695)

# 2.20.0 - 31 Mar 2025

## Features

* Add a `remove_revision()` method to `SecretRemoveEvent` and `SecretExpiredEvent` (#1624)
* Add `Relation.remote_model` property (#1610)
* Efficient implementation of `RelationDataContent.update` (#1586)
* Expose the config metadata in `CharmMeta` (#1648)
* Add the ability to emit custom events in unit tests (#1589)
* Check that the check-infos in `testing.Container` match the plan (#1630)
* `ops.testing.State` components are less mutable (#1617)

## Fixes

* Assorted fixes for Pebble layer merging in Harness and Scenario (#1627)

## Documentation

* Add a docs link to the Harness deprecation warning (#1513)
* Add best practices and a "manage charms" how-to (#1615)
* Add section about services with long startup time (#1604)
* Clarify how to use mounts in `ops.testing.Container` (#1637)
* Fix code snippet indentation (#1649)
* Fix Scenario example (#1616)
* Move hooks-based charm migration guide (#1636)
* Putting test into each chapter of the tutorial (#1647)
* Refactor how-to unit test according to comments (#1642)
* Refactor test docs to 1 explanation and 2 how-tos (#1628)
* Remove the charm-tech@lists.launchpad.net email address (#1632)
* Remove tutorial chapters that are covered by the how-to guide (#1511)
* Stack args vertically for long signature lines (#1641)
* Testing explanation (#1635)
* Unify charm test docs how to (#1639)

## CI

* Exclude vault-k8s-operator until the system can handle monorepos (#1650)
* Use the latest version of ops-scenario in the compatibility tests (#1608)

# 2.19.0 - 27 Feb 2025

## Features

* Expose the Juju version via Model objects (#1563)
* Support starting and stopping Pebble checks, and the checks enabled field (#1560)

## Documentation

* Update logo and readme by @tmihoc (#1571)
* Fill out remaining external link placeholders (#1564)
* Use noun relation and verb integrate (#1574)
* Update ref to charmcraft.yaml reference by @medubelko (#1580)
* Add a how-to for setting open ports (#1579)
* Fix links that pointed to earlier Juju docs (#1575)
* Update links to Charmcraft docs (#1582)
* Small updates to machine charm tutorial (#1583)

## CI

* Update list of charms and handle increasing uv usage (#1588)
* Handle presence/absence of "static" and "static-charm" envs (#1590)

# 2.18.1 - 5 Feb 2025

## Fixes

* Ensure that the event snapshot is available when one observer defers and another does not (#1562)
* Maintain transaction integrity on first run (#1558)

## Documentation

* Set up intersphinx and add links (#1546)

# 2.18.0 - 30 Jan 2025

## Features

* Don't store duplicate events in the notice queue (#1372)

## Fixes
* Remove ops.main.main deprecation warning, and avoid warnings in action output (#1496)

## Documentation
* Use the right ops-scenario for building the docs (#1470)
* Go full Diátaxis, ingesting the relevant juju.is/docs/sdk documentation by @tmihoc (#1481)
* Update boilerplate links (#1515)
* Fix broken links and use cross references instead of absolute links (#1519)
* Use explicit framework param instead of *args (#1523)
* Add doc style tips to HACKING.md (#1528)
* Fix link to Juju docs in Kubernetes charm tutorial (#1529)
* Remove the publish badge from the README (#1505)
* Add how-to for storing state (#1534)
* Improve info about contributing to docs (#1533)
* Fix formatting errors in HACKING.md (#1539)

## Continuous Integration
* Add support for injecting the latest ops when uv is used (#1477)
* Don't cancel other unit tests when one fails (#1471)
* Use Concierge to set up the smoke test environments (#1541)
* Bump poetry to 2.0 to match downstream (#1542)
* Enable the prometheus-k8s revision updates again (#1544)
* Include Juju 2.9 in the smoke tests (#1545)

## Testing
* Handle warnings generated by our own tests (#1469)
* Allow check to fail an additional time when running the test (#1531)

# 2.17.1 - 28 Nov 2024

## Fixes

* Make `push_path` open in binary mode so it works on non-text files (#1458)

## Documentation

* Use `MaintenanceStatus` for local issues (#1397)
* Explicitly document that `collect-status` is is run on every hook (#1399)
* Use our docs URL for the `ogp:url` properties Sphinx generates (#1411)
* Set the `READTHEDOCS` context variable (#1410)
* Fix Read the Docs ad placement (#1414)
* Clarify where `StoredState` is stored, and the upgrade behaviour (#1416)
* Fix copy 'n' paste error in `stop_services` docstring (#1457)

## Continuous Integration

* Configure the labels for dependabot PRs (#1407)
* Disable the automatic ops[testing] releasing (#1415)
* Use the actual poetry command, rather than manually tweaking the file (#1443)
* Fix broken GitHub variable expansion (#1446)
* Coverage report generation should also include testing/src/scenario (#1453)
* Fix PR title CI job concurrency (#1451)
* Adjust the release process to handle publishing ops and ops[testing] (#1432)
* A better way than commenting out external repos (#1463)
* Use more descriptive names for the publish workflows (#1464)
* Move the XML coverage report to .report (#1465)

## Refactoring

* Import the ops[testing] repository (#1406)
* Update linting with the latest ruff (#1441)

# 2.17.0 - 26 Sep 2024

## Features

* Optionally install Scenario with `ops[testing]` and expose the names in ops.testing (#1381)
* Change ops.main() so that you don't need to `type: ignore` it (#1345)
* Expand the secret ID out to the full URI when only given the ID (#1358)
* Add a JujuVersion property for Pebble log forwarding to Loki (#1370)
* Preemptively raise `InvalidStatusError` instead of waiting for Juju:
    * Make it an error to call `CollectStatusEvent.add_status` with error or unknown (#1386)
    * Document and validate settable status values in `_ModelBackend.set_status` (#1354)

## Fixes

* Fix type of `StatusBase` subclasses by calling `StatusBase.register` in `__init_subclass__` (#1383)
* `Secret.set_info` and `Secret.set_content` can be called in the same hook (#1373)

## Documentation

* Add top-level intro and module-level intros (#1320)
* Update the links to the Pebble docs (#1362)
* Note about repeatedly setting secret value in Juju 3.6 (#1366)
* `config-changed` is triggered by Juju trust (#1357)
* Typo on `CharmBase` inheritance example by @theofpa (#1349)
* Docs: move Pebble to a separate page (#1392)

## Continuous Integration

* Periodically run the unit tests of all GitHub-hosted published charms (#1365)
* Update the TIOBE reporting for the changes in coverage calculation (#1367)
* Spell-check the code as part of linting (#1388)
* Run the smoke tests on a schedule (#1387)

## Testing

* Fix tests that leaked environment variables (#1385)

## Refactoring

* Move the content of `ops.testing` to `ops._private.harness` (#1369)
* Keep the `unittest.mock` names in the 'mock' namespace (#1379)
* Deprecate `StatusBase.register` decorator (#1384)

## Chores

* Note Juju version on legacy workaround (#1355)
* Re-enable test now that Pebble directory permissions are fixed (#1363)
* Generate warnings for events that will be removed in Juju 4.0 (#1374)

# 2.16.1 - 5 Sep 2024

## Fix

* Don't alter os.environ when creating a Harness (#1359)

# 2.16.0 - 29 Aug 2024

## Features

* Add the description field to SecretInfo in (#1338)

## Refactor

* Parse JUJU_* environment variables in one place in (#1313)

## Fixes

* Fix reading Juju secret expiry dates in (#1317)
* Correct the signature of .events() in (#1342)

## Documentation

* Security policy change to only support each active major release in (#1297)
* Add Juju version markers in (#1311)
* Use Sphinx 8 in (#1303)
* Live reload documentation with sphinx-autobuild in (#1323)

## Tests

* Update the smoke test series/bases in (#1318)
* Run pytest in parallel with pytest xdist in (#1319)
* Bump Pyright to 1.1.377 in (#1332)
* Run tests on Python 3.12 and the install test on Python 3.13 in (#1315)

## CI

* Add a workflow that runs the TIOBE quality checks in (#1301)
* Allow executing the TIOBE workflow manually in (#1321)
* Make Pyright report unnecessary type ignore comments in (#1333)
* Enable linting of docs/custom_conf.py in (#1330)

# 2.15.0 - 22 Jul 2024

## Features

* Add support for Pebble check-failed and check-recovered events (#1281)

## Fixes

* Pass secret data to Juju via files, rather than as command-line values (#1290) fixing CVE-2024-41129
* Include checks and log targets when merging layers in ops.testing (#1268)

## Documentation

* Clarify distinction between maintenance and waiting status (#1148)

## CI

* Bump the Go version to match Pebble (#1285)
* Run ruff format over charm pin update code (#1278)
* Bump certifi from 2024.2.2 to 2024.7.4 in /docs (#1282)
* Update charm pins (#1269)

# 2.14.1 - 27 Jun 2024

## Fixes

* Add connect timeout for exec websockets to avoid hanging (#1247)
* Adjust Harness secret behaviour to align with Juju (#1248)

## Tests

* Fix TypeError when running test.pebble_cli (#1245)
* Properly clean up after running setup_root_logging in test_log (#1259)
* Verify that defer() is not usable on stop,remove,secret-expired,secret-rotate (#1233)

## Documentation

* Fix HACKING.md link on PyPI, and internal links (#1261, #1236)
* Add a section to HACKING.md on PR titles (commit messages to main) (#1252)
* Add release step to update pinned charm tests (#1213)
* Add a security policy (#1266)

## CI

* Only run tests once on push to PR (#1242)
* Validate PR title against conventional commit rules in (#1262)
* Only update ops, not all dependencies, in charm tests in (#1275)
* Add artefact attestation (#1267)

# 2.14.0 - 29 May 2024

## Features

* Add a `__str__` to ActionFailed, for better unexpected failure output (#1209)

## Fixes

* The `other` argument to `RelatationDataContent.update(...)` should be optional (#1226)

## Documentation

* Use the actual emoji character rather than GitHub markup, to show properly on PyPI (#1221)
* Clarify that SecretNotFound may be raised for permission errors (#1231)

## Refactoring

* Refactor tests to pytest style (#1199, #1200, #1203, #1206)
* Use `ruff` formatter and reformat all code (#1224)
* Don't use f-strings in logging calls (#1227, 1234)

# 2.13.0 - 30 Apr 2024

## Features

* Added support for user secrets in Harness (#1176)

## Fixes

* Corrected the model config types (#1183)
* In Harness, only inspect the source file if it will be used - this fixed using Harness in a Python REPL (#1181)

## Documentation

* Updated publishing a release in HACKING.md (#1173)
* Added `tox -e docs-deps` to compile requirements.txt (#1172)
* Updated doc to note deprecated functionality in (#1178)

## Tests

* First stage of converting tests from unittest to pytest (#1191, #1192, #1196, #1193, #1195)
* Added `pebble.CheckInfo.change_id` field (#1197)

# 2.12.0 - 28 Mar 2024

## Features

* Added `Model.get_cloud_spec` which uses the `credential-get` hook tool to get details of the cloud where the model is deployed (#1152)

## Fixes

* Update Pebble Notices `get_notices` parameter name to `users=all` (previously `select=all`) (#1146)
* Warn when an observer weakref is lost (#1142)
* More robust validation of observer signatures (#1147)
* Change `Model.relation.app` type from `Application|None` to `Application` (#1151)
* Fix attaching storage in Harness before `begin` (#1150)
* Fixed an issue where `pebble.Client.exec` might leak a `socket.timeout` (`builtins.TimeoutError`) exception (#1155)
* Add a consistency check and default network to `add_relation` (#1138)
* Don't special-case `get_relation` behaviour in `leader-elected` (#1156)
* Accept `type: secret` for config options (#1167)

## Refactoring

* Refactor main.py, creating a new `_Manager` class (#1085)

## Documentation

* Use "integrate with" rather than "relate to" (#1145)
* Updated code examples in the docstring of `ops.testing` from unittest to pytest style (#1157)
* Add peer relation details in `Harness.add_relation` docstring (#1168)
* Update Read the Docs Sphinx Furo theme to use Canonical's latest styling (#1163, #1164, #1165)

# 2.11.0 - 29 Feb 2024

## Features

* `StopEvent`, `RemoveEvent`, and all `LifecycleEvent`s are no longer deferrable, and will raise a `RuntimeError` if `defer()` is called on the event object (#1122)
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
