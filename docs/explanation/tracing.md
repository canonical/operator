(tracing)=
# Tracing
## Tracing users

Instrument generously, so that more context is captured than is immediately needed; this ensures that enough data is available for each role:

**Charm developers** get more visibility during local development: how Juju hooks and charm library processing is connected to the key code paths in their charms.

**Field engineers** can inspect the trace data from live deployments, ideally avoiding the need to reproduce failures in staging.

**SREs** may want to set latency and error rate alerts on specific elements of trace data preemptively. They can also get more insights to help root-cause analysis across services.

**QA teams** can incorporate trace assertions into integration tests to simplify interoperability testing.

At the same time, we do not recommend deriving **business metrics** from charm trace data, as the workload trace data should be the primary source instead.

## Relations

The recommended declaration is:

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

The traced charm must be the requirer in the relation. Trace data sinks, like Tempo, are the providers.

The `limit` attribute is validated at charm initialisation time, because the tracing infrastructure can only handle one destination at a time. Thus it doesn't make sense for the traced app to be related to multiple providers simultaneously.

The `optional` attribute is recommended, as it gives a hint that this charm can be deployed with or without tracing.

The `receive-ca-cert` relation is optional; it's only useful if your charm should be able to send trace data over HTTPS to another app in Juju.

For the `charm-tracing` relation, the supported `tracing` interface version is `v2`.

For the `receive-ca-cert` relation, the supported `certificate_transfer` interface version is `v1`.

## Storage

### Priority

An application is deployed and the charm tracing relation can only be established after that.
The trace data collected during this period may be important. The tracing backend stores up
to 40MB of trace data in a disk buffer and this data will be sent out when the relation is
established.

Dispatch is called and Python code is run on every Juju event, regardless of whether that event
is observed. Trace data collected from observed dispatches is given higher priority in the
buffer, reducing the risk that repetitive and/or uninteresting dispatches would flush the
important bits of trace data from the buffer.

This hopefully ensures that you can see the trace data for your "install" and "start" events.

Note that for for Kubernetes charms, if the container is recreated, any buffered traces will be lost.

### Data format

The data is stored and sent to the OpenTelemetry collector in the
[OLTP 1.5.0 JSON format](https://opentelemetry.io/docs/specs/otlp/)
(protobuf JSON representation with OTLP gotchas).

### Backwards and forwards compatibility

The ``ops==2.20.0`` is the first Ops library release that supports tracing.
