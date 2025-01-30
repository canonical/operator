# 7.1.1 - 30 Jan 2025

## Fixes

* require ops 2.18.0 or better as a hot-fix against accidentally introduced incompatibility (#1551)

# 7.1.0 - 30 Jan 2025

## Features

* Use :memory: as the unit state storage location for ops.testing (#1494)
* Make Context and Manager variadic types in testing by @Batalex (#1445)

## Fixes
* Require the same object to be in the testing state as in the event (#1468)
* Raise ModelError on unknown/error status set in Scenario (#1417)

## Documentation
* Use the right ops-scenario for building the docs (#1470)
* Clearly deprecate Harness in the testing how-tos (#1508)
* Fix Markdown syntax in ops.testing readme (#1502)

## Continuous Integration
* All the ops-scenario publish actions need to be done in testing/ (#1479)
* Correctly point PyPI publishing to the ops-scenario packages (#1514)

## Testing
* Add a small set of ops.testing benchmark tests (#1504)

## Refactoring
* Use ops._main._Manager in Scenario (#1491)
* Don't use the max-positional-args parent class for JujuLogLine (#1495)
* Cache signature structure in ops.testing state classes (#1499)
* Use _JujuContext in Scenario (#1459)
* Fix the testing src-layout structure and use relative imports (#1431)

# 7.0.5 - 20 Sep 2024

## Features

* Use a slightly more strict type for `AnyJson`

# 7.0.4 - 18 Sep 2024

## Chores

* Add a `py.typed` file

# 7.0.3 - 18 Sep 2024

## Fixes

* `ops.Model.get_relation` should not raise when a relation with the specified ID does not exist

# 7.0.2 - 13 Sep 2024

## Refactor

* Adjustments to handle the upcoming release of ops 2.17

# 7.0.1 - 9 Sep 2024

## Fixes

* Fix broken Python 3.8 compatibility.

# 7.0.0 - 9 Sep 2024

## Features

* Support for testing Pebble check events
* Container exec mocking can match against a command prefix
* Inspect a list of the commands that a charm has `exec`'d in a container
* Add consistency checks for `StoredState`
* Specifying your event is now done via `ctx.on` attributes
* The context manager is accessed via the `Context` object
* State collections are frozensets instead of lists
* Most classes now expect at least some arguments to be passed as keywords
* Secret tests are much simpler - particularly, revision numbers do not need to be managed
