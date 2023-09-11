from unittest.mock import patch

from ops import CharmBase

from scenario import Action, Context, Event, State


class MyCharm(CharmBase):
    pass


def test_run():
    ctx = Context(MyCharm, meta={"name": "foo"})
    state = State()

    with patch.object(ctx, "_run") as p:
        ctx.run("start", state)

    assert p.called
    e = p.call_args.kwargs["event"]
    s = p.call_args.kwargs["state"]

    assert isinstance(e, Event)
    assert e.name == "start"
    assert s is state


def test_run_action():
    ctx = Context(MyCharm, meta={"name": "foo"})
    state = State()

    with patch.object(ctx, "_run_action") as p:
        ctx.run_action("do-foo", state)

    assert p.called
    a = p.call_args.kwargs["action"]
    s = p.call_args.kwargs["state"]

    assert isinstance(a, Action)
    assert a.event.name == "do_foo_action"
    assert s is state
