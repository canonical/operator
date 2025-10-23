(explanation)=
# Explanation

These guides explain how Ops works.

## Interface definitions

The `charm-relation-interfaces` repository contains specifications, schemas, and tests for Juju interfaces.

```{toctree}
:maxdepth: 1

charm-relation-interfaces
```

## Testing

Your charm should have unit tests and integration tests. If your charm uses relations, it should also have interface tests.

```{toctree}
:maxdepth: 1

testing
```

## Tracing

Ops enables you to trace your charm code and send data to the [Canonical Observability Stack](https://documentation.ubuntu.com/observability/).

```{toctree}
:maxdepth: 1

tracing
```

## Handling events

Charms typically either handle events holistically, using a shared reconciler method, or individually.

```{toctree}
:maxdepth: 1

holistic-vs-delta-charms
```

## Deferring events

The `defer()` mechanism in Ops is convenient, but has some limitations.

```{toctree}
:maxdepth: 1

defer-guidance
```

## Security

As you write your charm, follow good security practices and produce security documentation for your charm.

```{toctree}
:maxdepth: 1

security
```

## Tracking state

Charms can track state in several ways, including using `ops.StoredState`. You should be judicious when deciding how to track state.

```{toctree}
:maxdepth: 1

storedstate-guidance
```

## State-transition testing

State-transition tests have replaced the older "Harness" framework for writing charm unit tests.

```{toctree}
:maxdepth: 1

state-transition-testing
```

## Charm maturity

Your charm should increase in maturity and quality over time, especially if you plan for it to be publicly listed on Charmhub.

```{toctree}
:maxdepth: 1

charm-maturity
```
