
ops library API reference
=========================

The `ops` library is a Python framework for writing and testing Juju charms.

It is the recommended way to write charms for both Kubernetes and machines.
The framework encapsulates the best charming practice and helps you write
consistent readable charms, reuse code via charm libs, and separate typical charm
concerns, such as application state management from integration management and
lifecycle management from testability.

- ``ops`` is the API to respond to Juju events and manage the application
  [units, relations, storage, secrets and resources].
- ``ops.pebble`` is the interface to control services and respond to their
  events in the workload container for Kubernetes charms.  
- ``ops.testing`` is the unit testing framework for your charm.

.. toctree::
   :maxdepth: 2
   :caption: Contents:

ops module
==========

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

.. automodule:: ops.pebble


ops.testing module
==================

.. automodule:: ops.testing


Indices
=======

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
