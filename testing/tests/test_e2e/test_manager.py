from __future__ import annotations

from typing import Any

import pytest
from ops import ActiveStatus, EventBase
from ops.charm import CharmBase, CollectStatusEvent
from ops.framework import Framework

from scenario import Context, State
from scenario.context import Manager
from scenario.errors import AlreadyEmittedError


@pytest.fixture(scope='function')
def mycharm():
    class MyCharm(CharmBase):
        META: dict[str, Any] = {'name': 'mycharm'}
        ACTIONS: dict[str, Any] = {'do-x': {}}

        def __init__(self, framework: Framework):
            super().__init__(framework)
            for evt in self.on.events().values():
                self.framework.observe(evt, self._on_event)

        def _on_event(self, e: EventBase) -> None:
            if isinstance(e, CollectStatusEvent):
                return

            self.unit.status = ActiveStatus(e.handle.kind)

    return MyCharm


def test_manager(mycharm: Any) -> None:
    ctx = Context(mycharm, meta=mycharm.META)
    with Manager(ctx, ctx.on.start(), State()) as manager:
        assert isinstance(manager.charm, mycharm)
        state_out = manager.run()

    assert isinstance(state_out, State)


def test_manager_implicit(mycharm: Any) -> None:
    ctx = Context(mycharm, meta=mycharm.META)
    with Manager(ctx, ctx.on.start(), State()) as manager:
        assert isinstance(manager.charm, mycharm)
        # do not call .run()

    # run is called automatically
    assert manager._emitted


def test_manager_reemit_fails(mycharm: Any) -> None:
    ctx = Context(mycharm, meta=mycharm.META)
    with Manager(ctx, ctx.on.start(), State()) as manager:
        manager.run()
        with pytest.raises(AlreadyEmittedError):
            manager.run()


def test_context_manager(mycharm: Any) -> None:
    ctx = Context(mycharm, meta=mycharm.META)
    with ctx(ctx.on.start(), State()) as manager:
        state_out = manager.run()
        assert isinstance(state_out, State)
    assert ctx.emitted_events[0].handle.kind == 'start'


def test_context_action_manager(mycharm: Any) -> None:
    ctx = Context(mycharm, meta=mycharm.META, actions=mycharm.ACTIONS)
    with ctx(ctx.on.action('do-x'), State()) as manager:
        state_out = manager.run()
        assert isinstance(state_out, State)
    assert ctx.emitted_events[0].handle.kind == 'do_x_action'
