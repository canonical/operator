import pytest
from ops.charm import CharmBase

from scenario import Action, Context, State
from scenario.context import AlreadyEmittedError, _EventEmitter


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

    return MyCharm


def test_emitter(mycharm):
    ctx = Context(mycharm, meta=mycharm.META)
    with _EventEmitter(ctx, "start", State()) as emitter:
        print("charm before", emitter.charm)
        state_out = emitter.emit()
        print("charm after", emitter.charm)

    assert state_out


def test_emitter_implicit(mycharm):
    ctx = Context(mycharm, meta=mycharm.META)
    with _EventEmitter(ctx, "start", State()) as emitter:
        print("charm before", emitter.charm)

    assert emitter.output


def test_emitter_reemit_fails(mycharm):
    ctx = Context(mycharm, meta=mycharm.META)
    with _EventEmitter(ctx, "start", State()) as emitter:
        print("charm before", emitter.charm)
        emitter.emit()
        with pytest.raises(AlreadyEmittedError):
            emitter.emit()

    assert emitter.output


def test_context_emitter(mycharm):
    ctx = Context(mycharm, meta=mycharm.META)
    with ctx.emitter("start", State()) as emitter:
        state_out = emitter.emit()
        assert state_out.model.name


def test_context_action_emitter(mycharm):
    ctx = Context(mycharm, meta=mycharm.META, actions=mycharm.ACTIONS)
    with ctx.action_emitter(Action("do-x"), State()) as emitter:
        state_out = emitter.emit()
        assert state_out.state.model.name
