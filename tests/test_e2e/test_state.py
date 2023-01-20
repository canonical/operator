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

# from tests.setup_tests import setup_tests
#
# setup_tests()  # noqa & keep this on top


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
        called = False
        on = MyCharmEvents()

        def __init__(self, framework: Framework, key: Optional[str] = None):
            super().__init__(framework, key)
            for evt in self.on.events().values():
                self.framework.observe(evt, self._on_event)

        def _on_event(self, event):
            if self._call:
                MyCharm.called = True
                MyCharm._call(self, event)

    return MyCharm


@pytest.fixture
def dummy_state():
    return State(config={"foo": "bar"}, leader=True)


@pytest.fixture(scope="function")
def start_scene(dummy_state):
    return Scene(event("start"), state=dummy_state)


@pytest.fixture(scope="function")
def scenario(mycharm):
    return Scenario(CharmSpec(mycharm, meta={"name": "foo"}))


def test_bare_event(start_scene, mycharm):
    scenario = Scenario(CharmSpec(mycharm, meta={"name": "foo"}))
    out = scenario.play(scene=start_scene)
    out.juju_log = []  # ignore logging output in the delta
    assert start_scene.state.delta(out) == []


def test_leader_get(start_scene, mycharm):
    def pre_event(charm):
        assert charm.unit.is_leader()

    scenario = Scenario(CharmSpec(mycharm, meta={"name": "foo"}))
    scenario.play(start_scene, pre_event=pre_event)


def test_status_setting(start_scene, mycharm):
    def call(charm: CharmBase, _):
        assert isinstance(charm.unit.status, UnknownStatus)
        charm.unit.status = ActiveStatus("foo test")
        charm.app.status = WaitingStatus("foo barz")

    mycharm._call = call
    scenario = Scenario(CharmSpec(mycharm, meta={"name": "foo"}))
    out = scenario.play(start_scene)
    assert out.status.unit == ("active", "foo test")
    assert out.status.app == ("waiting", "foo barz")
    assert out.status.app_version == ""

    out.juju_log = []  # ignore logging output in the delta
    assert out.delta(start_scene.state) == sort_patch(
        [
            {
                "op": "replace",
                "path": "/status/app",
                "value": ("waiting", "foo barz"),
            },
            {
                "op": "replace",
                "path": "/status/unit",
                "value": ("active", "foo test"),
            },
        ]
    )


@pytest.mark.parametrize("connect", (True, False))
def test_container(start_scene: Scene, connect, mycharm):
    def pre_event(charm: CharmBase):
        container = charm.unit.get_container("foo")
        assert container is not None
        assert container.name == "foo"
        assert container.can_connect() is connect

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
    scene.state.containers = (ContainerSpec(name="foo", can_connect=connect),)
    scenario.play(scene, pre_event=pre_event)


def test_relation_get(start_scene: Scene, mycharm):
    def pre_event(charm: CharmBase):
        rel = charm.model.get_relation("foo")
        assert rel is not None
        assert rel.data[charm.app]["a"] == "because"

        assert rel.data[rel.app]["a"] == "b"
        assert rel.data[charm.unit]["c"] == "d"

        for unit in rel.units:
            if unit is charm.unit:
                continue
            if unit.name == "remote/1":
                assert rel.data[unit]["e"] == "f"
            else:
                assert not rel.data[unit]

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
    scene.state.relations = [
        relation(
            endpoint="foo",
            interface="bar",
            local_app_data={"a": "because"},
            remote_app_name="remote",
            remote_unit_ids=[0, 1, 2],
            remote_app_data={"a": "b"},
            local_unit_data={"c": "d"},
            remote_units_data={0: {}, 1: {"e": "f"}, 2: {}},
        ),
    ]
    scenario.play(scene, pre_event=pre_event)


def test_relation_set(start_scene: Scene, mycharm):
    def event_handler(charm: CharmBase, _):
        rel = charm.model.get_relation("foo")
        rel.data[charm.app]["a"] = "b"
        rel.data[charm.unit]["c"] = "d"

        # this will NOT raise an exception because we're not in an event context!
        # we're right before the event context is entered in fact.
        # todo: how do we warn against the user abusing pre/post_event to mess with an unguarded state?
        with pytest.raises(Exception):
            rel.data[rel.app]["a"] = "b"
        with pytest.raises(Exception):
            rel.data[charm.model.get_unit("remote/1")]["c"] = "d"

        assert charm.unit.is_leader()

    def pre_event(charm: CharmBase):
        assert charm.model.get_relation("foo")

        # this would NOT raise an exception because we're not in an event context!
        # we're right before the event context is entered in fact.
        # todo: how do we warn against the user abusing pre/post_event to mess with an unguarded state?
        # with pytest.raises(Exception):
        #     rel.data[rel.app]["a"] = "b"
        # with pytest.raises(Exception):
        #     rel.data[charm.model.get_unit("remote/1")]["c"] = "d"

    mycharm._call = event_handler
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

    scene.state.leader = True
    scene.state.relations = [
        relation(
            endpoint="foo",
            interface="bar",
            remote_unit_ids=[1, 4],
            local_app_data={},
            local_unit_data={},
        )
    ]

    assert not mycharm.called
    out = scenario.play(scene, pre_event=pre_event)
    assert mycharm.called

    assert asdict(out.relations[0]) == asdict(
        relation(
            endpoint="foo",
            interface="bar",
            remote_unit_ids=[1, 4],
            local_app_data={"a": "b"},
            local_unit_data={"c": "d"},
        )
    )

    assert out.relations[0].local_app_data == {"a": "b"}
    assert out.relations[0].local_unit_data == {"c": "d"}
