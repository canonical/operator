
ops library API reference
=========================

The `ops` library is a Python framework for writing and testing Juju charms.

  See more: `Charm SDK documentation <https://juju.is/docs/sdk>`_

The library provides:

- :ref:`ops_main_entry_point` used to initialise and run your charm.
- :ref:`ops_module`, the API to respond to Juju events and manage the application.
- :ref:`ops_pebble_module` low-level API for Pebble in Kubernetes containers.
- :ref:`ops_testing_module`, the framework for unit testing charms in a simulated environment.

You can write a charm in any way you want, but with the `ops` library you get a
framework that helps you write consistent readable charms following the latest
best practices, reuse code via charm libs, and separate typical charm concerns
--- application state management from integration management or lifecycle
management from testability.

Whether you are a machine or a Kubernetes charm author, `ops` is the recommended way to go.


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
