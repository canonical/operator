import pytest
from ops import __version__ as ops_version
from ops.charm import ActionEvent, CharmBase
from ops.framework import Framework
from ops._private.harness import ActionFailed

from scenario import Context
from scenario.state import State, _Action, _next_action_id


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
    state = ctx.run(ctx.on.action("foo", params={"baz": baz_value, "bar": 10}), State())

    assert isinstance(state, State)
    evt = ctx.emitted_events[0]
    assert evt.params["bar"] == 10
    assert evt.params["baz"] is baz_value


def test_action_no_results():
    class MyCharm(CharmBase):
        def __init__(self, framework):
            super().__init__(framework)
            framework.observe(self.on.act_action, self._on_act_action)

        def _on_act_action(self, _):
            pass

    ctx = Context(MyCharm, meta={"name": "foo"}, actions={"act": {}})
    ctx.run(ctx.on.action("act"), State())
    assert ctx.action_results is None
    assert ctx.action_logs == []


@pytest.mark.parametrize("res_value", ("one", 1, [2], ["bar"], (1,), {1, 2}))
def test_action_event_results_invalid(mycharm, res_value):
    def handle_evt(charm: CharmBase, evt: ActionEvent):
        with pytest.raises((TypeError, AttributeError)):
            evt.set_results(res_value)

    mycharm._evt_handler = handle_evt

    ctx = Context(mycharm, meta={"name": "foo"}, actions={"foo": {}})
    ctx.run(ctx.on.action("foo"), State())


@pytest.mark.parametrize("res_value", ({"a": {"b": {"c"}}}, {"d": "e"}))
def test_action_event_results_valid(mycharm, res_value):
    def handle_evt(_: CharmBase, evt):
        if not isinstance(evt, ActionEvent):
            return
        evt.set_results(res_value)
        evt.log("foo")
        evt.log("bar")

    mycharm._evt_handler = handle_evt

    ctx = Context(mycharm, meta={"name": "foo"}, actions={"foo": {}})

    ctx.run(ctx.on.action("foo"), State())

    assert ctx.action_results == res_value


@pytest.mark.parametrize("res_value", ({"a": {"b": {"c"}}}, {"d": "e"}))
def test_action_event_outputs(mycharm, res_value):
    def handle_evt(_: CharmBase, evt: ActionEvent):
        if not isinstance(evt, ActionEvent):
            return

        evt.set_results({"my-res": res_value})
        evt.log("log1")
        evt.log("log2")
        evt.fail("failed becozz")

    mycharm._evt_handler = handle_evt

    ctx = Context(mycharm, meta={"name": "foo"}, actions={"foo": {}})
    with pytest.raises(ActionFailed) as exc_info:
        ctx.run(ctx.on.action("foo"), State())
    assert exc_info.value.message == "failed becozz"
    assert ctx.action_results == {"my-res": res_value}
    assert ctx.action_logs == ["log1", "log2"]


def test_action_continues_after_fail():
    class MyCharm(CharmBase):
        def __init__(self, framework):
            super().__init__(framework)
            framework.observe(self.on.foo_action, self._on_foo_action)

        def _on_foo_action(self, event):
            event.log("starting")
            event.set_results({"initial": "result"})
            event.fail("oh no!")
            event.set_results({"final": "result"})

    ctx = Context(MyCharm, meta={"name": "foo"}, actions={"foo": {}})
    with pytest.raises(ActionFailed) as exc_info:
        ctx.run(ctx.on.action("foo"), State())
    assert exc_info.value.message == "oh no!"
    assert ctx.action_logs == ["starting"]
    assert ctx.action_results == {"initial": "result", "final": "result"}


def _ops_less_than(wanted_major, wanted_minor):
    major, minor = (int(v) for v in ops_version.split(".")[:2])
    if major < wanted_major:
        return True
    if major == wanted_major and minor < wanted_minor:
        return True
    return False


@pytest.mark.skipif(
    _ops_less_than(2, 11), reason="ops 2.10 and earlier don't have ActionEvent.id"
)
def test_action_event_has_id(mycharm):
    def handle_evt(_: CharmBase, evt: ActionEvent):
        if not isinstance(evt, ActionEvent):
            return
        assert isinstance(evt.id, str) and evt.id != ""

    mycharm._evt_handler = handle_evt

    ctx = Context(mycharm, meta={"name": "foo"}, actions={"foo": {}})
    ctx.run(ctx.on.action("foo"), State())


@pytest.mark.skipif(
    _ops_less_than(2, 11), reason="ops 2.10 and earlier don't have ActionEvent.id"
)
def test_action_event_has_override_id(mycharm):
    uuid = "0ddba11-cafe-ba1d-5a1e-dec0debad"

    def handle_evt(charm: CharmBase, evt: ActionEvent):
        if not isinstance(evt, ActionEvent):
            return
        assert evt.id == uuid

    mycharm._evt_handler = handle_evt

    ctx = Context(mycharm, meta={"name": "foo"}, actions={"foo": {}})
    ctx.run(ctx.on.action("foo", id=uuid), State())


def test_two_actions_same_context():
    class MyCharm(CharmBase):
        def __init__(self, framework):
            super().__init__(framework)
            framework.observe(self.on.foo_action, self._on_foo_action)
            framework.observe(self.on.bar_action, self._on_bar_action)

        def _on_foo_action(self, event):
            event.log("foo")
            event.set_results({"foo": "result"})

        def _on_bar_action(self, event):
            event.log("bar")
            event.set_results({"bar": "result"})

    ctx = Context(MyCharm, meta={"name": "foo"}, actions={"foo": {}, "bar": {}})
    ctx.run(ctx.on.action("foo"), State())
    assert ctx.action_results == {"foo": "result"}
    assert ctx.action_logs == ["foo"]
    # Not recommended, but run another action in the same context.
    ctx.run(ctx.on.action("bar"), State())
    assert ctx.action_results == {"bar": "result"}
    assert ctx.action_logs == ["bar"]


def test_positional_arguments():
    with pytest.raises(TypeError):
        _Action("foo", {})


def test_default_arguments():
    expected_id = _next_action_id(update=False)
    name = "foo"
    action = _Action(name)
    assert action.name == name
    assert action.params == {}
    assert action.id == expected_id
