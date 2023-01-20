from typing import Optional

import pytest
from ops.charm import CharmBase, StartEvent, ActionEvent
from ops.framework import Framework

from scenario.scenario import Scenario
from scenario.structs import (
    CharmSpec,
    Scene,
    State,
    event,
)


@pytest.fixture(scope="function")
def charm_evts():
    events = []
    class MyCharm(CharmBase):
        def __init__(self, framework: Framework, key: Optional[str] = None):
            super().__init__(framework, key)
            for evt in self.on.events().values():
                self.framework.observe(evt, self._on_event)

            print(self.on.show_proxied_endpoints_action)

        def _on_event(self, event):
            events.append(event)

    return MyCharm, events


def test_start_event(charm_evts):
    charm, evts = charm_evts
    scenario = Scenario(
        CharmSpec(charm,
                  meta={"name": "foo"},
                  actions={"show_proxied_endpoints": {}}))
    scene = Scene(event("start"), state=State())
    scenario.play(scene)
    assert len(evts) == 1
    assert isinstance(evts[0], StartEvent)


@pytest.mark.xfail(reason="actions not implemented yet")
def test_action_event(charm_evts):
    charm, evts = charm_evts

    scenario = Scenario(
        CharmSpec(charm,
                  meta={"name": "foo"},
                  actions={"show_proxied_endpoints": {}}))
    scene = Scene(event("show_proxied_endpoints_action"), state=State())
    scenario.play(scene)
    assert len(evts) == 1
    assert isinstance(evts[0], ActionEvent)
