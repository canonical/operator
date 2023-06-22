import pytest
from ops.charm import ActionEvent, CharmBase
from ops.framework import Framework

from scenario import Context
from scenario.context import InvalidEventError
from scenario.state import Action, Event, State
from tests.helpers import trigger


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
def test_action_event(mycharm, baz_value):
    ctx = Context(
        mycharm,
        meta={"name": "foo"},
        actions={
            "foo": {"params": {"bar": {"type": "number"}, "baz": {"type": "boolean"}}}
        },
    )
    action = Action("foo", params={"baz": baz_value, "bar": 10})
    ctx.run_action(action, State())

    evt = ctx.emitted_events[0]

    assert evt.params["bar"] == 10
    assert evt.params["baz"] is baz_value


@pytest.mark.parametrize("res_value", ("one", 1, [2], ["bar"], (1,), {1, 2}))
def test_action_event_results_invalid(mycharm, res_value):
    def handle_evt(charm: CharmBase, evt: ActionEvent):
        with pytest.raises((TypeError, AttributeError)):
            evt.set_results(res_value)

    mycharm._evt_handler = handle_evt

    action = Action("foo")
    ctx = Context(mycharm, meta={"name": "foo"}, actions={"foo": {}})
    ctx.run_action(action, State())


def test_cannot_run_action(mycharm):
    ctx = Context(mycharm, meta={"name": "foo"}, actions={"foo": {}})
    action = Action("foo")

    with pytest.raises(InvalidEventError):
        ctx.run(action, state=State())


def test_cannot_run_action_name(mycharm):
    ctx = Context(mycharm, meta={"name": "foo"}, actions={"foo": {}})
    action = Action("foo")
    with pytest.raises(InvalidEventError):
        ctx.run(action.event.name, state=State())


def test_cannot_run_action_event(mycharm):
    ctx = Context(mycharm, meta={"name": "foo"}, actions={"foo": {}})
    action = Action("foo")
    with pytest.raises(InvalidEventError):
        ctx.run(action.event, state=State())


@pytest.mark.parametrize("res_value", ({"a": {"b": {"c"}}}, {"d": "e"}))
def test_action_event_results_valid(mycharm, res_value):
    def handle_evt(charm: CharmBase, evt: ActionEvent):
        evt.set_results(res_value)
        evt.log("foo")
        evt.log("bar")

    mycharm._evt_handler = handle_evt

    action = Action("foo")
    ctx = Context(mycharm, meta={"name": "foo"}, actions={"foo": {}})

    out = ctx.run_action(action, State())

    assert out.results == res_value


@pytest.mark.parametrize("res_value", ({"a": {"b": {"c"}}}, {"d": "e"}))
def test_action_event_outputs(mycharm, res_value):
    def handle_evt(charm: CharmBase, evt: ActionEvent):
        evt.set_results({"my-res": res_value})
        evt.log("log1")
        evt.log("log2")
        evt.fail("failed becozz")

    mycharm._evt_handler = handle_evt

    action = Action("foo")
    ctx = Context(mycharm, meta={"name": "foo"}, actions={"foo": {}})
    out = ctx.run_action(action, State())

    assert out.failure == "failed becozz"
    assert out.logs == ["log1", "log2"]
