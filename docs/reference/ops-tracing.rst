.. _ops_tracing:

`ops.tracing`
==============

.. automodule:: ops_tracing

Open Telemetry resource attributes
----------------------------------

- ``service.namespace`` the UUID of the Juju model.
- ``service.namespace.name`` the name of the Juju model.
- ``service.name`` the application name, like ``user_db``.
- ``service.instance.id`` the unit number, like ``0``.
- ``service.charm`` the charm class name, like ``DbCharm``.


Security considerations
-----------------------

The trace data can be sent out over HTTP or HTTPS. If your charm uses the
``ops.tracing.Tracing()`` object, the protocol is determined by the URL that
the charm tracing integration counterpart posts in the databag.

This release supports TLS 1.2 and 1.3 for HTTPS connections.

Tracing behaviour across test frameworks
----------------------------------------

**ops[testing]** (formerly Scenario) replaces the OpenTelemetry tracer provider
with a mocked version that keeps the emitted spans in memory. This data is not
presently exposed to the tests. See ``ops_tracing._mock.patch_tracing`` for
details.

**Harness** (legacy) is not affected. This framework does not have a Manager and
does not call ``ops.main()`` and therefore the tracing subsystem remains
uninitialised. It is still safe to create OpenTelemetry spans and events, as the
root span is a ``NonRecordingSpan`` in this case.
