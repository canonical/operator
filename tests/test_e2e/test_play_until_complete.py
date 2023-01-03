from typing import Optional, Type

import pytest
from ops.charm import CharmBase, CharmEvents
from ops.framework import EventBase, Framework

from scenario.scenario import StartupScenario, TeardownScenario
from scenario.structs import CharmSpec

CHARM_CALLED = 0


@pytest.fixture(scope="function")
def mycharm():
    global CHARM_CALLED
    CHARM_CALLED = 0

    class MyCharmEvents(CharmEvents):
        @classmethod
        def define_event(cls, event_kind: str, event_type: "Type[EventBase]"):
            if getattr(cls, event_kind, None):
                delattr(cls, event_kind)
            return super().define_event(event_kind, event_type)

    class MyCharm(CharmBase):
        _call = None
        on = MyCharmEvents()

        def __init__(self, framework: Framework, key: Optional[str] = None):
            super().__init__(framework, key)
            self.called = False

            for evt in self.on.events().values():
                self.framework.observe(evt, self._on_event)

        def _on_event(self, event):
            global CHARM_CALLED
            CHARM_CALLED += 1

            if self._call:
                self.called = True
                self._call(event)

    return MyCharm


@pytest.mark.parametrize("leader", (True, False))
def test_setup(leader, mycharm):
    scenario = StartupScenario(CharmSpec(mycharm, meta={"name": "foo"}), leader=leader)
    scenario.play_until_complete()
    assert CHARM_CALLED == 4


def test_teardown(mycharm):
    scenario = TeardownScenario(CharmSpec(mycharm, meta={"name": "foo"}))
    scenario.play_until_complete()
    assert CHARM_CALLED == 2
