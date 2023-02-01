from typing import Optional

import pytest
from ops.charm import CharmBase
from ops.framework import Framework

from scenario.scenario import Scenario
from scenario.structs import (
    CharmSpec,
    NetworkSpec,
    Scene,
    State,
    event,
    network,
    relation,
)


@pytest.fixture(scope="function")
def mycharm():
    class MyCharm(CharmBase):
        _call = None
        called = False

        def __init__(self, framework: Framework):
            super().__init__(framework)

            for evt in self.on.events().values():
                self.framework.observe(evt, self._on_event)

        def _on_event(self, event):
            if MyCharm._call:
                MyCharm.called = True
                MyCharm._call(self, event)

    return MyCharm


def test_ip_get(mycharm):
    mycharm._call = lambda *_: True
    scenario = Scenario(
        CharmSpec(
            mycharm,
            meta={
                "name": "foo",
                "requires": {"metrics-endpoint": {"interface": "foo"}},
            },
        )
    )

    def fetch_unit_address(charm: CharmBase):
        rel = charm.model.get_relation("metrics-endpoint")
        assert str(charm.model.get_binding(rel).network.bind_address) == "1.1.1.1"

    scene = Scene(
        state=State(
            relations=[relation(endpoint="metrics-endpoint", interface="foo")],
            networks=[NetworkSpec("metrics-endpoint", bind_id=0, network=network())],
        ),
        event=event("update-status"),
    )

    scenario.play(
        scene,
        post_event=fetch_unit_address,
    )
