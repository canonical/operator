import copy
from dataclasses import asdict, replace
from typing import Type

import pytest
from ops.charm import CharmBase, CharmEvents, CollectStatusEvent
from ops.framework import EventBase, Framework
from ops.model import ActiveStatus, UnknownStatus, WaitingStatus

from scenario.state import (
    _DEFAULT_JUJU_DATABAG,
    Address,
    BindAddress,
    Container,
    Model,
    Network,
    Relation,
    Resource,
    State,
)
from tests.helpers import jsonpatch_delta, sort_patch, trigger

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
    "pebble_custom_notice",
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

        def __init__(self, framework: Framework):
            super().__init__(framework)
            for evt in self.on.events().values():
                self.framework.observe(evt, self._on_event)

        def _on_event(self, event):
            if self._call:
                MyCharm.called = True
                MyCharm._call(self, event)

    return MyCharm


@pytest.fixture
def state():
    return State(config={"foo": "bar"}, leader=True)


def test_bare_event(state, mycharm):
    out = trigger(
        state,
        "start",
        mycharm,
        meta={"name": "foo"},
        config={"options": {"foo": {"type": "string"}}},
    )
    out_purged = replace(out, stored_states=state.stored_states)
    assert jsonpatch_delta(state, out_purged) == []


def test_leader_get(state, mycharm):
    def pre_event(charm):
        assert charm.unit.is_leader()

    trigger(
        state,
        "start",
        mycharm,
        meta={"name": "foo"},
        config={"options": {"foo": {"type": "string"}}},
        pre_event=pre_event,
    )


def test_status_setting(state, mycharm):
    def call(charm: CharmBase, e):
        if isinstance(e, CollectStatusEvent):
            return

        assert isinstance(charm.unit.status, UnknownStatus)
        charm.unit.status = ActiveStatus("foo test")
        charm.app.status = WaitingStatus("foo barz")

    mycharm._call = call
    out = trigger(
        state,
        "start",
        mycharm,
        meta={"name": "foo"},
        config={"options": {"foo": {"type": "string"}}},
    )
    assert out.unit_status == ActiveStatus("foo test")
    assert out.app_status == WaitingStatus("foo barz")
    assert out.workload_version == ""

    # ignore stored state in the delta
    out_purged = replace(out, stored_states=state.stored_states)
    assert jsonpatch_delta(out_purged, state) == sort_patch([
        {"op": "replace", "path": "/app_status/message", "value": "foo barz"},
        {"op": "replace", "path": "/app_status/name", "value": "waiting"},
        {"op": "replace", "path": "/unit_status/message", "value": "foo test"},
        {"op": "replace", "path": "/unit_status/name", "value": "active"},
    ])


@pytest.mark.parametrize("connect", (True, False))
def test_container(connect, mycharm):
    def pre_event(charm: CharmBase):
        container = charm.unit.get_container("foo")
        assert container is not None
        assert container.name == "foo"
        assert container.can_connect() is connect

    trigger(
        State(containers={Container(name="foo", can_connect=connect)}),
        "start",
        mycharm,
        meta={
            "name": "foo",
            "containers": {"foo": {"resource": "bar"}},
        },
        pre_event=pre_event,
    )


def test_relation_get(mycharm):
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

    state = State(
        relations={
            Relation(
                endpoint="foo",
                interface="bar",
                local_app_data={"a": "because"},
                remote_app_name="remote",
                remote_app_data={"a": "b"},
                local_unit_data={"c": "d"},
                remote_units_data={0: {}, 1: {"e": "f"}, 2: {}},
            )
        }
    )
    trigger(
        state,
        "start",
        mycharm,
        meta={
            "name": "local",
            "requires": {"foo": {"interface": "bar"}},
        },
        pre_event=pre_event,
    )


def test_relation_set(mycharm):
    def event_handler(charm: CharmBase, _):
        rel = charm.model.get_relation("foo")
        rel.data[charm.app]["a"] = "b"
        rel.data[charm.unit]["c"] = "d"

        # this will NOT raise an exception because we're not in an event context!
        # we're right before the event context is entered in fact.
        with pytest.raises(Exception):
            rel.data[rel.app]["a"] = "b"
        with pytest.raises(Exception):
            rel.data[charm.model.get_unit("remote/1")]["c"] = "d"

        assert charm.unit.is_leader()

    def pre_event(charm: CharmBase):
        assert charm.model.get_relation("foo")
        assert charm.model.app.planned_units() == 4

        # this would NOT raise an exception because we're not in an event context!
        # we're right before the event context is entered in fact.
        # with pytest.raises(Exception):
        #     rel.data[rel.app]["a"] = "b"
        # with pytest.raises(Exception):
        #     rel.data[charm.model.get_unit("remote/1")]["c"] = "d"

    mycharm._call = event_handler
    relation = Relation(
        endpoint="foo",
        interface="bar",
        remote_app_name="remote",
        remote_units_data={1: {}, 4: {}},
    )
    state = State(
        leader=True,
        planned_units=4,
        relations={relation},
    )

    assert not mycharm.called
    out = trigger(
        state,
        event="start",
        charm_type=mycharm,
        meta={
            "name": "foo",
            "requires": {"foo": {"interface": "bar"}},
        },
        pre_event=pre_event,
    )
    assert mycharm.called

    assert asdict(out.get_relation(relation.id)) == asdict(
        replace(
            relation,
            local_app_data={"a": "b"},
            local_unit_data={"c": "d", **_DEFAULT_JUJU_DATABAG},
        )
    )
    assert out.get_relation(relation.id).local_app_data == {"a": "b"}
    assert out.get_relation(relation.id).local_unit_data == {
        "c": "d",
        **_DEFAULT_JUJU_DATABAG,
    }


@pytest.mark.parametrize(
    "klass,num_args",
    [
        (State, (1,)),
        (Resource, (1,)),
        (Address, (0, 2)),
        (BindAddress, (0, 2)),
        (Network, (0, 3)),
    ],
)
def test_positional_arguments(klass, num_args):
    for num in num_args:
        args = (None,) * num
        with pytest.raises(TypeError):
            klass(*args)


def test_model_positional_arguments():
    with pytest.raises(TypeError):
        Model("", "")


def test_container_positional_arguments():
    with pytest.raises(TypeError):
        Container("", "")


def test_container_default_values():
    name = "foo"
    container = Container(name)
    assert container.name == name
    assert container.can_connect is False
    assert container.layers == {}
    assert container.service_statuses == {}
    assert container.mounts == {}
    assert container.execs == frozenset()
    assert container.layers == {}
    assert container._base_plan == {}


def test_state_default_values():
    state = State()
    assert state.config == {}
    assert state.relations == frozenset()
    assert state.networks == frozenset()
    assert state.containers == frozenset()
    assert state.storages == frozenset()
    assert state.opened_ports == frozenset()
    assert state.secrets == frozenset()
    assert state.resources == frozenset()
    assert state.deferred == []
    assert isinstance(state.model, Model)
    assert state.leader is False
    assert state.planned_units == 1
    assert state.app_status == UnknownStatus()
    assert state.unit_status == UnknownStatus()
    assert state.workload_version == ""


def test_deepcopy_state():
    containers = [Container("foo"), Container("bar")]
    state = State(containers=containers)
    state_copy = copy.deepcopy(state)
    for container in state.containers:
        copied_container = state_copy.get_container(container.name)
        assert container.name == copied_container.name


def test_replace_state():
    containers = [Container("foo"), Container("bar")]
    state = State(containers=containers, leader=True)
    state2 = replace(state, leader=False)
    assert state.leader != state2.leader
    assert state.containers == state2.containers
