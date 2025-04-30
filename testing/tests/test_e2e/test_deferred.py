from __future__ import annotations

import logging
import typing

import ops
import pytest
from ops.framework import LifecycleEvent

from scenario import Context
from scenario.state import Container, Relation, State, _Event
from ..helpers import trigger

CHARM_CALLED = 0


@pytest.fixture(scope='function')
def mycharm():
    class MyCharm(ops.CharmBase):
        META: dict[str, typing.Any] = {
            'name': 'mycharm',
            'requires': {'foo': {'interface': 'bar'}},
            'containers': {'foo': {'type': 'oci-image'}},
        }
        defer_next = 0
        captured: list[ops.EventBase] = []

        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            for evt in self.on.events().values():
                if issubclass(evt.event_type, LifecycleEvent):
                    continue

                self.framework.observe(evt, self._on_event)

        def _on_event(self, event: ops.EventBase):
            self.captured.append(event)
            if self.defer_next > 0:
                self.defer_next -= 1
                event.defer()

    return MyCharm


def test_defer(mycharm):
    mycharm.defer_next = True
    out = trigger(State(), 'start', mycharm, meta=mycharm.META)
    assert len(out.deferred) == 1
    assert out.deferred[0].name == 'start'


def test_deferred_evt_emitted(mycharm):
    mycharm.defer_next = 2

    out = trigger(
        State(deferred=[_Event('update_status').deferred(handler=mycharm._on_event)]),
        'start',
        mycharm,
        meta=mycharm.META,
    )

    # we deferred the first 2 events we saw: update-status, start.
    start, update_status = out.deferred
    assert start.name == 'start'
    assert update_status.name == 'update_status'

    # we saw start and update-status.
    upstat, start = mycharm.captured
    assert isinstance(upstat, ops.UpdateStatusEvent)
    assert isinstance(start, ops.StartEvent)


def test_deferred_relation_event(mycharm):
    mycharm.defer_next = 2

    rel = Relation(endpoint='foo', remote_app_name='remote')

    out = trigger(
        State(
            relations={rel},
            deferred=[
                _Event('foo_relation_changed', relation=rel).deferred(
                    handler=mycharm._on_event,
                )
            ],
        ),
        'start',
        mycharm,
        meta=mycharm.META,
    )

    # we deferred the first 2 events we saw: relation-changed, start.
    relation_changed, start = out.deferred
    assert relation_changed.name == 'foo_relation_changed'
    assert start.name == 'start'

    # we saw start and relation-changed.
    relation_changed, start = mycharm.captured
    assert isinstance(relation_changed, ops.RelationChangedEvent)
    assert isinstance(start, ops.StartEvent)


def test_deferred_relation_event_from_relation(mycharm):
    ctx = Context(mycharm, meta=mycharm.META)
    mycharm.defer_next = 2
    rel = Relation(endpoint='foo', remote_app_name='remote')
    out = trigger(
        State(
            relations={rel},
            deferred=[
                ctx.on.relation_changed(rel, remote_unit=1).deferred(handler=mycharm._on_event)
            ],
        ),
        'start',
        mycharm,
        meta=mycharm.META,
    )

    # we deferred the first 2 events we saw: foo_relation_changed, start.
    relation_changed, start = out.deferred
    assert relation_changed.name == 'foo_relation_changed'
    assert relation_changed.snapshot_data == {
        'relation_name': rel.endpoint,
        'relation_id': rel.id,
        'app_name': 'remote',
        'unit_name': 'remote/1',
    }
    assert start.name == 'start'

    # we saw start and foo_relation_changed.
    relation_changed, start = mycharm.captured
    assert isinstance(relation_changed, ops.RelationChangedEvent)
    assert isinstance(start, ops.StartEvent)


def test_deferred_workload_event(mycharm):
    mycharm.defer_next = 2

    ctr = Container('foo')

    out = trigger(
        State(
            containers={ctr},
            deferred=[
                _Event('foo_pebble_ready', container=ctr).deferred(handler=mycharm._on_event)
            ],
        ),
        'start',
        mycharm,
        meta=mycharm.META,
    )

    # we deferred the first 2 events we saw: foo_pebble_ready, start.
    pebble_ready, start = out.deferred
    assert pebble_ready.name == 'foo_pebble_ready'
    assert start.name == 'start'

    # we saw start and foo_pebble_ready.
    ready, start = mycharm.captured
    assert isinstance(ready, ops.WorkloadEvent)
    assert isinstance(start, ops.StartEvent)


def test_defer_reemit_lifecycle_event(mycharm):
    ctx = Context(mycharm, meta=mycharm.META, capture_deferred_events=True)

    mycharm.defer_next = 1
    state_1 = ctx.run(ctx.on.update_status(), State())

    mycharm.defer_next = 0
    state_2 = ctx.run(ctx.on.start(), state_1)

    assert [type(e).__name__ for e in ctx.emitted_events] == [
        'UpdateStatusEvent',
        'UpdateStatusEvent',
        'StartEvent',
    ]
    assert len(state_1.deferred) == 1
    assert not state_2.deferred


def test_defer_reemit_relation_event(mycharm):
    ctx = Context(mycharm, meta=mycharm.META, capture_deferred_events=True)

    rel = Relation('foo')
    mycharm.defer_next = 1
    state_1 = ctx.run(ctx.on.relation_created(rel), State(relations={rel}))

    mycharm.defer_next = 0
    state_2 = ctx.run(ctx.on.start(), state_1)

    assert [type(e).__name__ for e in ctx.emitted_events] == [
        'RelationCreatedEvent',
        'RelationCreatedEvent',
        'StartEvent',
    ]
    assert len(state_1.deferred) == 1
    assert not state_2.deferred


class CustomEventWithArgs(ops.EventBase):
    arg0: str
    arg1: int

    def __init__(self, handle: ops.Handle, arg0: str = '', arg1: int = 0):
        super().__init__(handle)
        self.arg0 = arg0
        self.arg1 = arg1

    def snapshot(self):
        base = super().snapshot()
        base.update({'arg0': self.arg0, 'arg1': self.arg1})
        return base

    def restore(self, snapshot: dict[str, typing.Any]):
        super().restore(snapshot)
        self.arg0 = snapshot['arg0']
        self.arg1 = snapshot['arg1']


class CustomEvents(ops.ObjectEvents):
    foo_changed = ops.EventSource(CustomEventWithArgs)


class MyConsumer(ops.Object):
    on = CustomEvents()  # type: ignore

    def __init__(self, charm: ops.CharmBase):
        super().__init__(charm, 'my-consumer')


def test_defer_custom_event(mycharm):
    class MyCharm(mycharm):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            self.consumer = MyConsumer(self)
            framework.observe(self.consumer.on.foo_changed, self._on_event)

    ctx = Context(MyCharm, meta=mycharm.META, capture_deferred_events=True)

    mycharm.defer_next = 1
    state_1 = ctx.run(ctx.on.custom(MyConsumer.on.foo_changed, 'foo', 28), State())
    assert [type(e).__name__ for e in ctx.emitted_events] == ['CustomEventWithArgs']
    assert ctx.emitted_events[0].snapshot() == {'arg0': 'foo', 'arg1': 28}
    assert len(state_1.deferred) == 1

    mycharm.defer_next = 0
    state_2 = ctx.run(ctx.on.start(), state_1)
    assert [type(e).__name__ for e in ctx.emitted_events] == [
        'CustomEventWithArgs',
        'CustomEventWithArgs',
        'StartEvent',
    ]
    assert (
        ctx.emitted_events[0].snapshot()
        == ctx.emitted_events[1].snapshot()
        == {'arg0': 'foo', 'arg1': 28}
    )
    assert not state_2.deferred


def test_juju_log_over_deferred(mycharm):
    # A backend is created for each charm, so one for a deferred event and one
    # for the primary event. We want to ensure that all the logs end up in the
    # context.
    logger = logging.getLogger(__name__)

    class MyCharm(mycharm):
        def _on_event(self, event: ops.EventBase):
            super()._on_event(event)
            logger.info('Handled event %s', event.__class__.__name__)

    ctx = Context(MyCharm, meta=mycharm.META)
    mycharm.defer_next = 1
    ctx.run(
        ctx.on.start(),
        State(deferred=[ctx.on.update_status().deferred(MyCharm._on_event)]),
    )
    logs = [log.message for log in ctx.juju_log if log.level == 'INFO']
    assert logs == [
        'Handled event UpdateStatusEvent',
        'Handled event StartEvent',
    ]
