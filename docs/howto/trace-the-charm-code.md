(trace-the-charm-code)=
# Trace the charm code

`ops[tracing]` provides the first party charm tracing library,
`ops.tracing.Tracing`, allowing you to observe and instrument your charm's
execution using OpenTelemetry.

Refer to `ops.tracing` reference for the canonical usage example, ocnfiguration
options and API details.

This guide covers:
- Adding tracing to your charm
- Creating custom spans and events
- Adding tracing to charm libraries
- Migrating from the `charm_tracing` charm library
- How and when to use the lower-level API

## Getting started

To enable basic tracing:

- In your charm's `pyproject.toml` or `requirements.txt`, add `ops[tracing]` dependency
- In your `charmcraft.yaml`, declare the tracing and (optionally) ca relations
- In your charm class `__init__`, instantiate the `ops.tracing.Tracing(...)` object

At this point, the Ops library will be traced:
- The `ops.main()` call
- The events that the Ops library emits
- The hook tools called by the charm code
- The Pebble API access by the charm code

This provides coarse-grained tracing, focused on the boundaries between the
charm code and the external processes.

(custom-spans-and-events)=
## Custom spans and events

- In your charm's `pyproject.toml` or `requirements.txt`, add
  `opentelemetry-api ~= 1.30.0` dependency.
- At the top of your charm file, `import opentelemetry.trace`.
- After the imports in your charm file, create the tracer object as
  `tracer = opentelemetry.trace.get_tracer(name)` where the name
   could be your charm name, or Python module `__name__`.
- Around some important charm code, use
  `tracer.start_as_current_span(name)` to create a custom span.
- At some important point in the charm code, use
  `opentelemetry.trace.get_current_span().add_event(name, attributes)` to create
  a custom OpenTelemetry event.

Prefer using the OpenTelemetry `start_as_current_span` primitive as a context manager
over a decorator. While both are supported, the context manager is more ergonomic,
allows exposing the resulting span, and doesn't pollute exception stack traces.

## Adding tracing to charm libraries

- In your charm library's PYDEPS, add `opentelemetry-api ~= 1.30.0`.
- At the top of your charm library, `import opentelemetry.trace`.
- After the imports in your charm library, create the tracer object as
  `tracer = opentelemetry.trace.get_tracer(name)` where the name could be your
  charm library name, or Python module `__name__`.
- See the [Custom spans and events](custom-spans-and-events) section above to
  create OpenTelemetry spans and events in the key places in your charm library.

## Migrating from charm\_tracing charm library

- In your charm's `pyproject.toml` or `requirements.txt`, remove the dependencies:
  `opentelemetry-sdk`, `opentelemetry-proto`, `opentelemetry-exporter-*`,
  `opentelemetry-semantic-conventions` and add `ops[tracing]` instead.
- In your repository, remove the `charm_tracing` charm library.
- In your charm code, remove `@trace_charm` decorator and its helpers: the 
  `tracing_endpoint` and `server_cert` properties or methods.
- In your charm's `pyproject.toml` or `requirements.txt`, add `ops[tracing]` dependency
- In your `charmcraft.yaml`, take note of the tracing and (optionally) ca relation names.
- In your charm class `__init__`, instantiate the `ops.tracing.Tracing(...)` object

Note that the `charm_tracing` charm library auto-instruments all public functions
of the decorated charm class. `ops[tracing]` doesn't do that, and you are expected
to create custom spans and events using the OpenTelemetry API where that makes sense.

## Lower-level API

The `ops.tracing.Tracing` class assumes a straightforward setup: that the tracing data
is to be sent to a destination that's specified in the charm tracing relation databag.

For an example where that's not the case, consider the `tempo` component of the COS stack.
If it is deployed standalone, the tracing data should be sent to the current unit's workload.
And when it is deployed in a cluster, the tracing data should be sent to the load balancer.

For cases like this, a lower-level primitive, `ops.tracing.set_destination(url, ca)` is available.

The destination is persisted in the unit's tracing database, next to the tracing data.
Thus, a delta charm would only call this function when some relation or configuration
value is changed.

At the same time, calling this function with the same data is a no-op.
A reconciler charm may therefore safely call it unconditionally.

The `url` parameter must be the full endpoint URL, like `http://localhost/v1/traces`.

The `ca` parameter is optional, only used for HTTPS URLs, and should be a multi-line string
containing the CA list (a PEM bundle).
