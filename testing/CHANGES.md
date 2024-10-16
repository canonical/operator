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
