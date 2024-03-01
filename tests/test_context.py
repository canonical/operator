from unittest.mock import patch

import pytest
from ops import CharmBase

from scenario import Action, Context, Event, State
from scenario.state import next_action_id


class MyCharm(CharmBase):
    pass


def test_run():
    ctx = Context(MyCharm, meta={"name": "foo"})
    state = State()

    with patch.object(ctx, "_run") as p:
        ctx._output_state = "foo"  # would normally be set within the _run call scope
        output = ctx.run("start", state)
        assert output == "foo"

    assert p.called
    e = p.call_args.kwargs["event"]
    s = p.call_args.kwargs["state"]

    assert isinstance(e, Event)
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
        output = ctx.run_action("do-foo", state)
        assert output.state == "foo"

    assert p.called
    a = p.call_args.kwargs["action"]
    s = p.call_args.kwargs["state"]

    assert isinstance(a, Action)
    assert a.event.name == "do_foo_action"
    assert s is state
    assert a.id == expected_id


def test_clear():
    ctx = Context(MyCharm, meta={"name": "foo"})
    state = State()

    ctx.run("start", state)
    assert ctx.emitted_events

    ctx.clear()
    assert not ctx.emitted_events  # and others...


@pytest.mark.parametrize("app_name", ("foo", "bar", "george"))
@pytest.mark.parametrize("unit_id", (1, 2, 42))
def test_app_name(app_name, unit_id):
    with Context(
        MyCharm, meta={"name": "foo"}, app_name=app_name, unit_id=unit_id
    ).manager("start", State()) as mgr:
        assert mgr.charm.app.name == app_name
        assert mgr.charm.unit.name == f"{app_name}/{unit_id}"
