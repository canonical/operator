import pytest
from ops.charm import CharmBase, CharmEvents
from ops.framework import EventBase, EventSource, Framework, Object

from scenario.state import State


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
    with pytest.raises(RuntimeError):
        State().trigger(evt_name, mycharm, meta={"name": "foo"})


@pytest.mark.parametrize("evt_name", ("rubbish", "foo", "bar", "kazoo_pebble_ready"))
def test_rubbish_event_warns(mycharm, evt_name, caplog):
    State().trigger(evt_name, mycharm, meta={"name": "foo"}, on_no_event_handler="warn")
    assert caplog.messages[0].startswith(
        f"Charm has no registered observers for {evt_name!r}."
    )


@pytest.mark.parametrize("evt_name", ("rubbish", "foo", "bar", "kazoo_pebble_ready"))
def test_rubbish_event_passes(mycharm, evt_name):
    State().trigger(evt_name, mycharm, meta={"name": "foo"}, on_no_event_handler="pass")


@pytest.mark.parametrize("evt_name", ("qux",))
def test_custom_events_pass(mycharm, evt_name):
    State().trigger(evt_name, mycharm, meta={"name": "foo"})


# cfr: https://github.com/PietroPasotti/ops-scenario/pull/11#discussion_r1101694961
@pytest.mark.parametrize("evt_name", ("sub",))
def test_custom_events_sub_raise(mycharm, evt_name):
    with pytest.raises(RuntimeError):
        State().trigger(evt_name, mycharm, meta={"name": "foo"})
