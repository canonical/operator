from dataclasses import asdict
from typing import Optional, Type

import pytest
from ops.charm import CharmBase, CharmEvents, StartEvent
from ops.framework import EventBase, Framework
from ops.model import ActiveStatus, UnknownStatus, WaitingStatus

from scenario.scenario import Scenario
from scenario.structs import (
    CharmSpec,
    ContainerSpec,
    Scene,
    State,
    event,
    relation,
    sort_patch,
)


@pytest.fixture(scope="function")
def mycharm():
    class MyCharmEvents(CharmEvents):
        @classmethod
        def define_event(cls, event_kind: str, event_type: "Type[EventBase]"):
            if getattr(cls, event_kind, None):
                delattr(cls, event_kind)
            return super().define_event(event_kind, event_type)

    class MyCharm(CharmBase):
        _call = None
        called = False
        on = MyCharmEvents()

        def __init__(self, framework: Framework):
            super().__init__(framework)
            for evt in self.on.events().values():
                self.framework.observe(evt, self._on_event)

        def _on_event(self, event):
            if self._call:
                MyCharm.called = True
                MyCharm._call(self, event)

    return MyCharm


@pytest.fixture(scope="function")
def start_scene():
    return Scene(event("start"), state=State(config={"foo": "bar"}, leader=True))


def test_get_relation(start_scene: Scene, mycharm):
    def pre_event(charm: CharmBase):
        assert charm.model.get_relation("foo")
        assert charm.model.get_relation("bar") is None
        assert charm.model.get_relation("qux")
        assert charm.model.get_relation("zoo") is None

    scenario = Scenario(
        CharmSpec(
            mycharm,
            meta={
                "name": "local",
                "requires": {
                    "foo": {"interface": "foo"},
                    "bar": {"interface": "bar"},
                },
                "provides": {
                    "qux": {"interface": "qux"},
                    "zoo": {"interface": "zoo"},
                },
            },
        )
    )
    scene = start_scene.copy()
    scene.state.relations = [
        relation(
            endpoint="foo",
            interface="foo"
        ),
        relation(
            endpoint="qux",
            interface="qux"
        ),
    ]
    scenario.play(scene, pre_event=pre_event)
