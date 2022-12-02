from dataclasses import asdict

from tests.setup_tests import setup_tests

setup_tests()  # noqa & keep this on top

from typing import Optional, Type

import pytest
from ops.charm import CharmBase, CharmEvents, StartEvent
from ops.framework import EventBase, Framework
from ops.model import ActiveStatus, UnknownStatus, WaitingStatus

from scenario.scenario import Scenario
from scenario.structs import (
    CharmSpec,
    ContainerSpec,
    Context,
    Scene,
    State,
    event,
    relation,
)

CUSTOM_EVT_SUFFIXES = {
    "relation_created",
    "relation_joined",
    "relation_changed",
    "relation_departed",
    "relation_broken",
    "storage_attached",
    "storage_detaching",
    "action",
    "pebble_ready",
}


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
        on = MyCharmEvents()

        def __init__(self, framework: Framework, key: Optional[str] = None):
            super().__init__(framework, key)
            self.called = False

            for evt in self.on.events().values():
                self.framework.observe(evt, self._on_event)

        def _on_event(self, event):
            if self._call:
                self.called = True
                self._call(event)

    return MyCharm


@pytest.fixture
def dummy_state():
    return State(
        config={"foo": "bar"},
        leader=True
    )


@pytest.fixture
def start_scene(dummy_state):
    return Scene(
        event("start"),
        context=Context(
            state=dummy_state
        )
    )


def test_bare_event(start_scene, mycharm):
    mycharm._call = lambda *_: True
    scenario = Scenario(CharmSpec(mycharm, meta={"name": "foo"}))
    out = scenario.run(start_scene)

    assert isinstance(out.charm, mycharm)
    assert out.charm.called
    assert isinstance(out.event, StartEvent)
    assert out.charm.unit.name == "foo/0"
    assert out.charm.model.uuid == start_scene.context.state.model.uuid


def test_leader_get(start_scene, mycharm):
    def call(charm, _):
        assert charm.unit.is_leader()

    mycharm._call = call
    scenario = Scenario(CharmSpec(mycharm, meta={"name": "foo"}))
    scenario.run(start_scene)


def test_status_setting(start_scene, mycharm):
    def call(charm: CharmBase, _):
        assert isinstance(charm.unit.status, UnknownStatus)
        charm.unit.status = ActiveStatus("foo test")
        charm.app.status = WaitingStatus("foo barz")

    mycharm._call = call
    scenario = Scenario(CharmSpec(mycharm, meta={"name": "foo"}))
    out = scenario.run(start_scene)
    assert out.context_out.state.status.unit == ("active", "foo test")
    assert out.context_out.state.status.app == ("waiting", "foo barz")
    assert out.context_out.state.status.app_version == ""
    assert out.delta() == out.sort_patch(
        [
            {
                "op": "replace",
                "path": "/state/status/app",
                "value": ("waiting", "foo barz"),
            },
            {
                "op": "replace",
                "path": "/state/status/unit",
                "value": ("active", "foo test"),
            },
        ]
    )


@pytest.mark.parametrize("connect", (True, False))
def test_container(start_scene: Scene, connect, mycharm):
    def call(charm: CharmBase, _):
        container = charm.unit.get_container("foo")
        assert container is not None
        assert container.name == "foo"
        assert container.can_connect() is connect

    mycharm._call = call
    scenario = Scenario(
        CharmSpec(
            mycharm,
            meta={
                "name": "foo",
                "containers": {"foo": {"resource": "bar"}},
            },
        )
    )
    scene = start_scene.copy()
    scene.context.state.containers = (ContainerSpec(name="foo", can_connect=connect),)
    scenario.run(scene)


def test_relation_get(start_scene: Scene, mycharm):
    def call(charm: CharmBase, _):
        rel = charm.model.get_relation("foo")
        assert rel is not None
        assert rel.data[charm.app]["a"] == "because"
        assert rel.data[rel.app]["a"] == "b"
        assert not rel.data[charm.unit]  # empty

    mycharm._call = call

    scenario = Scenario(
        CharmSpec(
            mycharm,
            meta={
                "name": "local",
                "requires": {"foo": {"interface": "bar"}},
            },
        )
    )
    scene = start_scene.copy()
    scene.context.state.relations = [
        relation(
            endpoint="foo",
            interface="bar",
            local_app_data={"a": "because"},
            remote_app_name="remote",
            remote_unit_ids=[0, 1, 2],
            remote_app_data={"a": "b"},
            local_unit_data={"c": "d"},
        ),
    ]
    scenario.run(scene)


def test_relation_set(start_scene: Scene, mycharm):
    def call(charm: CharmBase, _):
        rel = charm.model.get_relation("foo")
        rel.data[charm.app]["a"] = "b"
        rel.data[charm.unit]["c"] = "d"

        with pytest.raises(Exception):
            rel.data[rel.app]["a"] = "b"
        with pytest.raises(Exception):
            rel.data[charm.model.get_unit("remote/1")]["c"] = "d"

    mycharm._call = call

    scenario = Scenario(
        CharmSpec(
            mycharm,
            meta={
                "name": "foo",
                "requires": {"foo": {"interface": "bar"}},
            },
        )
    )
    scene = start_scene.copy()
    scene.context.state.relations = [  # we could also append...
        relation(
            endpoint="foo",
            interface="bar",
            remote_unit_ids=[1, 4],
            local_app_data={},
            local_unit_data={},
        )
    ]
    out = scenario.run(scene)

    assert asdict(out.context_out.state.relations[0]) == \
           asdict(
               relation(
                   endpoint="foo",
                   interface="bar",
                   remote_unit_ids=[1, 4],
                   local_app_data={"a": "b"},
                   local_unit_data={"c": "d"},
               )
           )

    assert out.context_out.state.relations[0].local_app_data == {"a": "b"}
    assert out.context_out.state.relations[0].local_unit_data == {"c": "d"}
    assert out.delta() == out.sort_patch(
        [
            {"op": "add", "path": "/state/relations/0/local_app_data/a", "value": "b"},
            {"op": "add", "path": "/state/relations/0/local_unit_data/c", "value": "d"},
        ]
    )
