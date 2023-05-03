import logging

import pytest
from ops.charm import CharmBase

from scenario import trigger
from scenario.state import State

logger = logging.getLogger("testing logger")


@pytest.fixture(scope="function")
def mycharm():
    class MyCharm(CharmBase):
        META = {"name": "mycharm"}

        def __init__(self, framework):
            super().__init__(framework)
            for evt in self.on.events().values():
                self.framework.observe(evt, self._on_event)

        def _on_event(self, event):
            print("foo!")
            logger.warning("bar!")

    return MyCharm


def test_juju_log(mycharm):
    out = trigger(State(), "start", mycharm, meta=mycharm.META)
    assert out.juju_log[16] == ("DEBUG", "Emitting Juju event start.")
    # prints are not juju-logged.
    assert out.juju_log[17] == ("WARNING", "bar!")
