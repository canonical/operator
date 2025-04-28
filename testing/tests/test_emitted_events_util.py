from __future__ import annotations

from typing import Any

import ops

from scenario import Context, State
from scenario.state import _Event


class Foo(ops.EventBase):
    pass


class MyCharmEvents(ops.CharmEvents):
    foo = ops.EventSource(Foo)


class MyCharm(ops.CharmBase):
    META = {'name': 'mycharm'}
    on = MyCharmEvents()  # type: ignore

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.framework.observe(self.on.start, self._on_start)
        self.framework.observe(self.on.foo, self._on_foo)

    def _on_start(self, _: ops.StartEvent):
        self.on.foo.emit()

    def _on_foo(self, _: Foo):
        pass


def test_capture_custom_evt_nonspecific_capture_include_fw_evts():
    ctx = Context(MyCharm, meta=MyCharm.META, capture_framework_events=True)
    ctx.run(ctx.on.start(), State())

    emitted = ctx.emitted_events
    assert len(emitted) == 5
    assert isinstance(emitted[0], ops.StartEvent)
    assert isinstance(emitted[1], Foo)
    assert isinstance(emitted[2], ops.CollectStatusEvent)
    assert isinstance(emitted[3], ops.PreCommitEvent)
    assert isinstance(emitted[4], ops.CommitEvent)


def test_capture_juju_evt():
    ctx = Context(MyCharm, meta=MyCharm.META)
    ctx.run(ctx.on.start(), State())

    emitted = ctx.emitted_events
    assert len(emitted) == 2
    assert isinstance(emitted[0], ops.StartEvent)
    assert isinstance(emitted[1], Foo)


def test_capture_deferred_evt():
    ctx = Context(MyCharm, meta=MyCharm.META, capture_deferred_events=True)
    deferred = [_Event('foo').deferred(handler=MyCharm._on_foo)]
    ctx.run(ctx.on.start(), State(deferred=deferred))

    emitted = ctx.emitted_events
    assert len(emitted) == 3
    assert isinstance(emitted[0], Foo)
    assert isinstance(emitted[1], ops.StartEvent)
    assert isinstance(emitted[2], Foo)


def test_capture_no_deferred_evt():
    ctx = Context(MyCharm, meta=MyCharm.META)
    deferred = [_Event('foo').deferred(handler=MyCharm._on_foo)]
    ctx.run(ctx.on.start(), State(deferred=deferred))

    emitted = ctx.emitted_events
    assert len(emitted) == 2
    assert isinstance(emitted[0], ops.StartEvent)
    assert isinstance(emitted[1], Foo)
