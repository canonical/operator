Tracing
=======

Some generic text.

Storage
-------

Some text about the buffver stored on disk, in which cases it may disappear.

K8s and VM concerns.

Data format
^^^^^^^^^^^

OLTP 1.5.0 JSON format (aka protobuf JSON representation with OTLP gotchas). A link to official docs.

Priority
^^^^^^^^

When a charm has just been deployed, the relation to the telemetry stack is not expected to exist yet.
The tracing data is buffered in a local file, because it may take arbitrary length of time before
it can be sent out. It's not unusual for buffer to become full and some data to be dropper dropped,
while waiting for the telemetry relation to be established.

To ensure that interesting data is kept, we mark dipatch invocations where the triggering Juju event
has at least one registered observer as "observed" and assign higher priority to tracing data collected
during these dispatches.

This hopefully ensures that you can see the tracing data for your "install" and "start" events.

Backwards and forwards compatibility
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The ``ops==2.20.0`` is the first Ops library release that supports tracing.

There's currently no backwards compatibility concern.

Forwards compatibility is based on a promise not to change the disk format,
or if it is changed, then providing a clear upgrade path as well as some
downgrade path. The downgrade path may involve erasing the buffered data,
based on the assumption that a working deployment sends tracing data out promptly.
