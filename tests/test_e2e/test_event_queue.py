import pytest
from ops.charm import CharmBase, UpdateStatusEvent, StartEvent
from ops.framework import Framework

from scenario.state import State, StoredEvent

CHARM_CALLED = 0


@pytest.fixture(scope="function")
def mycharm():
    class MyCharm(CharmBase):
        META = {'name': 'mycharm'}
        defer_next = 0
        captured = []

        def __init__(self, framework: Framework):
            super().__init__(framework)
            for evt in self.on.events().values():
                self.framework.observe(evt, self._on_event)

        def _on_event(self, event):
            self.captured.append(event)
            if self.defer_next:
                self.defer_next -= 1
                return event.defer()

    return MyCharm


def test_defer(mycharm):
    mycharm.defer_next = True
    out = State().trigger('start', mycharm, meta=mycharm.META)
    assert len(out.event_queue) == 1
    assert out.event_queue[0].name == 'start'


def test_deferred_evt_emitted(mycharm):
    mycharm.defer_next = 2
    out = State(
        event_queue=[
            StoredEvent('MyCharm/on/update_status[1]', 'MyCharm', '_on_event')
        ]
    ).trigger('start', mycharm, meta=mycharm.META)

    # we deferred the first 2 events we saw: update-status, start.
    assert len(out.event_queue) == 2
    assert out.event_queue[0].name == 'start'
    assert out.event_queue[1].name == 'update_status'

    # we saw start and update-status.
    assert len(mycharm.captured) == 2
    upstat, start = mycharm.captured
    assert isinstance(upstat, UpdateStatusEvent)
    assert isinstance(start, StartEvent)
