from ops.charm import CharmBase, CharmEvents, CollectStatusEvent, StartEvent
from ops.framework import CommitEvent, EventBase, EventSource, PreCommitEvent

from scenario import State
from scenario.state import _Event
from scenario._runtime import capture_events
from .helpers import trigger


class Foo(EventBase):
    pass


class MyCharmEvents(CharmEvents):
    foo = EventSource(Foo)


class MyCharm(CharmBase):
    META = {"name": "mycharm"}
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
    with capture_events(include_framework=True) as emitted:
        trigger(State(), "start", MyCharm, meta=MyCharm.META)

    assert len(emitted) == 5
    assert isinstance(emitted[0], StartEvent)
    assert isinstance(emitted[1], Foo)
    assert isinstance(emitted[2], CollectStatusEvent)
    assert isinstance(emitted[3], PreCommitEvent)
    assert isinstance(emitted[4], CommitEvent)


def test_capture_juju_evt():
    with capture_events() as emitted:
        trigger(State(), "start", MyCharm, meta=MyCharm.META)

    assert len(emitted) == 2
    assert isinstance(emitted[0], StartEvent)
    assert isinstance(emitted[1], Foo)


def test_capture_deferred_evt():
    # todo: this test should pass with ops < 2.1 as well
    with capture_events() as emitted:
        trigger(
            State(deferred=[_Event("foo").deferred(handler=MyCharm._on_foo)]),
            "start",
            MyCharm,
            meta=MyCharm.META,
        )

    assert len(emitted) == 3
    assert isinstance(emitted[0], Foo)
    assert isinstance(emitted[1], StartEvent)
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
    assert isinstance(emitted[0], StartEvent)
    assert isinstance(emitted[1], Foo)
