import logging

import pytest
from ops.charm import CharmBase

from scenario import Context
from scenario.state import State
from tests.helpers import trigger

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
    ctx = Context(mycharm, meta=mycharm.META)
    ctx.run("start", State())
    assert ctx.juju_log[16] == ("DEBUG", "Emitting Juju event start.")
    # prints are not juju-logged.
    assert ctx.juju_log[17] == ("WARNING", "bar!")
