from unittest.mock import patch

import pytest
from ops import CharmBase

from scenario import Action, ActionOutput, Context, State
from scenario.state import _Event, next_action_id


class MyCharm(CharmBase):
    pass


def test_run():
    ctx = Context(MyCharm, meta={"name": "foo"})
    state = State()

    with patch.object(ctx, "_run") as p:
        ctx._output_state = "foo"  # would normally be set within the _run call scope
        output = ctx.run(ctx.on.start(), state)
        assert output == "foo"

    assert p.called
    e = p.call_args.kwargs["event"]
    s = p.call_args.kwargs["state"]

    assert isinstance(e, _Event)
    assert e.name == "start"
    assert s is state


def test_run_action():
    ctx = Context(MyCharm, meta={"name": "foo"})
    state = State()
    expected_id = next_action_id(update=False)

    with patch.object(ctx, "_run_action") as p:
        ctx._output_state = (
            "foo"  # would normally be set within the _run_action call scope
        )
        action = Action("do-foo")
        output = ctx.run_action(action, state)
        assert output.state == "foo"

    assert p.called
    a = p.call_args.kwargs["action"]
    s = p.call_args.kwargs["state"]

    assert isinstance(a, Action)
    assert a.event.name == "do_foo_action"
    assert s is state
    assert a.id == expected_id


@pytest.mark.parametrize("app_name", ("foo", "bar", "george"))
@pytest.mark.parametrize("unit_id", (1, 2, 42))
def test_app_name(app_name, unit_id):
    ctx = Context(MyCharm, meta={"name": "foo"}, app_name=app_name, unit_id=unit_id)
    with ctx.manager(ctx.on.start(), State()) as mgr:
        assert mgr.charm.app.name == app_name
        assert mgr.charm.unit.name == f"{app_name}/{unit_id}"


def test_action_output_no_positional_arguments():
    with pytest.raises(TypeError):
        ActionOutput(None, None)


def test_action_output_no_results():
    class MyCharm(CharmBase):
        def __init__(self, framework):
            super().__init__(framework)
            framework.observe(self.on.act_action, self._on_act_action)

        def _on_act_action(self, _):
            pass

    ctx = Context(MyCharm, meta={"name": "foo"}, actions={"act": {}})
    out = ctx.run_action(Action("act"), State())
    assert out.results is None
    assert out.failure is None
