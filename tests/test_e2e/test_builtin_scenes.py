import pytest
from ops.charm import CharmBase
from ops.framework import Framework

from scenario.sequences import check_builtin_sequences
from scenario.state import State

CHARM_CALLED = 0


@pytest.fixture(scope="function")
def mycharm():
    global CHARM_CALLED
    CHARM_CALLED = 0

    class MyCharm(CharmBase):
        _call = None
        require_config = False

        def __init__(self, framework: Framework):
            super().__init__(framework)
            self.called = False
            if self.require_config:
                assert self.config["foo"] == "bar"

            for evt in self.on.events().values():
                self.framework.observe(evt, self._on_event)

        def _on_event(self, event):
            global CHARM_CALLED
            CHARM_CALLED += 1

            if self._call:
                self.called = True
                self._call(event)

    return MyCharm


def test_builtin_scenes(mycharm):
    check_builtin_sequences(mycharm, meta={"name": "foo"})
    assert CHARM_CALLED == 12


def test_builtin_scenes_template(mycharm):
    mycharm.require_config = True
    check_builtin_sequences(
        mycharm,
        meta={"name": "foo"},
        config={"options": {"foo": {"type": "string"}}},
        template_state=State(config={"foo": "bar"}),
    )
    assert CHARM_CALLED == 12
