import pytest
from ops.charm import CharmBase
from ops.framework import Framework

from scenario import trigger
from scenario.state import Action, Event, Network, Relation, State, _CharmSpec


@pytest.fixture(scope="function")
def mycharm():
    class MyCharm(CharmBase):
        _evt_handler = None

        def __init__(self, framework: Framework):
            super().__init__(framework)
            for evt in self.on.events().values():
                self.framework.observe(evt, self._on_event)

        def _on_event(self, event):
            if handler := self._evt_handler:
                handler(event)

    return MyCharm


@pytest.mark.parametrize("baz_value", (True, False))
def test_action_event(mycharm, baz_value, emitted_events):
    trigger(
        State(),
        Action("foo", params={"baz": baz_value, "bar": 10}).event,
        mycharm,
        meta={"name": "foo"},
        actions={
            "foo": {"params": {"bar": {"type": "number"}, "baz": {"type": "boolean"}}}
        },
    )

    evt = emitted_events[0]

    assert evt.params["bar"] == 10
    assert evt.params["baz"] is baz_value


@pytest.mark.parametrize("res_value", ("one", 1, [2], ["bar"], (1,), {1, 2}))
def test_action_event_results_invalid(mycharm, res_value):
    def handle_evt(charm: CharmBase, evt: Event):
        with pytest.raises((TypeError, AttributeError)):
            evt.set_results(res_value)

    mycharm._evt_handler = handle_evt

    action = Action("foo")
    trigger(
        State(),
        action.event,
        mycharm,
        meta={"name": "foo"},
        actions={"foo": {}},
    )


@pytest.mark.parametrize("res_value", ({"a": {"b": {"c"}}}, {"d": "e"}))
def test_action_event_results_valid(mycharm, res_value):
    def handle_evt(charm: CharmBase, evt: Event):
        evt.set_results(res_value)

    mycharm._evt_handler = handle_evt

    action = Action("foo")
    trigger(
        State(),
        action.event,
        mycharm,
        meta={"name": "foo"},
        actions={"foo": {}},
    )

    assert action.results == res_value


@pytest.mark.parametrize("res_value", ({"a": {"b": {"c"}}}, {"d": "e"}))
def test_action_event_outputs(mycharm, res_value):
    def handle_evt(charm: CharmBase, evt: Event):
        evt.set_results({"my-res": res_value})
        evt.log("log1")
        evt.log("log2")
        evt.fail("failed becozz")

    mycharm._evt_handler = handle_evt

    action = Action("foo")
    trigger(
        State(),
        action.event,
        mycharm,
        meta={"name": "foo"},
        actions={"foo": {}},
    )

    assert action.failed
    assert action.failure_message == "failed becozz"
    assert action.logs == ["log1", "log2"]
