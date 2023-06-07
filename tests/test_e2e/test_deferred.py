from dataclasses import asdict

import pytest
from ops.charm import (
    CharmBase,
    RelationChangedEvent,
    StartEvent,
    UpdateStatusEvent,
    WorkloadEvent,
)
from ops.framework import Framework

from scenario.state import Container, DeferredEvent, Relation, State, deferred
from tests.helpers import trigger

CHARM_CALLED = 0


@pytest.fixture(scope="function")
def mycharm():
    class MyCharm(CharmBase):
        META = {
            "name": "mycharm",
            "requires": {"foo": {"interface": "bar"}},
            "containers": {"foo": {"type": "oci-image"}},
        }
        defer_next = 0
        captured = []

        def __init__(self, framework: Framework):
            super().__init__(framework)
            for evt in self.on.events().values():
                self.framework.observe(evt, self._on_event)

        def _on_event(self, event):
            self.captured.append(event)
            if self.defer_next:
                self.defer_next -= 1
                return event.defer()

    return MyCharm


def test_defer(mycharm):
    mycharm.defer_next = True
    out = trigger(State(), "start", mycharm, meta=mycharm.META)
    assert len(out.deferred) == 1
    assert out.deferred[0].name == "start"


def test_deferred_evt_emitted(mycharm):
    mycharm.defer_next = 2

    out = trigger(
        State(deferred=[deferred(event="update_status", handler=mycharm._on_event)]),
        "start",
        mycharm,
        meta=mycharm.META,
    )

    # we deferred the first 2 events we saw: update-status, start.
    assert len(out.deferred) == 2
    assert out.deferred[0].name == "start"
    assert out.deferred[1].name == "update_status"

    # we saw start and update-status.
    assert len(mycharm.captured) == 2
    upstat, start = mycharm.captured
    assert isinstance(upstat, UpdateStatusEvent)
    assert isinstance(start, StartEvent)


def test_deferred_relation_event_without_relation_raises(mycharm):
    with pytest.raises(AttributeError):
        deferred(event="foo_relation_changed", handler=mycharm._on_event)


def test_deferred_relation_evt(mycharm):
    rel = Relation(endpoint="foo", remote_app_name="remote")
    evt1 = rel.changed_event.deferred(handler=mycharm._on_event)
    evt2 = deferred(
        event="foo_relation_changed",
        handler=mycharm._on_event,
        relation=rel,
    )

    assert asdict(evt2) == asdict(evt1)


def test_deferred_workload_evt(mycharm):
    ctr = Container("foo")
    evt1 = ctr.pebble_ready_event.deferred(handler=mycharm._on_event)
    evt2 = deferred(event="foo_pebble_ready", handler=mycharm._on_event, container=ctr)

    assert asdict(evt2) == asdict(evt1)


def test_deferred_relation_event(mycharm):
    mycharm.defer_next = 2

    rel = Relation(endpoint="foo", remote_app_name="remote")

    out = trigger(
        State(
            relations=[rel],
            deferred=[
                deferred(
                    event="foo_relation_changed",
                    handler=mycharm._on_event,
                    relation=rel,
                )
            ],
        ),
        "start",
        mycharm,
        meta=mycharm.META,
    )

    # we deferred the first 2 events we saw: relation-changed, start.
    assert len(out.deferred) == 2
    assert out.deferred[0].name == "foo_relation_changed"
    assert out.deferred[1].name == "start"

    # we saw start and relation-changed.
    assert len(mycharm.captured) == 2
    upstat, start = mycharm.captured
    assert isinstance(upstat, RelationChangedEvent)
    assert isinstance(start, StartEvent)


def test_deferred_relation_event_from_relation(mycharm):
    mycharm.defer_next = 2
    rel = Relation(endpoint="foo", remote_app_name="remote")
    out = trigger(
        State(
            relations=[rel],
            deferred=[rel.changed_event.deferred(handler=mycharm._on_event)],
        ),
        "start",
        mycharm,
        meta=mycharm.META,
    )

    # we deferred the first 2 events we saw: foo_relation_changed, start.
    assert len(out.deferred) == 2
    assert out.deferred[0].name == "foo_relation_changed"
    assert out.deferred[1].name == "start"

    # we saw start and foo_relation_changed.
    assert len(mycharm.captured) == 2
    upstat, start = mycharm.captured
    assert isinstance(upstat, RelationChangedEvent)
    assert isinstance(start, StartEvent)


def test_deferred_workload_event(mycharm):
    mycharm.defer_next = 2

    ctr = Container("foo")

    out = trigger(
        State(
            containers=[ctr],
            deferred=[ctr.pebble_ready_event.deferred(handler=mycharm._on_event)],
        ),
        "start",
        mycharm,
        meta=mycharm.META,
    )

    # we deferred the first 2 events we saw: foo_pebble_ready, start.
    assert len(out.deferred) == 2
    assert out.deferred[0].name == "foo_pebble_ready"
    assert out.deferred[1].name == "start"

    # we saw start and foo_pebble_ready.
    assert len(mycharm.captured) == 2
    upstat, start = mycharm.captured
    assert isinstance(upstat, WorkloadEvent)
    assert isinstance(start, StartEvent)
