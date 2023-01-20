from typing import Optional, Type

import pytest
from ops.charm import CharmBase, CharmEvents
from ops.framework import EventBase, Framework

from scenario.scenario import check_builtin_sequences
from scenario.structs import CharmSpec

CHARM_CALLED = 0


@pytest.fixture(scope="function")
def mycharm():
    global CHARM_CALLED
    CHARM_CALLED = 0

    class MyCharm(CharmBase):
        _call = None

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


def test_builtin_scenes(mycharm):
    charm_spec = CharmSpec(mycharm, meta={"name": "foo"})
    check_builtin_sequences(charm_spec)
    assert CHARM_CALLED == 12
