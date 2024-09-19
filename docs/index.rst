
ops library API reference
=========================

The `ops` library is a Python framework for writing and testing Juju charms.

  See more: `Charm SDK documentation <https://juju.is/docs/sdk>`_

The library provides:

- :ref:`ops_main_entry_point`, used to initialise and run your charm;
- :ref:`ops_module`, the API to respond to Juju events and manage the application;
- :ref:`ops_pebble_module`, the Pebble client, a low-level API for Kubernetes containers;
- :ref:`ops_testing_module`, the framework for unit testing charms in a simulated environment;

You can structure your charm however you like, but with the `ops` library, you
get a framework that promotes consistency and readability by following best
practices. It also helps you organize your code better by separating different
aspects of the charm, such as managing the application’s state, handling
integrations with other services, and making the charm easier to test.


.. toctree::
   :maxdepth: 2
   :caption: Contents:


.. _ops_module:

ops module
==========

.. automodule:: ops
   :exclude-members: main


.. _ops_main_entry_point:

ops.main entry point
====================

The main entry point to initialise and run your charm.

.. autofunction:: ops.main


legacy main module
------------------

.. automodule:: ops.main
   :noindex:


.. _ops_pebble_module:

ops.pebble module
=================

.. automodule:: ops.pebble


.. _ops_testing_module:

ops.testing module
==================

.. automodule:: ops.testing


Indices
=======

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
