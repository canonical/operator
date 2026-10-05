## 2.23.4: backport fixes from 3.x

2.23 is the LTS series for Ops, and this release brings it up to date with the bug fixes made in the 3.x series from **3.1.0 through to 3.8.0** (everything that was applicable to 2.23 and did not require behaviour changes or features that only exist in 3.x). There are no new features and no breaking changes.

Most of the fixes are in `ops.testing` (Scenario and Harness), where several long-standing sources of confusing test results are resolved. The runtime fixes are smaller in number but include two that can hang or crash a real charm.

### Runtime fixes worth knowing about

* **Exec no longer leaks I/O threads when the wait fails** (#2558). If a `Container.exec()` change outlived the client-side wait (for example, an orphaned process holding the exec's stdio open), the non-daemon I/O pump threads stayed blocked in `recv()` and prevented interpreter shutdown, wedging the hook. The exec is now torn down when the wait fails.
* **No more errors during finalisation on an already-closed Pebble websocket** (#2548). Closing a socket that is already closed is now a no-op, and the race where it closes underneath us is ignored. This was showing up as noisy tracebacks at interpreter shutdown on Python 3.13+.
* **Datetimes from Juju 4 parse correctly on Python 3.10** (#2264).
* **`credential-get` is recognised on Kubernetes** (#2307) and **action metadata reports `additional_properties` correctly** (#2250) on newer Juju, both of which otherwise caused spurious failures against Juju 4.
* **`ops.pebble.Client.pull` cleans up its temporary file if it errors** (#2087), rather than leaving it behind.
* **`ExecError.__str__` shows only the executable**, not the whole command line (#2336), so arguments that contain secrets do not end up in logs and status messages. *Please avoid putting secrets in `exec` calls.*
* **`breakpoint()` still works after `_Manager` teardown** (#2542): `sys.breakpointhook` is restored instead of being left patched.
* Type annotation corrections that may surface new (correct) errors in your type checker: `Model.get_binding()` (#2329) and `StorageMeta.properties` (#2348).

### Testing fixes worth knowing about

* **Relation data in tests is no longer shared with the mock backend** (#2052). Tests that relied on the old aliasing may now (correctly) see different data.
* **Remote units on relation events match Juju** (#1918, #1925): the remote unit is only added for `-departed` and `-broken` events, the ordering is fixed, and the departing unit appears in `Relation.data` but not in `Relation.units`.
* **Errors inside the `Context` context manager are no longer swallowed** (#2117, #2121): the manager is exited properly when an exception occurs, and `ActionFailed` is raised as it is outside the manager.
* **Mutable state you pass in is copied, not captured** (#2349, #2379, #2380): `Context` holds copies of user-provided meta, config and actions; `secret_get` and `action_get` return copies; and layers are deep-copied when rendering the plan. Previously a test could mutate the objects another test was about to use.
* **Resources and files are cleaned up** (#2506, #2507): `Context` releases its resources, and `Harness.cleanup()` closes the SQLite storage instead of leaking a file handle.
* **Consistency checking is less trigger-happy**: Pebble's defaults for check level, startup and threshold are taken into account (#2567), `_checks_action` returns an empty list rather than erroring when nothing changed (#2270), and `testing.CheckInfo`'s `level` argument accepts the same type as `pebble.CheckInfo.level` (#2274).
* **`Secret.owner` is normalised to `'app'`** in output state (#2127), and an event that ends with `_Abort(0)` is treated as a success (#1887).
* **Clearing a non-empty container now warns first** (#2365), and the `testing.Container` compatibility import moved so mypy-style checkers understand it (#2343).

### What's Changed

#### Fixes

* If an event ends with `_Abort(0)`, tests behave as if it ended successfully (#1887)
* Only add the remote unit for departed and broken relation events, and fix the ordering (#1918)
* Add the remote unit to `Relation.data` but not `Relation.units` (#1925)
* `_MockModelBackend.relation_get` returns a copy of the relation data (#2052)
* Ensure `ops.pebble.Client.pull` cleans up temporary files if it errors (#2087)
* Ensure that the testing context manager is exited when an exception occurs (#2117)
* Raise `ActionFailed` when using `Context` as a context manager (#2121)
* Normalise `Secret.owner` to `'app'` for `ops[testing]` output state (#2127)
* Correct the value of `additional_properties` in the action meta in Juju 4 (#2250)
* Use `parse_rfc3339` for datetime parsing to support Python 3.10 (#2264)
* `_checks_action` returns an empty list when there are no changes (#2270)
* Make `testing.CheckInfo` level argument type match `pebble.CheckInfo.level` (#2274)
* Support the Pydantic MISSING sentinel in `ops.Relation.save` (#2306)
* `credential-get` is available on Kubernetes in newer Juju (#2307)
* Correct the `Model.get_binding()` return type (#2329)
* Only show the executable in `ExecError.__str__`, not the full command line (#2336)
* Move the `testing.Container` compatibility import so that mypy-style checkers understand it (#2343)
* Correct the type annotation for `StorageMeta.properties` (#2348)
* Hold only copies of user provided dicts in `testing.Context` (#2349)
* Warn before clearing a non-empty container in testing (#2365)
* Use timezone-aware datetimes in expiry calculation (#2378)
* Return copies from Scenario `secret_get` and `action_get` (#2379)
* Deep-copy layer objects during Scenario plan rendering (#2380)
* Pass the endpoint name through to `relation-get` (#2499)
* Ensure resources are cleaned up in `testing.Context` (#2506)
* Close SQLite storage in `Harness.cleanup()` (#2507)
* Restore `sys.breakpointhook` on `_Manager` teardown (#2542)
* Avoid errors in finalisation due to an already-closed websocket (#2548)
* Don't leak exec I/O threads when waiting on the change fails (#2558)
* Drop the unused `importlib-metadata` dependency declaration (#2521)
* Take Pebble defaults into consideration when consistency checking `Check`s (#2567)
* Pin `pydantic` to 2-3 (#2583)

#### Documentation

* Move 2.x docs to canonical.com/juju/docs/ops (#2546)

#### CI

* Fix ops-tracing release for 2.23-maintenance (#2324)
* Test Ops 2.23 with Python 3.14 (#2576)


**Full Changelog**: https://github.com/canonical/operator/compare/2.23.2...2.23.4

## 3.8.1: assorted fixes to align with Juju more closely

This is a fixes-and-polish release, with most of the work in the state transition testing framework and the documentation.

In state transition testing, entity names are now validated the way Juju itself validates them, and simulated dispatch matches how real Juju invokes hooks, so a test can no longer pass against a charm that Juju would refuse to deploy. Note that tests using names that Juju would reject will now fail. Secret `grant` and `revoke` no longer try to mutate immutable state.

In `ops` itself, `Relation.load()` now only decodes the fields that your data class declares, so loading a unit databag into a dataclass or Pydantic model no longer trips over the values that Juju sets automatically, such as `egress-subnets` and `private-address`. The `access` field of `IdentityDict` accepts the `IdentityAccess` enum as well as the string literals.

On the documentation side, there is a new how-to guide for debugging Kubernetes charms, a new how-to for configuring Jubilant logs, expanded guidance on naming charms, and a series of improvements to the Kubernetes tutorial, including setting and testing the workload version and moving the demo server to a rock.

## What's Changed

### Fixes
* Align Juju naming rules with testing class rules in https://github.com/canonical/operator/pull/2570
* Drop unsupported cooldown.semver-major-days from github-actions block in https://github.com/canonical/operator/pull/2617
* Do not attempt to mutate secret data in grant/revoke during tests in https://github.com/canonical/operator/pull/2614
* Allow `IdentityDict` to be assigned `IdentityAccess` in https://github.com/canonical/operator/pull/2628
* Only decode fields used by the data class in Relation.load() in https://github.com/canonical/operator/pull/2636
* Use juju.wait for workload version tests in k8s tutorial in https://github.com/canonical/operator/pull/2650

### Documentation
* Wait longer for Loki data in K8s tutorial integration tests in https://github.com/canonical/operator/pull/2611
* Add more guidance about charm naming in https://github.com/canonical/operator/pull/2610
* Fix tempo test_deploy url in https://github.com/canonical/operator/pull/2631
* Add how-to guide for debugging Kubernetes charms in https://github.com/canonical/operator/pull/2498
* Revert to installed charmcraft for initing charms in https://github.com/canonical/operator/pull/2635
* Grab workload version in k8s tutorial in https://github.com/canonical/operator/pull/2559
* Separate test_workload_version_is_set in k8s tutorial chapter 3 in https://github.com/canonical/operator/pull/2638
* Add howto configure jubilant logs in https://github.com/canonical/operator/pull/2619
* Use autofunction for `layer_from_rockcraft` in https://github.com/canonical/operator/pull/2648
* Remove log_cli and log_file ini options; keep them as cli arguments for integration tests in https://github.com/canonical/operator/pull/2654
* Fix typo in explanation of mock_version fixture usage in https://github.com/canonical/operator/pull/2647
* Switch K8s tutorial charms to rock version of demo server in https://github.com/canonical/operator/pull/2649

### Tests
* Type-check testing/src/scenario and fix uncovered errors in https://github.com/canonical/operator/pull/2615

### CI
* Add dependency-review-action on PRs in https://github.com/canonical/operator/pull/2587
* Re-enable the tracing integration tests in https://github.com/canonical/operator/pull/2586
* Adopt new dependabot conventions in https://github.com/canonical/operator/pull/2609
* Open an issue if a scheduled workflow fails in https://github.com/canonical/operator/pull/2627
* Hash-pin actions and drop zizmor config in https://github.com/canonical/operator/pull/2612
* Use uv-venv-lock-runner in tracing tox, align deps in https://github.com/canonical/operator/pull/2651

**Full Changelog**: https://github.com/canonical/operator/compare/3.8.0...3.8.1

## 3.8.2: fix how duplicate events are identified

This release fixes a bug in deferred event handling. If an event `MyEmitter[foo]/evt1` was deferred, subsequent events `MyEmitter[foo]/evt2` and `MyEmitter[bar]/evt1` would be incorrectly identified as duplicate events, and then skipped. Thank you @Ali-932 for the fix!

## What's Changed

### Fixes
* Compare full event paths when skipping duplicate notices in https://github.com/canonical/operator/pull/2684
* In `ops.testing`, don't pass a message when converting an unknown status by name in https://github.com/canonical/operator/pull/2700

### Documentation
* Give each best-practice admonition a stable anchor in https://github.com/canonical/operator/pull/2524
* Reword text that vale 3.17 flags as misspelled in https://github.com/canonical/operator/pull/2695
* Stop styling page references as blockquotes in https://github.com/canonical/operator/pull/2666
* Make the custom-endpoint-name sample test actually test something in https://github.com/canonical/operator/pull/2664
* Replace `requests` by `urllib` in K8s tutorial integration tests in https://github.com/canonical/operator/pull/2687
* Recommend spread directly, rather than charmcraft test in https://github.com/canonical/operator/pull/2706
* Extract sections in "how to write integration tests" to their own how-to guide in https://github.com/canonical/operator/pull/2662

### CI
* Point DB charm CI at the moved mysql-operators repo in https://github.com/canonical/operator/pull/2551
* Switch example charm integration tests to Concierge `k8s` preset in https://github.com/canonical/operator/pull/2696
* Use the upstream concierge presets again in https://github.com/canonical/operator/pull/2699

**Full Changelog**: https://github.com/canonical/operator/compare/3.8.1...3.8.2
