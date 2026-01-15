# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

from __future__ import annotations

import pytest
from scenario import Context, Manager, State
from scenario.errors import AlreadyEmittedError

import ops


class Charm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        for evt in self.on.events().values():
            framework.observe(evt, self._on_event)

    def _on_event(self, e: ops.EventBase):
        if isinstance(e, ops.CollectStatusEvent):
            return
        self.unit.status = ops.ActiveStatus(e.handle.kind)


@pytest.fixture
def ctx() -> Context[Charm]:
    return Context(Charm, meta={'name': 'foo'}, actions={'do-x': {}})


def test_manager(ctx: Context[Charm]):
    with Manager(ctx, ctx.on.start(), State()) as manager:
        assert isinstance(manager.charm, Charm)
        state_out = manager.run()

    assert isinstance(state_out, State)


def test_manager_implicit(ctx: Context[Charm]):
    with Manager(ctx, ctx.on.start(), State()) as manager:
        assert isinstance(manager.charm, Charm)
        # do not call .run()

    # run is called automatically
    assert manager._emitted


def test_manager_reemit_fails(ctx: Context[Charm]):
    with Manager(ctx, ctx.on.start(), State()) as manager:
        manager.run()
        with pytest.raises(AlreadyEmittedError):
            manager.run()


def test_context_manager(ctx: Context[Charm]):
    with ctx(ctx.on.start(), State()) as manager:
        state_out = manager.run()
        assert isinstance(state_out, State)
    assert ctx.emitted_events[0].handle.kind == 'start'


def test_context_action_manager(ctx: Context[Charm]):
    with ctx(ctx.on.action('do-x'), State()) as manager:
        state_out = manager.run()
        assert isinstance(state_out, State)
    assert ctx.emitted_events[0].handle.kind == 'do_x_action'
