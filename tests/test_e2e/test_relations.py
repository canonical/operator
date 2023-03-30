import os
from typing import Type

import pytest
from ops.charm import CharmBase, CharmEvents, RelationDepartedEvent
from ops.framework import EventBase, Framework

from scenario.runtime import InconsistentScenarioError
from scenario.state import (
    PeerRelation,
    Relation,
    RelationType,
    State,
    StateValidationError,
    SubordinateRelation,
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


def test_get_relation(mycharm):
    def pre_event(charm: CharmBase):
        assert charm.model.get_relation("foo")
        assert charm.model.get_relation("bar") is None
        assert charm.model.get_relation("qux")
        assert charm.model.get_relation("zoo") is None

    State(
        config={"foo": "bar"},
        leader=True,
        relations=[
            Relation(endpoint="foo", interface="foo", remote_app_name="remote"),
            Relation(endpoint="qux", interface="qux", remote_app_name="remote"),
        ],
    ).trigger(
        "start",
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
        config={"options": {"foo": {"type": "string"}}},
    )


@pytest.mark.parametrize(
    "evt_name", ("changed", "broken", "departed", "joined", "created")
)
def test_relation_events(mycharm, evt_name):
    relation = Relation(endpoint="foo", interface="foo", remote_app_name="remote")

    mycharm._call = lambda self, evt: None

    State(
        relations=[
            relation,
        ],
    ).trigger(
        getattr(relation, f"{evt_name}_event"),
        mycharm,
        meta={
            "name": "local",
            "requires": {
                "foo": {"interface": "foo"},
            },
        },
    )

    assert mycharm.called


@pytest.mark.parametrize(
    "evt_name",
    ("changed", "broken", "departed", "joined", "created"),
)
@pytest.mark.parametrize(
    "remote_app_name",
    ("remote", "prometheus", "aodeok123"),
)
def test_relation_events(mycharm, evt_name, remote_app_name):
    relation = Relation(
        endpoint="foo", interface="foo", remote_app_name=remote_app_name
    )

    def callback(charm: CharmBase, _):
        assert charm.model.get_relation("foo").app.name == remote_app_name

    mycharm._call = callback

    State(
        relations=[
            relation,
        ],
    ).trigger(
        getattr(relation, f"{evt_name}_event"),
        mycharm,
        meta={
            "name": "local",
            "requires": {
                "foo": {"interface": "foo"},
            },
        },
    )


@pytest.mark.parametrize(
    "evt_name",
    ("changed", "broken", "departed", "joined", "created"),
)
@pytest.mark.parametrize(
    "remote_app_name",
    ("remote", "prometheus", "aodeok123"),
)
@pytest.mark.parametrize(
    "remote_unit_id",
    (0, 1),
)
def test_relation_events_attrs(mycharm, evt_name, remote_app_name, remote_unit_id):
    relation = Relation(
        endpoint="foo", interface="foo", remote_app_name=remote_app_name
    )

    def callback(charm: CharmBase, event):
        assert event.app
        assert event.unit
        if isinstance(event, RelationDepartedEvent):
            assert event.departing_unit

    mycharm._call = callback

    State(
        relations=[
            relation,
        ],
    ).trigger(
        getattr(relation, f"{evt_name}_event")(remote_unit=remote_unit_id),
        mycharm,
        meta={
            "name": "local",
            "requires": {
                "foo": {"interface": "foo"},
            },
        },
    )


@pytest.mark.parametrize(
    "evt_name",
    ("changed", "broken", "departed", "joined", "created"),
)
@pytest.mark.parametrize(
    "remote_app_name",
    ("remote", "prometheus", "aodeok123"),
)
def test_relation_events_no_attrs(mycharm, evt_name, remote_app_name, caplog):
    relation = Relation(
        endpoint="foo",
        interface="foo",
        remote_app_name=remote_app_name,
        remote_units_data={0: {}, 1: {}},  # 2 units
    )

    def callback(charm: CharmBase, event):
        assert event.app  # that's always present
        assert not event.unit
        assert not getattr(event, "departing_unit", False)

    mycharm._call = callback

    State(
        relations=[
            relation,
        ],
    ).trigger(
        getattr(relation, f"{evt_name}_event"),
        mycharm,
        meta={
            "name": "local",
            "requires": {
                "foo": {"interface": "foo"},
            },
        },
    )

    assert "unable to determine remote unit ID" in caplog.text


@pytest.mark.parametrize("data", (set(), {}, [], (), 1, 1.0, None, b""))
def test_relation_unit_data_bad_types(mycharm, data):
    with pytest.raises(StateValidationError):
        relation = Relation(
            endpoint="foo", interface="foo", remote_units_data={0: {"a": data}}
        )


@pytest.mark.parametrize("data", (set(), {}, [], (), 1, 1.0, None, b""))
def test_relation_app_data_bad_types(mycharm, data):
    with pytest.raises(StateValidationError):
        relation = Relation(endpoint="foo", interface="foo", local_app_data={"a": data})


@pytest.mark.parametrize(
    "relation, expected_type",
    (
        (Relation("a"), RelationType.regular),
        (PeerRelation("b"), RelationType.peer),
        (SubordinateRelation("b"), RelationType.subordinate),
    ),
)
def test_relation_type(relation, expected_type):
    assert relation.__type__ == expected_type


@pytest.mark.parametrize(
    "evt_name",
    ("changed", "broken", "departed", "joined", "created"),
)
@pytest.mark.parametrize(
    "relation",
    (Relation("a"), PeerRelation("b"), SubordinateRelation("b")),
)
def test_relation_event_trigger(relation, evt_name, mycharm):
    meta = {
        "name": "mycharm",
        "requires": {"a": {"interface": "i1"}},
        "provides": {
            "c": {
                "interface": "i3",
                # this is a subordinate relation.
                "scope": "container",
            }
        },
        "peers": {"b": {"interface": "i2"}},
    }
    state = State(relations=[relation]).trigger(
        getattr(relation, evt_name + "_event"), mycharm, meta=meta
    )
