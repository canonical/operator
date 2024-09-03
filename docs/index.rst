
ops library API reference
=========================

The `ops` library is a Python framework for writing and testing Juju charms.
It is the recommended way to write charms for both Kubernetes and machines.

The `ops` library provides powerful constructs for charm developers: FIXME fixme fixme the ops library provides structure that makes blah blah easier to reason.
Easier to write charms, read other charms, and reuse aspects like individual integration handling via charm libs.

- ``ops`` offers the API to respond to Juju events and manage application units, relations, storage, secrets and resources.

- **Interact with Juju**: `ops` offers the API to respond to Juju events
  and manage application units, relations, storage, secrets and resources.
- **Manage workloads**: For Kubernetes charms, `ops.pebble`
  provides an interface to control services inside the workload containers.
- **Write unit tests**: `ops.testing` is the unit testing framework for
  your charm.

.. toctree::
   :maxdepth: 2
   :caption: Contents:

ops module
==========

Provides APIs for managing the given Juju application, focusing on:

- Lifecycle
- State management and event response
- Handling of units, relations, and resources

Here’s a simple charm example using the `ops` library:

.. code-block:: python

    #!/usr/bin/env python3
    import ops


    class FastAPIDemoCharm(ops.CharmBase):
        """Charm the service."""

        def __init__(self, framework):
            super().__init__(framework)
            # let's try to on.started...
            self.framework.observe(self.on.demo_server_pebble_ready, self._on_demo_server_pebble_ready)

        def _on_demo_server_pebble_ready(self, event):
            event.workload.container.add_layer(...)
            event.workload.container.replan()
            self.unit.status = ops.ActiveStatus()


    if __name__ == "__main__":  # pragma: nocover
        ops.main(FastAPIDemoCharm)


.. automodule:: ops
   :exclude-members: main


ops.main entry point
====================
.. autofunction:: ops.main


legacy main module
------------------

.. automodule:: ops.main
   :noindex:


ops.pebble module
=================

An example of configuring workload container using pebble.

.. code-block:: python

        def _on_demo_server_pebble_ready(self, event):
            event.workload.container.add_layer(self._pebble_layer())
            event.workload.container.replan()
            self.unit.status = ops.ActiveStatus()

        def _pebble_layer(self) -> ops.pebble.Layer:
            return ops.pebble.Layer({
                "services": {
                    "demo_service": {
                        "override": "replace",
                        "startup": "enabled",
                        "command": ["/some/command", "--some-arg"],
                        "environment": {
                            "SOME_ENV_VAR": "some value",
                        },
                        # Let the container die if things go wrong
                        "on-success": "shutdown",
                        "on-failure": "shutdown",
                        "on-check-failure": {
                            "online": "shutdown"
                        }
                    }
                },
                "checks": {
                    # A custom check called "online"
                    "online": {
                        "override": "replace",
                        "exec": {
                            "command": ["/another/command", "--another-arg"],
                        },
                        "period": "3s"
                    }
                },
            })

.. automodule:: ops.pebble


ops.testing module
==================

Framework for unit testing charms in a simulated environment, enabling:

- Testing against mocked Juju events and states
- Validation of charm behavior prior to live deployment

An example testing a charm using the Harness framework.

.. code-block:: python

    @pytest.fixture
    def harness():
        harness = ops.testing.Harness(FastAPIDemoCharm)
        harness.begin()
        yield harness
        harness.cleanup()


    def test_pebble_ready(harness):
        assert harness.model.unit.status == ops.MaintenanceStatus("")

        harness.container_pebble_ready("demo_server")
        assert harness.model.unit.status == ops.ActiveStatus()

.. automodule:: ops.testing


Indices
=======

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
