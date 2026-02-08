.. _ops_testing_harness:

`ops.testing.Harness` (legacy unit testing)
===========================================

.. deprecated:: 2.17
    The Harness framework is deprecated and will be moved out of the base
    install in a future ops release. Charm authors that don't want to upgrade
    will still be able to use it with ``pip install ops[harness]``.
    For guidance on how to upgrade, see :ref:`harness-migration`.

The Harness API includes:

- :class:`ops.testing.Harness`, a class to set up the simulated environment,
  that provides:

  - :meth:`~ops.testing.Harness.add_relation` method, to declare a relation
    (integration) with another app.
  - :meth:`~ops.testing.Harness.begin` and :meth:`~ops.testing.Harness.cleanup`
    methods to start and end the testing lifecycle.
  - :meth:`~ops.testing.Harness.evaluate_status` method, which aggregates the
    status of the charm after test interactions.
  - :attr:`~ops.testing.Harness.model` attribute, which exposes e.g. the
    :attr:`~ops.Model.unit` attribute for detailed assertions on the unit's state.

.. warning:: The Harness API has flaws with resetting the charm state between
    Juju events. Care must be taken when emitting multiple events with the same
    Harness object.

.. note::
    Unit testing is only one aspect of a comprehensive testing strategy. For more
    on testing charms, see :doc:`/explanation/testing`.


.. autoclass:: ops.testing.ActionFailed
   :noindex:
.. autoclass:: ops.testing.ActionOutput
.. autoclass:: ops.testing.ExecArgs
.. autoclass:: ops.testing.ExecResult
.. autoclass:: ops.testing.Harness
