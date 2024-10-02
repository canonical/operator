import os

import pytest
from ops.charm import CharmBase, CharmEvents
from ops.framework import EventBase, EventSource, Framework, Object

from scenario.state import State, _CharmSpec, _Event
from ..helpers import trigger


class QuxEvent(EventBase):
    pass


class SubEvent(EventBase):
    pass


@pytest.fixture(scope="function")
def mycharm():
    class MyCharmEvents(CharmEvents):
        qux = EventSource(QuxEvent)

    class MySubEvents(CharmEvents):
        sub = EventSource(SubEvent)

    class Sub(Object):
        on = MySubEvents()

    class MyCharm(CharmBase):
        on = MyCharmEvents()
        evts = []

        def __init__(self, framework: Framework):
            super().__init__(framework)
            self.sub = Sub(self, "sub")
            self.framework.observe(self.sub.on.sub, self._on_event)
            self.framework.observe(self.on.qux, self._on_event)

        def _on_event(self, e):
            MyCharm.evts.append(e)

    return MyCharm


@pytest.mark.parametrize("evt_name", ("rubbish", "foo", "bar", "kazoo_pebble_ready"))
def test_rubbish_event_raises(mycharm, evt_name):
    with pytest.raises(AttributeError):
        if evt_name.startswith("kazoo"):
            os.environ["SCENARIO_SKIP_CONSISTENCY_CHECKS"] = "true"
            # else it will whine about the container not being in state and meta;
            # but if we put the container in meta, it will actually register an event!

        trigger(State(), evt_name, mycharm, meta={"name": "foo"})

        if evt_name.startswith("kazoo"):
            os.environ["SCENARIO_SKIP_CONSISTENCY_CHECKS"] = "false"


@pytest.mark.parametrize("evt_name", ("qux",))
def test_custom_events_fail(mycharm, evt_name):
    with pytest.raises(AttributeError):
        trigger(State(), evt_name, mycharm, meta={"name": "foo"})


# cfr: https://github.com/PietroPasotti/ops-scenario/pull/11#discussion_r1101694961
@pytest.mark.parametrize("evt_name", ("sub",))
def test_custom_events_sub_raise(mycharm, evt_name):
    with pytest.raises(AttributeError):
        trigger(State(), evt_name, mycharm, meta={"name": "foo"})


@pytest.mark.parametrize(
    "evt_name, expected",
    (
        ("qux", False),
        ("sub", False),
        ("start", True),
        ("install", True),
        ("config-changed", True),
        ("foo-relation-changed", True),
        ("bar-relation-changed", True),
    ),
)
def test_is_custom_event(mycharm, evt_name, expected):
    spec = _CharmSpec(
        charm_type=mycharm, meta={"name": "mycharm", "requires": {"foo": {}}}
    )
    assert _Event(evt_name)._is_builtin_event(spec) is expected
