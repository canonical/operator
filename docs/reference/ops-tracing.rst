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
