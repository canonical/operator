from tests.setup_tests import setup_tests

setup_tests()  # noqa & keep this on top

from typing import Optional

import pytest
from ops.charm import CharmBase, StartEvent
from ops.framework import Framework
from ops.model import ActiveStatus, UnknownStatus

from scenario.scenario import Scenario
from scenario.structs import CharmSpec, Context, Scene, State, get_event


class MyCharm(CharmBase):
    _call = None

    def __init__(self, framework: Framework, key: Optional[str] = None):
        super().__init__(framework, key)
        self.called = False

        if self._call:
            self.called = True
            self._call()


@pytest.fixture
def dummy_state():
    return State(config={"foo": "bar"}, leader=True)


@pytest.fixture
def start_scene(dummy_state):
    return Scene(get_event("start"), context=Context(state=dummy_state))


def test_bare_event(start_scene):
    MyCharm._call = lambda charm: True
    scenario = Scenario(CharmSpec(MyCharm, meta={"name": "foo"}))
    out = scenario.run(start_scene)

    assert isinstance(out.charm, MyCharm)
    assert out.charm.called
    assert isinstance(out.event, StartEvent)
    assert out.charm.unit.name == "foo/0"
    assert out.charm.model.uuid == start_scene.context.state.model.uuid


def test_leader_get(start_scene):
    def call(charm):
        assert charm.unit.is_leader()

    MyCharm._call = call
    scenario = Scenario(CharmSpec(MyCharm, meta={"name": "foo"}))
    scenario.run(start_scene)


def test_status_setting(start_scene):
    def call(charm):
        assert isinstance(charm.unit.status, UnknownStatus)
        charm.unit.status = ActiveStatus("foo test")

    MyCharm._call = call
    scenario = Scenario(CharmSpec(MyCharm, meta={"name": "foo"}))
    out = scenario.run(start_scene)
    assert out.context_out.state.status.unit == ("active", "foo test")
    assert out.context_out.state.status.app == ("unknown", "")
    assert out.delta().patch == [
        {"op": "replace", "path": "/state/status/unit", "value": ("active", "foo test")}
    ]
