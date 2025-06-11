(trace-the-charm-code)=
# Trace the charm code

`ops[tracing]` provides the first party charm tracing library,
`ops.tracing.Tracing`, allowing you to observe and instrument your charm's
execution using OpenTelemetry.

Refer to the {ref}`ops_tracing` reference for the canonical usage example, configuration
options, and API details.

## Getting started

To enable basic tracing:

- In `pyproject.toml` or `requirements.txt`, add `ops[tracing]` as a dependency
- In `charmcraft.yaml`, declare the tracing and (optionally) certificate_transfer relations, for example:

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
- Events that Ops emits, including all the Juju events
- Ops calls that inspect and update Juju (also called "hook tools")
- Pebble API access by the charm code

This provides coarse-grained tracing, focused on the boundaries between the
charm code and the external processes.

When you deploy your charm, until it is integrated with an app providing the `tracing` relation
(and optionally the `certificate_transfer` relation), the traces will be buffered in a tracing
database on the unit. When the charm is successfully integrated with the `tracing` provider,
the buffered traces and new traces will be sent to the tracing destination. For Kubernetes
charms, if the container is recreated, any buffered traces will be lost. Ops will buffer traces
for a reasonable period of time and amount of space.

For example, to send traces to [Grafana Tempo](https://grafana.com/docs/tempo/latest/) from
a charm named `my-charm`, assuming that
[Charmed Tempo HA](https://discourse.charmhub.io/t/charmed-tempo-ha/15531) has already been
deployed:

```bash
juju deploy my-charm
juju integrate my-charm tempo
```

(custom-spans-and-events)=
## Custom spans and events

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
        with tracer.start_as_current_span('migrate-db'):
            for attempt in range(3):
                try:
                    subprocess.run('/path/to/migrate.sh', capture_output=True, check=True)
                except subprocess.CalledProcessError:
                    opentelemetry.trace.get_current_span().add_event(
                        'db-migrate-failed',
                        {'attempt': attempt},
                    )
                    time.sleep(10 ** attempt)
                else:
                    break
            else:
                logger.error('Could not migrate the database')
            ...
```

## Adding tracing to charm libraries

- At the top of your charm library, `import opentelemetry.trace`.
- After the imports in your charm library, create the tracer object as
  `tracer = opentelemetry.trace.get_tracer(name)` where the name could be your
  charm library name, or Python module `__name__`.
- See the [Custom spans and events](custom-spans-and-events) section above to
  create OpenTelemetry spans and events in the key places in your charm library.

## Migrating from the charm\_tracing charm library

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
