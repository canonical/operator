#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm state-transition testing SDK for Ops charms.

Write tests that declaratively define the Juju state all at once, define the
Juju context against which to test the charm, and fire a single event on the
charm to execute its logic. The tests can then assert that the Juju state has
changed as expected.

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

- the charm does not raise uncaught exceptions while handling the event
- the output state (as compared with the input state) is as expected.

A test consists of three broad steps:

- **Arrange**:
    - declare the context
    - declare the input state
- **Act**:
    - select an event to fire
    - run the context (i.e. obtain the output state, given the input state and the event)
- **Assert**:
    - verify that the output state (as compared with the input state) is how you expect it to be
    - verify that the charm has seen a certain sequence of statuses, events, and `juju-log` calls
    - optionally, you can use a context manager to get a hold of the charm instance and run
      assertions on APIs and state internal to it.

The most basic scenario is one in which all is defaulted and barely any data is
available. The charm has no config, no integrations, no leadership, and its
status is `unknown`. With that, we can write the simplest possible test:

.. code-block:: python

    def test_base():
        ctx = Context(MyCharm)
        out = ctx.run(ctx.on.start(), State())
        assert out.unit_status == UnknownStatus()
"""

from ops._private.harness import ActionFailed  # For backwards compatibility.

from .context import CharmEvents, Context, Manager
from .errors import StateValidationError  # For backwards compatibility.
from .state import (
    ActiveStatus,
    Address,
    AnyJson,
    BindAddress,
    BlockedStatus,
    CharmType,
    CheckInfo,
    CloudCredential,
    CloudSpec,
    Container,
    DeferredEvent,
    ErrorStatus,
    Exec,
    ICMPPort,
    JujuLogLine,
    MaintenanceStatus,
    Model,
    Mount,
    Network,
    Notice,
    PeerRelation,
    Port,
    RawDataBagContents,
    RawSecretRevisionContents,
    Relation,
    RelationBase,
    Resource,
    Secret,
    State,
    Storage,
    StoredState,
    SubordinateRelation,
    TCPPort,
    UDPPort,
    UnitID,
    UnknownStatus,
    WaitingStatus,
)

__all__ = [
    "ActionFailed",
    "ActiveStatus",
    "Address",
    "AnyJson",
    "BindAddress",
    "BlockedStatus",
    "CharmEvents",
    "CharmType",
    "CheckInfo",
    "CloudCredential",
    "CloudSpec",
    "Container",
    "Context",
    "DeferredEvent",
    "ErrorStatus",
    "Exec",
    "ICMPPort",
    "JujuLogLine",
    "MaintenanceStatus",
    "Manager",
    "Model",
    "Mount",
    "Network",
    "Notice",
    "PeerRelation",
    "Port",
    "RawDataBagContents",
    "RawSecretRevisionContents",
    "Relation",
    "RelationBase",
    "Resource",
    "Secret",
    "State",
    "StateValidationError",
    "Storage",
    "StoredState",
    "SubordinateRelation",
    "TCPPort",
    "UDPPort",
    "UnitID",
    "UnknownStatus",
    "WaitingStatus",
]
