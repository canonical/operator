import pytest
from ops.charm import (
    CharmBase,
    RelationChangedEvent,
    StartEvent,
    UpdateStatusEvent,
    WorkloadEvent,
)
from ops.framework import Framework, LifecycleEvent

from scenario import Context
from scenario.state import Container, Relation, State, _Event
from ..helpers import trigger

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
                if issubclass(evt.event_type, LifecycleEvent):
                    continue

                self.framework.observe(evt, self._on_event)

        def _on_event(self, event):
            self.captured.append(event)
            if self.defer_next > 0:
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
        State(deferred=[_Event("update_status").deferred(handler=mycharm._on_event)]),
        "start",
        mycharm,
        meta=mycharm.META,
    )

    # we deferred the first 2 events we saw: update-status, start.
    start, update_status = out.deferred
    assert start.name == "start"
    assert update_status.name == "update_status"

    # we saw start and update-status.
    upstat, start = mycharm.captured
    assert isinstance(upstat, UpdateStatusEvent)
    assert isinstance(start, StartEvent)


def test_deferred_relation_event(mycharm):
    mycharm.defer_next = 2

    rel = Relation(endpoint="foo", remote_app_name="remote")

    out = trigger(
        State(
            relations={rel},
            deferred=[
                _Event("foo_relation_changed", relation=rel).deferred(
                    handler=mycharm._on_event,
                )
            ],
        ),
        "start",
        mycharm,
        meta=mycharm.META,
    )

    # we deferred the first 2 events we saw: relation-changed, start.
    relation_changed, start = out.deferred
    assert relation_changed.name == "foo_relation_changed"
    assert start.name == "start"

    # we saw start and relation-changed.
    upstat, start = mycharm.captured
    assert isinstance(upstat, RelationChangedEvent)
    assert isinstance(start, StartEvent)


def test_deferred_relation_event_from_relation(mycharm):
    ctx = Context(mycharm, meta=mycharm.META)
    mycharm.defer_next = 2
    rel = Relation(endpoint="foo", remote_app_name="remote")
    out = trigger(
        State(
            relations={rel},
            deferred=[
                ctx.on.relation_changed(rel, remote_unit=1).deferred(
                    handler=mycharm._on_event
                )
            ],
        ),
        "start",
        mycharm,
        meta=mycharm.META,
    )

    # we deferred the first 2 events we saw: foo_relation_changed, start.
    relation_changed, start = out.deferred
    assert relation_changed.name == "foo_relation_changed"
    assert relation_changed.snapshot_data == {
        "relation_name": rel.endpoint,
        "relation_id": rel.id,
        "app_name": "remote",
        "unit_name": "remote/1",
    }
    assert start.name == "start"

    # we saw start and foo_relation_changed.
    upstat, start = mycharm.captured
    assert isinstance(upstat, RelationChangedEvent)
    assert isinstance(start, StartEvent)


def test_deferred_workload_event(mycharm):
    mycharm.defer_next = 2

    ctr = Container("foo")

    out = trigger(
        State(
            containers={ctr},
            deferred=[
                _Event("foo_pebble_ready", container=ctr).deferred(
                    handler=mycharm._on_event
                )
            ],
        ),
        "start",
        mycharm,
        meta=mycharm.META,
    )

    # we deferred the first 2 events we saw: foo_pebble_ready, start.
    pebble_ready, start = out.deferred
    assert pebble_ready.name == "foo_pebble_ready"
    assert start.name == "start"

    # we saw start and foo_pebble_ready.
    upstat, start = mycharm.captured
    assert isinstance(upstat, WorkloadEvent)
    assert isinstance(start, StartEvent)


def test_defer_reemit_lifecycle_event(mycharm):
    ctx = Context(mycharm, meta=mycharm.META, capture_deferred_events=True)

    mycharm.defer_next = 1
    state_1 = ctx.run(ctx.on.update_status(), State())

    mycharm.defer_next = 0
    state_2 = ctx.run(ctx.on.start(), state_1)

    assert [type(e).__name__ for e in ctx.emitted_events] == [
        "UpdateStatusEvent",
        "UpdateStatusEvent",
        "StartEvent",
    ]
    assert len(state_1.deferred) == 1
    assert not state_2.deferred


def test_defer_reemit_relation_event(mycharm):
    ctx = Context(mycharm, meta=mycharm.META, capture_deferred_events=True)

    rel = Relation("foo")
    mycharm.defer_next = 1
    state_1 = ctx.run(ctx.on.relation_created(rel), State(relations={rel}))

    mycharm.defer_next = 0
    state_2 = ctx.run(ctx.on.start(), state_1)

    assert [type(e).__name__ for e in ctx.emitted_events] == [
        "RelationCreatedEvent",
        "RelationCreatedEvent",
        "StartEvent",
    ]
    assert len(state_1.deferred) == 1
    assert not state_2.deferred
