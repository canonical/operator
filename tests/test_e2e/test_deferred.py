from dataclasses import asdict

import pytest
from ops.charm import (
    CharmBase,
    CollectStatusEvent,
    RelationChangedEvent,
    StartEvent,
    UpdateStatusEvent,
    WorkloadEvent,
)
from ops.framework import Framework

from scenario import Context
from scenario.state import Container, DeferredEvent, Notice, Relation, State, deferred
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
    assert len(mycharm.captured) == 3
    upstat, start, _ = mycharm.captured
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


def test_deferred_notice_evt(mycharm):
    notice = Notice(key="example.com/bar")
    ctr = Container("foo", notices=[notice])
    evt1 = ctr.get_notice("example.com/bar").event.deferred(handler=mycharm._on_event)
    evt2 = deferred(
        event="foo_pebble_custom_notice",
        handler=mycharm._on_event,
        container=ctr,
        notice=notice,
    )

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
    assert len(mycharm.captured) == 3
    upstat, start, _ = mycharm.captured
    assert isinstance(upstat, RelationChangedEvent)
    assert isinstance(start, StartEvent)


def test_deferred_relation_event_from_relation(mycharm):
    mycharm.defer_next = 2
    rel = Relation(endpoint="foo", remote_app_name="remote")
    out = trigger(
        State(
            relations=[rel],
            deferred=[
                rel.changed_event(remote_unit_id=1).deferred(handler=mycharm._on_event)
            ],
        ),
        "start",
        mycharm,
        meta=mycharm.META,
    )

    # we deferred the first 2 events we saw: foo_relation_changed, start.
    assert len(out.deferred) == 2
    assert out.deferred[0].name == "foo_relation_changed"
    assert out.deferred[0].snapshot_data == {
        "relation_name": rel.endpoint,
        "relation_id": rel.relation_id,
        "app_name": "remote",
        "unit_name": "remote/1",
    }
    assert out.deferred[1].name == "start"

    # we saw start and foo_relation_changed.
    assert len(mycharm.captured) == 3
    upstat, start, collect_status = mycharm.captured
    assert isinstance(upstat, RelationChangedEvent)
    assert isinstance(start, StartEvent)
    assert isinstance(collect_status, CollectStatusEvent)


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
    assert len(mycharm.captured) == 3
    upstat, start, collect_status = mycharm.captured
    assert isinstance(upstat, WorkloadEvent)
    assert isinstance(start, StartEvent)
    assert isinstance(collect_status, CollectStatusEvent)


def test_defer_reemit_lifecycle_event(mycharm):
    ctx = Context(mycharm, meta=mycharm.META, capture_deferred_events=True)

    mycharm.defer_next = 1
    state_1 = ctx.run("update-status", State())

    mycharm.defer_next = 0
    state_2 = ctx.run("start", state_1)

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
    state_1 = ctx.run(rel.created_event, State(relations=[rel]))

    mycharm.defer_next = 0
    state_2 = ctx.run("start", state_1)

    assert [type(e).__name__ for e in ctx.emitted_events] == [
        "RelationCreatedEvent",
        "RelationCreatedEvent",
        "StartEvent",
    ]
    assert len(state_1.deferred) == 1
    assert not state_2.deferred
