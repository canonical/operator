import pytest
from ops.charm import ActionEvent, CharmBase, StartEvent
from ops.framework import Framework

from scenario.state import Event, State, _CharmSpec
from tests.helpers import trigger


@pytest.fixture(scope="function")
def charm_evts():
    events = []

    class MyCharm(CharmBase):
        def __init__(self, framework: Framework):
            super().__init__(framework)
            for evt in self.on.events().values():
                self.framework.observe(evt, self._on_event)

            print(self.on.show_proxied_endpoints_action)

        def _on_event(self, event):
            events.append(event)

    return MyCharm, events


def test_start_event(charm_evts):
    charm, evts = charm_evts
    trigger(
        State(),
        event="start",
        charm_type=charm,
        meta={"name": "foo"},
        actions={"show_proxied_endpoints": {}},
    )
    assert len(evts) == 1
    assert isinstance(evts[0], StartEvent)
