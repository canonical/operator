import pytest
from ops import ActiveStatus
from ops.charm import CharmBase

from scenario import Action, Context, State
from scenario.context import AlreadyEmittedError, _EventManager


@pytest.fixture(scope="function")
def mycharm():
    class MyCharm(CharmBase):
        META = {"name": "mycharm"}
        ACTIONS = {"do-x": {}}

        def __init__(self, framework):
            super().__init__(framework)
            for evt in self.on.events().values():
                self.framework.observe(evt, self._on_event)

        def _on_event(self, e):
            print("event!")
            self.unit.status = ActiveStatus(e.handle.kind)

    return MyCharm


def test_manager(mycharm):
    ctx = Context(mycharm, meta=mycharm.META)
    with _EventManager(ctx, "start", State()) as manager:
        assert isinstance(manager.charm, mycharm)
        state_out = manager.run()

    assert state_out


def test_manager_legacy(mycharm):
    ctx = Context(mycharm, meta=mycharm.META)

    def pre_event(charm):
        print(1)

    def post_event(charm):
        print(2)

    ctx.run("start", State(), pre_event=pre_event, post_event=post_event)


def test_manager_implicit(mycharm):
    ctx = Context(mycharm, meta=mycharm.META)
    with _EventManager(ctx, "start", State()) as manager:
        print("charm before", manager.charm)

    assert manager.output
    assert manager.output.unit_status == ActiveStatus("start")


def test_manager_reemit_fails(mycharm):
    ctx = Context(mycharm, meta=mycharm.META)
    with _EventManager(ctx, "start", State()) as manager:
        print("charm before", manager.charm)
        manager.run()
        with pytest.raises(AlreadyEmittedError):
            manager.run()

    assert manager.output


def test_context_manager(mycharm):
    ctx = Context(mycharm, meta=mycharm.META)
    with ctx.manager("start", State()) as manager:
        state_out = manager.run()
        assert state_out.model.name


def test_context_action_manager(mycharm):
    ctx = Context(mycharm, meta=mycharm.META, actions=mycharm.ACTIONS)
    with ctx.action_manager(Action("do-x"), State()) as manager:
        ao = manager.run()
        assert ao.state.model.name
