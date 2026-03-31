# Migration guides

These guides help you migrate away from deprecated approaches to charming.

## Harness

Harness is a deprecated framework for writing unit tests. You should migrate to state-transition tests.

```{toctree}
:maxdepth: 1

Migrate unit tests from Harness <migrate-unit-tests-from-harness>
```

## pytest-operator

pytest-operator and python-libjuju are deprecated. You should migrate integration tests to Jubilant and pytest-jubilant.

```{toctree}
:maxdepth: 1

Migrate integration tests from pytest-operator <migrate-integration-tests-from-pytest-operator>
```

## Hooks-based charms

Hooks-based charms use script files instead of Python code with Ops. You should migrate to Ops.

```{toctree}
:maxdepth: 1

Migrate from a hooks-based charm <migrate-from-a-hooks-based-charm>
```
