from dataclasses import asdict
from typing import Type

import pytest
from ops.charm import CharmBase, CharmEvents
from ops.framework import EventBase, Framework
from ops.model import ActiveStatus, UnknownStatus, WaitingStatus

from scenario.state import Container, Relation, State, sort_patch
from tests.helpers import trigger

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
    out = trigger(state, "start", mycharm, meta={"name": "foo"})
    out_purged = out.replace(stored_state=state.stored_state)
    assert state.jsonpatch_delta(out_purged) == []


def test_leader_get(state, mycharm):
    def pre_event(charm):
        assert charm.unit.is_leader()

    trigger(
        state,
        "start",
        mycharm,
        meta={"name": "foo"},
        pre_event=pre_event,
    )


def test_status_setting(state, mycharm):
    def call(charm: CharmBase, _):
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
    out_purged = out.replace(stored_state=state.stored_state)
    assert out_purged.jsonpatch_delta(state) == sort_patch(
        [
            {"op": "replace", "path": "/app_status/message", "value": "foo barz"},
            {"op": "replace", "path": "/app_status/name", "value": "waiting"},
            {"op": "replace", "path": "/unit_status/message", "value": "foo test"},
            {"op": "replace", "path": "/unit_status/name", "value": "active"},
        ]
    )


@pytest.mark.parametrize("connect", (True, False))
def test_container(connect, mycharm):
    def pre_event(charm: CharmBase):
        container = charm.unit.get_container("foo")
        assert container is not None
        assert container.name == "foo"
        assert container.can_connect() is connect

    trigger(
        State(containers=[Container(name="foo", can_connect=connect)]),
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
        relations=[
            Relation(
                endpoint="foo",
                interface="bar",
                local_app_data={"a": "because"},
                remote_app_name="remote",
                remote_unit_ids=[0, 1, 2],
                remote_app_data={"a": "b"},
                local_unit_data={"c": "d"},
                remote_units_data={0: {}, 1: {"e": "f"}, 2: {}},
            )
        ]
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
    relation = Relation(
        endpoint="foo",
        interface="bar",
        remote_app_name="remote",
        remote_unit_ids=[1, 4],
        local_app_data={},
        local_unit_data={},
    )
    state = State(
        leader=True,
        relations=[relation],
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

    assert asdict(out.relations[0]) == asdict(
        relation.replace(
            local_app_data={"a": "b"},
            local_unit_data={"c": "d"},
        )
    )

    assert out.relations[0].local_app_data == {"a": "b"}
    assert out.relations[0].local_unit_data == {"c": "d"}
