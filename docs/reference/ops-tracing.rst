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
