(reference)=
# Reference

These guides provide technical information about Ops APIs.

## Core APIs

`ops.main` is the entry point to initialise and run your charm. `ops` is the API to respond to Juju events and manage the application.

```{toctree}
:maxdepth: 1

ops-main-entrypoint
ops
```

## Pebble

An API for interacting with {external+pebble:doc}`index`.

```{toctree}
:maxdepth: 1

pebble
```

## Testing

APIs for testing charms. `Harness` is deprecated. For guidance on how to upgrade, see [](#harness-migration).

```{toctree}
:maxdepth: 1

ops-testing
ops-testing-harness
```

## Tracing

An API for tracing charm code and sending data to sources such as the [Canonical Observability Stack](https://documentation.ubuntu.com/observability/).

```{toctree}
:maxdepth: 1

ops-tracing
```

## Hook commands

A low-level API for accessing the Juju hook commands. This API isn't intended for charms to use directly. It primarily supports alternatives to the Ops framework.

```{toctree}
:maxdepth: 1

ops-hookcmds
```
