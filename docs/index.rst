API reference
=============

The `ops` library is a Python framework for writing and testing Juju charms.

  See more: `Charm SDK documentation <https://juju.is/docs/sdk>`_

The library (`available on PyPI`_) provides:

- :ref:`ops_main_entry_point`, used to initialise and run your charm;
- :ref:`ops_module`, the API to respond to Juju events and manage the application;
- :ref:`ops_pebble_module`, the Pebble client, a low-level API for Kubernetes containers;
- :ref:`ops_testing_module` frameworks for unit testing charms in a simulated environment;

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
   state-transition-testing
   harness

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

.. _ops_pebble_module:

ops.pebble
----------

.. automodule:: ops.pebble

.. _ops_testing_module:

.. _ops_testing_module:

Testing
-------

Two frameworks for unit testing charms in a simulated Juju environment are
available:

* :doc:`State-transition testing </state-transition-testing>`, which tests the charm's state transitions in response
  to events. This is the recommended approach. Install ops with the ``testing``
  extra to use this framework; for example: ``pip install ops[testing]``
* :doc:`Harness </harness>`, which provides an API reminiscent of the Juju CLI. This is a
  deprecated framework, and has issues, particularly with resetting the charm
  state between Juju events. It will be moved out of the base ``ops`` install in
  a future release.


.. note::
    Unit testing is only one aspect of a comprehensive testing strategy. For more
    on testing charms, see `Charm SDK | Testing <https://juju.is/docs/sdk/testing>`_.


Indices
=======

* :ref:`genindex`
