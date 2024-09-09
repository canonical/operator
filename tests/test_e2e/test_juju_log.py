import logging

import pytest
from ops.charm import CharmBase, CollectStatusEvent

from scenario import Context
from scenario.state import JujuLogLine, State

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
            if isinstance(event, CollectStatusEvent):
                return
            print("foo!")
            logger.warning("bar!")

    return MyCharm


def test_juju_log(mycharm):
    ctx = Context(mycharm, meta=mycharm.META)
    ctx.run(ctx.on.start(), State())
    assert ctx.juju_log[-2] == JujuLogLine(
        level="DEBUG", message="Emitting Juju event start."
    )
    assert ctx.juju_log[-1] == JujuLogLine(level="WARNING", message="bar!")
    # prints are not juju-logged.
