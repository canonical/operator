(trace-your-charm)=
# How to trace your charm

This document describes how to trace your charm code and send the trace data to the [Canonical Observability Stack](https://documentation.ubuntu.com/observability/).

Observability transforms a Juju deployment from a black box to a real-time system. Trace data is structured and contextual, which helps users understand the application's behaviour at different points in your charm's lifecycle.

The responsibility to instrument the Python code is divided between Ops, charm libraries, and charms.

> See also: [](#tracing)

## Summary

To start instrumenting your charm code, you'll instantiate `ops.tracing.Tracing` in the charm's `__init__` method and provide it with relation names. Depending on the charm, you might also need to instrument: workflow decisions, external calls, and important attributes.

Ops provides instrumentation for general functionality, while libraries may also provide instrumentation. To find out what a library provides, check the library's documentation.

## Add tracing to an existing charm

### Enable built-in tracing

- In `pyproject.toml` or `requirements.txt`, add `ops[tracing]` as a dependency
- In `charmcraft.yaml`, declare the relations for `tracing` and (optionally) `certificate_transfer` interfaces, for example:

```yaml
requires:
  charm-tracing:
    interface: tracing
    limit: 1
    optional: true
  receive-ca-cert:
    interface: certificate_transfer
    limit: 1
    optional: true
```

- In your charm's `__init__` method, instantiate the `ops.tracing.Tracing` object, for example:

```python
class MyCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self.tracing = ops.tracing.Tracing(
            self,
            tracing_relation_name='charm-tracing',
            ca_relation_name='receive-ca-cert',
        )
        ...
```

At this point, Ops will trace:
- The `ops.main()` call
- Observer invocations for the Juju event
- Observer invocations for custom and life-cycle events
- Ops calls that inspect and update Juju (also called "hook commands")
- Pebble API access

This provides coarse-grained tracing, focused on the boundaries between the
charm code and the external processes.

When you deploy your charm, until it is integrated with an app providing the `tracing` relation
(and optionally the `certificate_transfer` relation), the traces will be buffered in a tracing
database on the unit. Ops allocates a reasonable amount of storage for the buffered traces.

When the charm is successfully integrated with the `tracing` provider,
the buffered traces and new traces will be sent to the tracing destination.

### Try it out

For example, to send traces to [Grafana Tempo](https://charmhub.io/topics/charmed-tempo-ha) from
a charm named `my-charm`, assuming that Charmed Tempo HA has already been deployed:

```bash
juju deploy my-charm
juju integrate my-charm tempo
```

At this point, trace data is sent to Tempo, and you can view it in Grafana, assuming that this Tempo instance is [added as a data source](https://grafana.com/docs/grafana/latest/datasources/tempo/configure-tempo-data-source/).

(custom-spans-and-events)=
### Add custom instrumentation

- At the top of your charm file, `import opentelemetry.trace`.
- After the imports in your charm file, create the tracer object as
  `tracer = opentelemetry.trace.get_tracer(name)` where the name
   could be your charm name, or Python module `__name__`.
- Around some important charm code, use
  `tracer.start_as_current_span(name)` to create a custom span.
- At some important point in the charm code, use
  `opentelemetry.trace.get_current_span().add_event(name, attributes)` to create
  a custom OpenTelemetry event.

```{tip}
Prefer using the OpenTelemetry `start_as_current_span` primitive as a context manager
over a decorator. While both are supported, the context manager is more ergonomic,
allows exposing the resulting span, and doesn't pollute exception stack traces.
```

For example, to add a custom span for the `migrate_db` method in this workload module,
with an event for each retry:

```python
import opentelemetry.trace

tracer = opentelemetry.trace.get_tracer(__name__)

class Workload:
    ...
    def migrate_db(self):
        with tracer.start_as_current_span('migrate-db') as span:
            for attempt in range(3):
                try:
                    subprocess.check_output('/path/to/migrate.sh')
                except subprocess.CalledProcessError:
                    span.add_event('db-migrate-failed', {'attempt': attempt})
                    time.sleep(10 ** attempt)
                else:
                    break
            else:
                logger.error('Could not migrate the database')
            ...
```

Refer to the {ref}`ops_tracing` reference for the canonical usage example, configuration
options, and API details.

### Migrate from the charm_tracing library

- In your charm's `pyproject.toml` or `requirements.txt`, remove the dependencies:
  `opentelemetry-sdk`, `opentelemetry-proto`, `opentelemetry-exporter-*`,
  `opentelemetry-semantic-conventions` and add `ops[tracing]` instead.
- In your repository, remove the `charm_tracing` charm library.
- In your charm code, remove the `@trace_charm` decorator and its helpers: the
  `tracing_endpoint` and `server_cert` properties or methods.
- In your `charmcraft.yaml`, take note of the tracing and (optionally) ca relation names.
- In your charm's `__init__` method, instantiate the `ops.tracing.Tracing` object,
  using the relation names from the previous step

Note that the `charm_tracing` charm library auto-instruments all public functions
of the decorated charm class. `ops[tracing]` doesn't do that, and you are expected
to create custom spans and events using the OpenTelemetry API where that makes sense.

## Test the feature

### Write unit tests

If you've added custom instrumentation, it is because something important is recorded.
Let's validate that in a unit test.

The [`trace_data`](ops.testing.Context.trace_data) attribute
of the [](ops.testing.Context) class of the testing framework
contains the list of finished spans.

The following example demonstrates how to get the root span, created by Ops itself.

```py
ctx = Context(YourCharm)
ctx.run(ctx.on.start(), State())
main_span = next(s for s in ctx.trace_data if s.name == 'ops.main')
```

The spans are OpenTelemetry objects in memory, allowing more focused examination; here is a check that span A is a parent of span B.

```py
span_a = ...
span_b = ...
assert span_a.context is span_b.parent
```

Or that span A is an ancestor of span C, which allows you to validate that an important logical thing C was done during some well-known process A: an Ops event representing the Juju event or a custom event, or some manually instrumented function.

```py
spans_by_id = {s.context.span_id: s for s in ctx.trace_data}

def ancestors(span: ReadableSpan) -> Generator[ReadableSpan]:
    while span.parent:
        span = spans_by_id[span.parent.span_id]
        yield span

assert span_a in list(ancestors(span_c))
```

You can disambiguate spans using their [`instrumentation_scope`](opentelemetry.sdk.util.instrumentation.InstrumentationScope) property.

```py
# Spans from Ops
ops_span.instrumentation_scope.name == "ops"
ops_span.name == ...

# tracer = opentelemetry.trace.get_tracer("my-charm")
my_span.instrumentation_scope.name == "my-charm"
my_span.name == ...
```

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

At the same time, calling this function with the same arguments is a no-op.
A charm that follows the reconciler pattern may therefore safely call it unconditionally.

The `url` parameter must be the full endpoint URL, like `http://localhost/v1/traces`.

The `ca` parameter is optional, only used for HTTPS URLs, and should be a multi-line string
containing the CA list (a PEM bundle).
