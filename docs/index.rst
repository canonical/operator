
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
practices. It also helps you organise your code better by separating different
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

Frameworks for unit testing charms in a simulated Juju environment.

Two frameworks are available:

* State-transition testing, which tests the charm's state transitions in response
  to events. This is the recommended approach. Install ops with the ``testing``
  extra to use this framework; for example: ``pip install ops[testing]``
* Harness, which provides an API similar to the Juju CLI. This is a deprecated
  framework, and has issues, particularly with resetting the charm state between
  Juju events. It will be moved out of the base ``ops`` install in a future
  release.

.. note::
    Unit testing is only one aspect of a comprehensive testing strategy. For more
    on testing charms, see `Charm SDK | Testing <https://juju.is/docs/sdk/testing>`_.

State-transition testing
------------------------

State-transition tests expect you to define the Juju state all at once, define
the Juju context against which to test the charm, and fire a single event on the
charm to execute its logic. The tests can then assert that the Juju state has
changed as expected.

A very simple test, where the charm has no config, no integrations, the unit
is the leader, and has a `start` handler that sets the status to active might
look like this:

.. code-block:: python

   from ops import testing

    def test_base():
        ctx = testing.Context(MyCharm)
        state = testing.State(leader=True)
        out = ctx.run(ctx.on.start(), state)
        assert out.unit_status == testing.ActiveStatus()

These tests are 'state-transition' tests, a way to test isolated units of charm
functionality (how the state changes in reaction to events). They are not
necessarily tests of individual methods or functions (but might be, depending on
the charm's event observers); they are testing the 'contract' of the charm: given
a certain state, when a certain event happens, the charm should transition to a
certain (likely different) state. They do not test against a real Juju
controller and model, and focus on a single Juju unit, unlike integration tests.
For simplicity, we refer to them as 'unit' tests in the charm context.

Writing these tests should nudge you into thinking of a charm as a black-box
input->output function. The input is the union of an `Event` (why am I, charm,
being executed), a `State` (am I leader? what is my integration data? what is my
config?...) and the charm's execution `Context` (what integrations can I have?
what containers can I have?...). The output is another `State`: the state after
the charm has had a chance to interact with the mocked Juju model and affect the
state.

.. image:: https://raw.githubusercontent.com/canonical/ops-scenario/main/resources/state-transition-model.png
   :alt: Transition diagram, with the input state and event on the left, the context including the charm in the centre, and the state out on the right

Writing unit tests for a charm, then, means verifying that:

- the output state (as compared with the input state) is as expected
- the charm does not raise uncaught exceptions while handling the event

A test consists of three broad steps:

- **Arrange**:
    - declare the context
    - declare the input state
- **Act**:
    - run an event (ie. obtain the output state, given the input state and the event)
- **Assert**:
    - verify that the output state (as compared with the input state) is how you expect it to be
    - verify that the charm has seen a certain sequence of statuses, events, and `juju-log` calls

..
   _The list here is manually maintained, because the `automodule` directive
   expects to document names defined in the module, and not imported ones, and
   we're doing the opposite of that - and we also want to use the 'ops.testing'
   namespace, not expose the 'ops._private.harness' and 'scenario' ones.
   Ideally, someone will figure out a nicer way to do this that doesn't require
   keeping this list in sync (see test/test_infra.py for a check that we are ok).

.. autoclass:: ops.testing.ActionFailed
.. autoclass:: ops.testing.ActiveStatus
.. autoclass:: ops.testing.Address
.. autoclass:: ops.testing.BindAddress
.. autoclass:: ops.testing.BlockedStatus
.. autoclass:: ops.testing.CharmEvents
.. autoclass:: ops.testing.CheckInfo
.. autoclass:: ops.testing.CloudCredential
.. autoclass:: ops.testing.CloudSpec
.. autoclass:: ops.testing.Container
.. autoclass:: ops.testing.Context
   :special-members: __call__
.. autoclass:: ops.testing.DeferredEvent
.. autoclass:: ops.testing.ErrorStatus
.. autoclass:: ops.testing.Exec
.. autoclass:: ops.testing.ICMPPort
.. autoclass:: ops.testing.JujuLogLine
.. autoclass:: ops.testing.MaintenanceStatus
.. autoclass:: ops.testing.Manager
.. autoclass:: ops.testing.Model
.. autoclass:: ops.testing.Mount
.. autoclass:: ops.testing.Network
.. autoclass:: ops.testing.Notice
.. autoclass:: ops.testing.PeerRelation
.. autoclass:: ops.testing.Port
.. autoclass:: ops.testing.Relation
.. autoclass:: ops.testing.RelationBase
.. autoclass:: ops.testing.Resource
.. autoclass:: ops.testing.Secret
.. autoclass:: ops.testing.State
.. autoclass:: ops.testing.Storage
.. autoclass:: ops.testing.StoredState
.. autoclass:: ops.testing.SubordinateRelation
.. autoclass:: ops.testing.TCPPort
.. autoclass:: ops.testing.UDPPort
.. autoclass:: ops.testing.UnknownStatus
.. autoclass:: ops.testing.WaitingStatus
.. autoclass:: ops.testing.errors.ContextSetupError
.. autoclass:: ops.testing.errors.AlreadyEmittedError
.. autoclass:: ops.testing.errors.ScenarioRuntimeError
.. autoclass:: ops.testing.errors.UncaughtCharmError
.. autoclass:: ops.testing.errors.InconsistentScenarioError
.. autoclass:: ops.testing.errors.StateValidationError
.. autoclass:: ops.testing.errors.MetadataNotFoundError
.. autoclass:: ops.testing.errors.ActionMissingFromContextError
.. autoclass:: ops.testing.errors.NoObserverError
.. autoclass:: ops.testing.errors.BadOwnerPath

Harness
-------

The Harness framework is deprecated and will be moved out of the base install in
a future ops release. The Harness framework includes:

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

.. autoclass:: ops.testing.ActionFailed
   :noindex:
.. autoclass:: ops.testing.ActionOutput
.. autoclass:: ops.testing.ExecArgs
.. autoclass:: ops.testing.ExecResult
.. autoclass:: ops.testing.Harness


Indices
=======

* :ref:`genindex`
