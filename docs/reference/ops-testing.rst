.. _ops_testing:

`ops.testing` (was: Scenario)
=============================

Install ops with the ``testing`` extra to use this API; for example:
``pip install ops[testing]``

State-transition tests, previously known as 'Scenario', expect you to define the
Juju state all at once, define the Juju context against which to test the charm,
and fire a single event on the charm to execute its logic. The tests can then
assert that the Juju state has changed as expected.

A very simple test, where the charm has no config, no relations, the unit
is the leader, and has a `start` handler that sets the status to active might
look like this:

.. code-block:: python

    from ops import testing

    def test_base():
        ctx = testing.Context(MyCharm)
        state = testing.State(leader=True)
        out = ctx.run(ctx.on.start(), state)
        assert out.unit_status == testing.ActiveStatus()

These 'state-transition' tests give charm authors a way to test
how the state changes in reaction to events. They are not
necessarily tests of individual methods or functions;
they are testing the 'contract' of the charm: given
a certain state, when a certain event happens, the charm should transition to
another state. Unlike integration tests, they do not test using a real Juju
controller and model, and focus on a single Juju unit.
For simplicity, we refer to them as 'unit' tests.

Writing these tests should nudge you into thinking of a charm as a black-box
'input to output' function. The inputs are:

- Event: why am I, the charm, being executed
- State: am I the leader? what is my relation data? what is my config?
- Context: what relations can I have? what containers can I have?

The output is another `State`: the state after
the charm has interacted with the mocked Juju model.
The output state is the same type of data structure as the input state.

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
    - verify that the output state is what you expect it to be
    - verify that the charm has seen a certain sequence of statuses, events, and `juju-log` calls

.. note::
    Unit testing is only one aspect of a comprehensive testing strategy. For more
    on testing charms, see :doc:`/explanation/testing`.


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
