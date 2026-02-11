# 3.5.2 - 11 February 2026

## Fixes

* Make testing.CheckInfo level arg type match pebble.CheckInfo.level (#2274)
* Credential-get is available on k8s in newer Juju (#2307)
* Drop unused `setuptools_scm` build dependency (#2310)

## Documentation

* Update Pebble version in Juju 3.6 (#2295)
* Refresh K8s tutorial to use Concierge and uv-based Charmcraft profile (#2285)
* Add missing "How to" in page titles (#2289)
* Fix and improve observability part of K8s tutorial (#2305)

# 3.5.1 - 28 January 2026

## Fixes

* Use `parse_rfc3339` for datetime parsing to support Juju 4 (#2264)
* Correct the value of `additional_properties` in the action meta in Juju 4 (#2250)
* Prevent `KeyError` on `auth-type` when creating `CloudCredential` object (#2268)
* `_checks_action` should return empty list when there are no changes (#2270)

## Documentation

* Provide examples in unit testing how-to, and other small improvements (#2251)
* Update the action how-to to explain the additionalProperties default flip (#2249)
* For state-transition tests, clarify about immutability and reusing state (#2153)
* Fix and clarify holistic example of handling storage (#2098)
* Remove comments from K8s tutorial and clarify about persisting data (#2253)
* Clarify handling of postgres relation data in K8s tutorial (#2256)
* Improve unit tests of httpbin demo charm (#2254)
* Add version information for tools in the charming ecosystem (#2231)
* Avoid emojis that render differently across platforms (#2273)
* Secrets over CMR comment added (#2271)
* Fix charm name in httpbin deploy command (#2276)
* Updated security@ubuntu.com PGP key (#2286)

## Tests

* Remove unnecessary test module (#2247)

## CI

* Replace git reference injection with wheel artifacts in charm test workflows (#2252)
* Explicitly provide the charmcraft repo location in CI (#2277)
* Remove outdated custom signature generation (#2280)

# 3.5.0 - 18 December 2025

## Features

* Env var to control exception wrapping in tests (#2142)
* Deprecate testing.Context.charm_spec (#2219)

## Documentation

* Fix charmcraft init command (#2210)
* Update CI examples to use uv and tox-uv (#2213)
* Update and clarify info about environment prep (#2217)
* Match Charmcraft profiles in tox.ini example for integration testing (#2221)
* Use base 24.04 for httpbin-demo charm (#2222)
* Clarify parts of the machine charm tutorial (#2223)
* Match Charmcraft profiles in "Write and structure charm code" (#2220)
* Use cosl binary in K8s tutorial charm to work around error (#2232)
* Fix URL issues by updating doc starter pack (#2238)

## Tests

* Don't skip tests if ops[testing] isn't installed (#2215)
* Switch the integration test charms to use the uv plugin (#2218)

## CI

* Avoid jitter in the best practice doc PRs (#2193)
* Ignore PERF401 (manual list comprehension) across the repo (#2201)
* The git commands need to be run in the operator directory as well (#2197)
* Have cycle in the sbomber manifests use the default value (#2209)
* Add pytest.warns to note an expected warning (#2092)
* Update release script to handle non-final versions (#2199)
* Add ops-tracing as a dependency for the observability tests (#2239)
* Add scheduled workflow for packing and integration testing example charms (#2233)

# 3.4.0 - 27 November 2025

## Breaking Changes

* Fix: Change JujuContext.machine_id from int to str (#2108)
* Fix: Ensure that the testing context manager is exited when an exception occurs (#2117)

## Features

* Add a low-level API for the Juju hook commands (#2019)
* Make PebbleClient file methods also accept pathlib.PurePath (#2097)
* Log the total number of deferred events (#2161)
* Allow setting the Juju availability zone and principal unit in the testing Context (#2187)

## Fixes

* Allow actions without params or descriptions in ops[testing] (#2090)
* Ensure `ops.Pebble.pull` cleans up temporary files if it errors (#2087)
* Make secret info description visible to the charm in ops[testing] (#2115)
* Raise ActionFailed when using Context as a context manager (#2121)
* Detect categories with an exclamation mark indicating breaking changes (#2132)
* Normalise Secret.owner to 'app' for ops[testing] output state (#2127)
* Don't cache secret metadata in Ops (#2143)
* Secret-info-get cannot be provided with both an ID and a label (#2170)
* Minor hookcmds fixes (#2175)

## Documentation

* Update referenced examples for managing interfaces (#2068)
* Tidy up spelling and formatting in several places (#2060)
* Add missing assignment to state_out in unit tests how-to (#2075)
* Update the holistic/delta explanation with the reconciler pattern (#2029)
* Fix broken setup/teardown links in README (#2094)
* Update info about release docs, mark testing changelog as not maintained (#2074)
* Switch to makefile for building the docs (#2073)
* Document how to extract the charm instance from the testing context (#2084)
* Add a how-to guide for migrating away from Harness (#2062)
* Rename hook tools to hook commands (#2114)
* Remove legacy how-to guide for Harness (#2122)
* Update the Juju release the metrics functionality is removed from 4.0 to 3.6.11 (#2126)
* Clarify that Context is the testing context not only the Juju context (#2123)
* Explain the Charmhub public listing process and add a reference list of best practices (#1989)
* Expand next steps for K8s tutorial (#2034)
* Remove mention of the `simple` Charmcraft profile (#2138)
* Expand landing pages with summaries of pages (#2140)
* Update environment setup for integration tests and K8s tutorial (#2124)
* Replace machine charm tutorial by an improved tutorial (#2119)
* Change HACKING.md instructions for maintaining Charmcraft profiles (#2151)
* In integration tests, use consistent approach to logging and packing (#2150)
* In integration testing how-to, clarify that Juju model is destroyed after all tests in the model complete (#2154)
* Remove Charmcraft channel specifier from machine charm tutorial (#2148)
* Add AI contribution note and style guideline for type annotation of return values (#2168)
* Add ops[testing] to the ops.testing docstring (#2171)
* Add links to the Juju hook from each event class (#2176)
* Add a short umask note (#2184)

## Tests

* Re-enable testing consistency checks after disabling them (#2141)
* Expand secrets integration and state transition tests (#2130)

## Refactoring

* Use ops.hookcmds in _ModelBackend (#2116)
* Don't get the storage details from --help (#2172)
* Drop 3.8 and 3.9 compatibility code (#2173)
* Use json.dumps to produce the YAML in relation-set and state-set (#2174)
* Rely on type annotations instead of casts in hookcmds (#2179)

## CI

* Add integration and state transition tests for the secrets API (#2078)
* Temporarily disable tracing integration tests (#2102)
* Add secrets tests follow-up (#2105)
* Support monorepos in ops charm compatibility testing (#2100)
* Test both Charmcraft 3 and Charmcraft 4 profiles (#2103)
* Add automated doc checks (and related starter pack updates) (#2099)
* Clean up accidental workflow trigger (#2144)
* Test if package versions match dependency versions before publishing (#2139)
* Update spelling (#2167)
* Test against 4.0/stable (#2186)
* Store charmcraft logs if smoke tests fail (#2192)
* Use Juju channel 4/stable in Ops smoke tests (#2190)

# 3.3.0 - 29 September 2025

## Features

* Expose the Juju hook context in ops.JujuContext (#1996)

## Fixes

* In testing, separate relation data cache from mock Juju backend (#2052)

## Documentation

* Use uv for testing and packing the httpbin charm (#2011)
* Improve intro to ops.testing reference (#2023)
* In httpbin charm integration tests, add env var for charm file to deploy (#2018)
* Update get_cloud_spec doc now that credential-get works on K8s (#2031)
* Note that arbitrary_types_allowed is required when ops.Secret is used in a Pydantic class (#2038)
* Clean up Resources.fetch docstring, add ModelError exception (#2039)
* Note that the peer databag isn't usable during the install event (#2051)
* Fix testing code in actions how-to guide (#2054)

## CI

* Nicer logging output in the release script using rich (#2017)
* Clean up PYTHONPATH in tox.ini (#2058)

# 3.2.0 - 28 August 2025

## Features

* Add security event logging (#1905)
* Surface JUJU_MACHINE_ID envvar in testing env (#1961)
* Add a new log target type opentelemetry (#1937)

## Documentation

* Update links and config for switch to documentation.ubuntu.com/ops (#1940)
* Update the required Python version and note the 2.x documentation site (#1946)
* Be consistent with recommending self.config (#1947)
* Use latest styles from starter pack and remove .html extensions (#1951)
* Remove .html extensions from hardcoded links (#1955)
* Fix broken URLs in sitemap (#1956)
* Add related doc links to homepage (#1959)
* Use classes from ops instead of ops.<submodule> (#1968)
* Fix unstyled error pages (#1969)
* Add Google Analyics integration and cookie consent banner (#1971)
* Refresh docs homepage with more context about Ops (#1964)
* Update link to Charmlibs docs (#1985)
* Remove unnecessary pages from sitemap (#1979)
* Update the httpbin example charm to Jubilant (#1987)
* Update the Zero to Hero tutorial to Jubilant (#1988)
* Add model-config best practice note (#1990)
* Change some best practices to tips (#2001)
* Add integration test for invalid config in httpbin charm (#2002)
* Make a `Layer` instead of a `LayerDict` in the httpbin charm (#2003)
* Update how-to to feature Jubilant (#2000, #2004)
* Use Charmcraft-style format and lint for example charms, not Ops-style (#2008)
* Update broken link to HookVars source code (#2006)

## CI

* Fixes for the SBOM and security scan workflow, and trigger it on publishing (#1916)
* Store the charmcraft logs if packing fails (#1936)
* Install release dependencies for the TIOBE analysis (#1930)
* Add Juju 4/beta to the smoke test matrix (#1963)
* Adjust permissions block in publish workflow (#1984)
* Update actions/checkout to v5 (#1993)
* Enable doctests (#1991)
* Ignore juju/4 timeouts (#1998)
* Remove the token for SBOM and security scan workflow (#2009)
* Speed up integration test (#1978)

# 3.1.0 - 30 July 2025

## Features

* Release automation script (#1855)
* Add app_name and unit_id attributes to testing.context (#1920)
## Fixes

* If an event ends with _abort(0) tests should behave as if it ended successfully (#1887)
* If self.app is not actually set avoid a new crash location (#1897)
* Only add the remote unit for departed and broken relation events, fix ordering (#1918)
* Add the remote unit to relation.data but not relation.units (#1925)
## Documentation

* Use load_config in the httpbin example charm (#1852)
* Update HACKING.md with how to bump `ops` version in Charmcraft profiles (#1872)
* Change title of docs site (#1890)
* Use config and action classes in the Kubernetes tutorial (#1891)
* Reference example charms from K8s tutorial and fix consistency (#1898)
* Update style guide (#1720)
* Fix issues in how-to guide for stored state (#1901)
* Link out to the 12-factor tutorials from the tutorial index page (#1902)
* Replace broken link in testing explanation (#1913)
* Expand the storage how-to with content from Juju docs scheduled for removal (#1915)
* Ops tracing how to (#1853)
* Add a security explanation doc (#1904)


## Tests

* Replace Python version to 3.10 for observability charm tests (#1914)
## CI

* Use httpbin demo charm for the Charmcraft pack test (#1895)
* Move TIOBE workflow to self-hosted runners (#1912)
* Add SBOM generation and secscan workflow (#1906)
* Build and publish in one step (#1857)
* Update the name and email when updating the charm pins (#1924)
* Drop smoke test against 20.04 (#1923)

# 3.0.0 - 02 July 2025

The minimum version of Python for Ops 3.x is 3.10.

## Documentation

* Be consistent with recommending self.app and self.unit (#1856)

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

* Added `Model.get_cloud_spec` which uses the `credential-get` hook command to get details of the cloud where the model is deployed (#1152)

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
