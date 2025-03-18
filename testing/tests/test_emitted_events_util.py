from typing import Any

import ops

from scenario import State
from scenario.state import _Event
from scenario._runtime import capture_events
from .helpers import trigger


class Foo(ops.EventBase):
    pass


class MyCharmEvents(ops.CharmEvents):
    foo = ops.EventSource(Foo)


class MyCharm(ops.CharmBase):
    META = {"name": "mycharm"}
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
    with capture_events(include_framework=True) as emitted:
        trigger(State(), "start", MyCharm, meta=MyCharm.META)

    assert len(emitted) == 5
    assert isinstance(emitted[0], ops.StartEvent)
    assert isinstance(emitted[1], Foo)
    assert isinstance(emitted[2], ops.CollectStatusEvent)
    assert isinstance(emitted[3], ops.PreCommitEvent)
    assert isinstance(emitted[4], ops.CommitEvent)


def test_capture_juju_evt():
    with capture_events() as emitted:
        trigger(State(), "start", MyCharm, meta=MyCharm.META)

    assert len(emitted) == 2
    assert isinstance(emitted[0], ops.StartEvent)
    assert isinstance(emitted[1], Foo)


def test_capture_deferred_evt():
    with capture_events() as emitted:
        trigger(
            State(deferred=[_Event("foo").deferred(handler=MyCharm._on_foo)]),
            "start",
            MyCharm,
            meta=MyCharm.META,
        )

    assert len(emitted) == 3
    assert isinstance(emitted[0], Foo)
    assert isinstance(emitted[1], ops.StartEvent)
    assert isinstance(emitted[2], Foo)


def test_capture_no_deferred_evt():
    # todo: this test should pass with ops < 2.1 as well
    with capture_events(include_deferred=False) as emitted:
        trigger(
            State(deferred=[_Event("foo").deferred(handler=MyCharm._on_foo)]),
            "start",
            MyCharm,
            meta=MyCharm.META,
        )

    assert len(emitted) == 2
    assert isinstance(emitted[0], ops.StartEvent)
    assert isinstance(emitted[1], Foo)
