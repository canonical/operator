API reference
=============

The `ops` library is a Python framework for writing and testing Juju charms.

  See more: `Charm SDK documentation <https://juju.is/docs/sdk>`_

The library (`available on PyPI`_) provides:

- :ref:`ops_module`, the API to respond to Juju events and manage the application;
- :ref:`ops_main_entry_point`, used to initialise and run your charm;
- :doc:`ops.pebble <_ops_pebble>`, the Pebble client, a low-level API for Kubernetes containers;
- the APIs for unit testing charms in a simulated environment:

  - :doc:`State-transition testing <_ops_testing>`. This is the
    recommended approach (it was previously known as 'Scenario').
  - :doc:`Harness <_ops_testing_harness>`. This is a deprecated framework, and has issues,
    particularly with resetting the charm state between Juju events.

You can structure your charm however you like, but with the `ops` library, you
get a framework that promotes consistency and readability by following best
practices. It also helps you organise your code better by separating different
aspects of the charm, such as managing the application's state, handling
integrations with other services, and making the charm easier to test.

.. _available on PyPI: https://pypi.org/project/ops/

.. toctree::
   :hidden:
   :maxdepth: 2

   self
   _ops_pebble
   _ops_testing
   _ops_testing_harness

.. _ops_module:

ops
---

.. automodule:: ops
   :exclude-members: main

.. _ops_main_entry_point:

ops.main entry point
--------------------

The main entry point to initialise and run your charm.

.. autofunction:: ops.main

legacy main module
------------------

.. automodule:: ops.main
   :noindex:


Indices
=======

* :ref:`genindex`
