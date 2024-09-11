
ops library API reference
=========================

The `ops` library is a Python framework for writing and testing Juju charms.

It is the recommended way to write charms for both Kubernetes and machines.
The framework encapsulates the best charming practice and helps you write
consistent readable charms, reuse code via charm libs, and separate typical charm
concerns, such as application state management from integration management and
lifecycle management from testability.

- :ref:`ops_main_entry_point` used to initialise and run your charm.
- :ref:`ops_module`, the API to respond to Juju events and manage the application.
- :ref:`ops_pebble_module` to control services and respond to their events for Kubernetes charms.  
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
