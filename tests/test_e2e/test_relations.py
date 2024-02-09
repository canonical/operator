from typing import Type

import pytest
from ops.charm import (
    CharmBase,
    CharmEvents,
    CollectStatusEvent,
    RelationDepartedEvent,
    RelationEvent,
)
from ops.framework import EventBase, Framework

from scenario import Context
from scenario.state import (
    DEFAULT_JUJU_DATABAG,
    PeerRelation,
    Relation,
    RelationBase,
    State,
    StateValidationError,
    SubordinateRelation,
)
from tests.helpers import trigger


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

    trigger(
        State(
            config={"foo": "bar"},
            leader=True,
            relations=[
                Relation(endpoint="foo", interface="foo", remote_app_name="remote"),
                Relation(endpoint="qux", interface="qux", remote_app_name="remote"),
            ],
        ),
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

    trigger(
        State(
            relations=[
                relation,
            ],
        ),
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

    def callback(charm: CharmBase, e):
        if not isinstance(e, RelationEvent):
            return  # filter out collect status events

        if evt_name == "broken":
            assert charm.model.get_relation("foo") is None
            assert e.relation.app.name == remote_app_name
        else:
            assert charm.model.get_relation("foo").app.name == remote_app_name

    mycharm._call = callback

    trigger(
        State(
            relations=[
                relation,
            ],
        ),
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
        if isinstance(event, CollectStatusEvent):
            return

        assert event.app
        assert event.unit
        if isinstance(event, RelationDepartedEvent):
            assert event.departing_unit

    mycharm._call = callback

    trigger(
        State(
            relations=[
                relation,
            ],
        ),
        getattr(relation, f"{evt_name}_event")(remote_unit_id=remote_unit_id),
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
        if isinstance(event, CollectStatusEvent):
            return

        assert event.app  # that's always present
        assert event.unit
        assert (evt_name == "departed") is bool(getattr(event, "departing_unit", False))

    mycharm._call = callback

    trigger(
        State(
            relations=[
                relation,
            ],
        ),
        getattr(relation, f"{evt_name}_event"),
        mycharm,
        meta={
            "name": "local",
            "requires": {
                "foo": {"interface": "foo"},
            },
        },
    )

    assert (
        "remote unit ID unset, and multiple remote unit IDs are present" in caplog.text
    )


def test_relation_default_unit_data_regular():
    relation = Relation("baz")
    assert relation.local_unit_data == DEFAULT_JUJU_DATABAG
    assert relation.remote_units_data == {0: DEFAULT_JUJU_DATABAG}


def test_relation_default_unit_data_sub():
    relation = SubordinateRelation("baz")
    assert relation.local_unit_data == DEFAULT_JUJU_DATABAG
    assert relation.remote_unit_data == DEFAULT_JUJU_DATABAG


def test_relation_default_unit_data_peer():
    relation = PeerRelation("baz")
    assert relation.local_unit_data == DEFAULT_JUJU_DATABAG


@pytest.mark.parametrize(
    "evt_name",
    ("changed", "broken", "departed", "joined", "created"),
)
def test_relation_events_no_remote_units(mycharm, evt_name, caplog):
    relation = Relation(
        endpoint="foo",
        interface="foo",
        remote_units_data={},  # no units
    )

    def callback(charm: CharmBase, event):
        if isinstance(event, CollectStatusEvent):
            return

        assert event.app  # that's always present
        assert not event.unit

    mycharm._call = callback

    trigger(
        State(
            relations=[
                relation,
            ],
        ),
        getattr(relation, f"{evt_name}_event"),
        mycharm,
        meta={
            "name": "local",
            "requires": {
                "foo": {"interface": "foo"},
            },
        },
    )

    assert "remote unit ID unset; no remote unit data present" in caplog.text


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
    "evt_name",
    ("changed", "broken", "departed", "joined", "created"),
)
@pytest.mark.parametrize(
    "relation",
    (Relation("a"), PeerRelation("b"), SubordinateRelation("c")),
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
    state = trigger(
        State(relations=[relation]),
        getattr(relation, evt_name + "_event"),
        mycharm,
        meta=meta,
    )


def test_trigger_sub_relation(mycharm):
    meta = {
        "name": "mycharm",
        "provides": {
            "foo": {
                "interface": "bar",
                # this is a subordinate relation.
                "scope": "container",
            }
        },
    }

    sub1 = SubordinateRelation(
        "foo", remote_unit_data={"1": "2"}, remote_app_name="primary1"
    )
    sub2 = SubordinateRelation(
        "foo", remote_unit_data={"3": "4"}, remote_app_name="primary2"
    )

    def post_event(charm: CharmBase):
        b_relations = charm.model.relations["foo"]
        assert len(b_relations) == 2
        for relation in b_relations:
            assert len(relation.units) == 1

    trigger(
        State(relations=[sub1, sub2]),
        "update-status",
        mycharm,
        meta=meta,
        post_event=post_event,
    )


def test_cannot_instantiate_relationbase():
    with pytest.raises(RuntimeError):
        RelationBase("")


def test_relation_ids():
    from scenario.state import _next_relation_id_counter

    initial_id = _next_relation_id_counter
    for i in range(10):
        rel = Relation("foo")
        assert rel.relation_id == initial_id + i


def test_broken_relation_not_in_model_relations(mycharm):
    rel = Relation("foo")

    with Context(
        mycharm, meta={"name": "local", "requires": {"foo": {"interface": "foo"}}}
    ).manager(rel.broken_event, state=State(relations=[rel])) as mgr:
        charm = mgr.charm

        assert charm.model.get_relation("foo") is None
        assert charm.model.relations["foo"] == []
