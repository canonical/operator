# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from scenario import Context, State
from scenario.state import _Event

from ops.charm import CharmBase, CharmEvents, CollectStatusEvent, StartEvent
from ops.framework import CommitEvent, EventBase, EventSource, PreCommitEvent


class Foo(EventBase):
    pass


class MyCharmEvents(CharmEvents):
    foo = EventSource(Foo)


class MyCharm(CharmBase):
    META: Mapping[str, Any] = {'name': 'mycharm'}
    on = MyCharmEvents()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.framework.observe(self.on.start, self._on_start)
        self.framework.observe(self.on.foo, self._on_foo)

    def _on_start(self, e):
        self.on.foo.emit()

    def _on_foo(self, e):
        pass


def test_capture_custom_evt_nonspecific_capture_include_fw_evts():
    ctx = Context(MyCharm, meta=MyCharm.META, capture_framework_events=True)
    ctx.run(ctx.on.start(), State())

    emitted = ctx.emitted_events
    assert len(emitted) == 5
    assert isinstance(emitted[0], StartEvent)
    assert isinstance(emitted[1], Foo)
    assert isinstance(emitted[2], CollectStatusEvent)
    assert isinstance(emitted[3], PreCommitEvent)
    assert isinstance(emitted[4], CommitEvent)


def test_capture_juju_evt():
    ctx = Context(MyCharm, meta=MyCharm.META)
    ctx.run(ctx.on.start(), State())

    emitted = ctx.emitted_events
    assert len(emitted) == 2
    assert isinstance(emitted[0], StartEvent)
    assert isinstance(emitted[1], Foo)


def test_capture_deferred_evt():
    ctx = Context(MyCharm, meta=MyCharm.META, capture_deferred_events=True)
    deferred = [_Event('foo').deferred(handler=MyCharm._on_foo)]
    ctx.run(ctx.on.start(), State(deferred=deferred))

    emitted = ctx.emitted_events
    assert len(emitted) == 3
    assert isinstance(emitted[0], Foo)
    assert isinstance(emitted[1], StartEvent)
    assert isinstance(emitted[2], Foo)


def test_capture_no_deferred_evt():
    ctx = Context(MyCharm, meta=MyCharm.META)
    deferred = [_Event('foo').deferred(handler=MyCharm._on_foo)]
    ctx.run(ctx.on.start(), State(deferred=deferred))

    emitted = ctx.emitted_events
    assert len(emitted) == 2
    assert isinstance(emitted[0], StartEvent)
    assert isinstance(emitted[1], Foo)
