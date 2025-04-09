Tracing
=======

Storage
-------

Priority
^^^^^^^^

An application is deployed and the charm tracing relation can only be established after that.
The trace data collected during this period may be important. The tracing backend stores up
to 40MB of trace data in a disk buffer and this data will be sent out when the relation is
established.

Dispatch is called and Python code is run on every Juju event, regardless of whether that event
is observed. Trace data collected from observed dispatches is given higher priority in the
buffer, reducing the risk that repetitive and/or uninteresting dispatches would flush the
important bits of trace data from the buffer.

This hopefully ensures that you can see the trace data for your "install" and "start" events.

Data format
^^^^^^^^^^^

The data is stored and sent to the OpenTelemetry collector in the [OLTP 1.5.0 JSON format]
(https://opentelemetry.io/docs/specs/otlp/) (aka protobuf JSON representation with OTLP gotchas).

Backwards and forwards compatibility
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The ``ops==2.20.0`` is the first Ops library release that supports tracing.
