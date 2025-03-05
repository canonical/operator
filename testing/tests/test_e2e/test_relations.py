from typing import Type

import pytest
from ops.charm import (
    CharmBase,
    CharmEvents,
    CollectStatusEvent,
    RelationBrokenEvent,
    RelationCreatedEvent,
    RelationDepartedEvent,
    RelationEvent,
)
from ops.framework import EventBase, Framework

from scenario import Context
from scenario.errors import UncaughtCharmError
from scenario.state import (
    _DEFAULT_JUJU_DATABAG,
    PeerRelation,
    Relation,
    RelationBase,
    State,
    StateValidationError,
    SubordinateRelation,
    _next_relation_id,
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
            relations={
                Relation(endpoint="foo", interface="foo", remote_app_name="remote"),
                Relation(endpoint="qux", interface="qux", remote_app_name="remote"),
            },
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
        pre_event=pre_event,
    )


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
            relations={
                relation,
            },
        ),
        f"relation_{evt_name}",
        mycharm,
        meta={
            "name": "local",
            "requires": {
                "foo": {"interface": "foo"},
            },
        },
    )


@pytest.mark.parametrize(
    "evt_name,has_unit",
    [
        ("changed", True),
        ("broken", False),
        ("departed", True),
        ("joined", True),
        ("created", False),
    ],
)
@pytest.mark.parametrize(
    "remote_app_name",
    ("remote", "prometheus", "aodeok123"),
)
@pytest.mark.parametrize(
    "remote_unit_id",
    (0, 1),
)
def test_relation_events_attrs(
    mycharm, evt_name, has_unit, remote_app_name, remote_unit_id
):
    relation = Relation(
        endpoint="foo", interface="foo", remote_app_name=remote_app_name
    )

    def callback(charm: CharmBase, event):
        if isinstance(event, CollectStatusEvent):
            return

        assert event.app
        if not isinstance(event, (RelationCreatedEvent, RelationBrokenEvent)):
            assert event.unit
        if isinstance(event, RelationDepartedEvent):
            assert event.departing_unit

    mycharm._call = callback

    ctx = Context(
        charm_type=mycharm,
        meta={
            "name": "local",
            "requires": {
                "foo": {"interface": "foo"},
            },
        },
    )
    state = State(relations={relation})
    kwargs = {}
    if has_unit:
        kwargs["remote_unit"] = remote_unit_id
    event = getattr(ctx.on, f"relation_{evt_name}")(relation, **kwargs)
    ctx.run(event, state=state)


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
        # .unit is always None for created and broken.
        if isinstance(event, (RelationCreatedEvent, RelationBrokenEvent)):
            assert event.unit is None
        else:
            assert event.unit
        assert (evt_name == "departed") is bool(getattr(event, "departing_unit", False))

    mycharm._call = callback

    trigger(
        State(
            relations={
                relation,
            },
        ),
        f"relation_{evt_name}",
        mycharm,
        meta={
            "name": "local",
            "requires": {
                "foo": {"interface": "foo"},
            },
        },
    )

    if evt_name not in ("created", "broken"):
        assert (
            "remote unit ID unset, and multiple remote unit IDs are present"
            in caplog.text
        )


def test_relation_default_unit_data_regular():
    relation = Relation("baz")
    assert relation.local_unit_data == _DEFAULT_JUJU_DATABAG
    assert relation.remote_units_data == {0: _DEFAULT_JUJU_DATABAG}


def test_relation_default_unit_data_sub():
    relation = SubordinateRelation("baz")
    assert relation.local_unit_data == _DEFAULT_JUJU_DATABAG
    assert relation.remote_unit_data == _DEFAULT_JUJU_DATABAG


def test_relation_default_unit_data_peer():
    relation = PeerRelation("baz")
    assert relation.local_unit_data == _DEFAULT_JUJU_DATABAG


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
            relations={
                relation,
            },
        ),
        f"relation_{evt_name}",
        mycharm,
        meta={
            "name": "local",
            "requires": {
                "foo": {"interface": "foo"},
            },
        },
    )

    if evt_name not in ("created", "broken"):
        assert "remote unit ID unset; no remote unit data present" in caplog.text


@pytest.mark.parametrize("data", (set(), {}, [], (), 1, 1.0, None, b""))
def test_relation_unit_data_bad_types(mycharm, data):
    with pytest.raises(StateValidationError):
        Relation(endpoint="foo", interface="foo", remote_units_data={0: {"a": data}})


@pytest.mark.parametrize("data", (set(), {}, [], (), 1, 1.0, None, b""))
def test_relation_app_data_bad_types(mycharm, data):
    with pytest.raises(StateValidationError):
        Relation(endpoint="foo", interface="foo", local_app_data={"a": data})


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
    trigger(
        State(relations={relation}),
        f"relation_{evt_name}",
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
        State(relations={sub1, sub2}),
        "update_status",
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
        assert rel.id == initial_id + i


def test_broken_relation_not_in_model_relations(mycharm):
    rel = Relation("foo")

    ctx = Context(
        mycharm, meta={"name": "local", "requires": {"foo": {"interface": "foo"}}}
    )
    with ctx(ctx.on.relation_broken(rel), state=State(relations={rel})) as mgr:
        charm = mgr.charm

        assert charm.model.get_relation("foo") is None
        assert charm.model.relations["foo"] == []


def test_get_relation_when_missing():
    class MyCharm(CharmBase):
        def __init__(self, framework):
            super().__init__(framework)
            self.framework.observe(self.on.update_status, self._on_update_status)
            self.framework.observe(self.on.config_changed, self._on_config_changed)
            self.relation = None

        def _on_update_status(self, _):
            self.relation = self.model.get_relation("foo")

        def _on_config_changed(self, _):
            self.relation = self.model.get_relation("foo", self.config["relation-id"])

    ctx = Context(
        MyCharm,
        meta={"name": "foo", "requires": {"foo": {"interface": "foo"}}},
        config={"options": {"relation-id": {"type": "int", "description": "foo"}}},
    )
    # There should be no error if the relation is missing - get_relation returns
    # None in that case.
    with ctx(ctx.on.update_status(), State()) as mgr:
        mgr.run()
        assert mgr.charm.relation is None

    # There should also be no error if the relation is present, of course.
    rel = Relation("foo")
    with ctx(ctx.on.update_status(), State(relations={rel})) as mgr:
        mgr.run()
        assert mgr.charm.relation.id == rel.id

    # If a relation that doesn't exist is requested, that should also not raise
    # an error.
    with ctx(ctx.on.config_changed(), State(config={"relation-id": 42})) as mgr:
        mgr.run()
        rel = mgr.charm.relation
        assert rel.id == 42
        assert not rel.active

    # If there's no defined relation with the name, then get_relation raises KeyError.
    ctx = Context(MyCharm, meta={"name": "foo"})
    with pytest.raises(UncaughtCharmError) as exc:
        ctx.run(ctx.on.update_status(), State())
    assert isinstance(exc.value.__cause__, KeyError)


@pytest.mark.parametrize("klass", (Relation, PeerRelation, SubordinateRelation))
def test_relation_positional_arguments(klass):
    with pytest.raises(TypeError):
        klass("foo", "bar", None)


def test_relation_default_values():
    expected_id = _next_relation_id(update=False)
    endpoint = "database"
    interface = "postgresql"
    relation = Relation(endpoint, interface)
    assert relation.id == expected_id
    assert relation.endpoint == endpoint
    assert relation.interface == interface
    assert relation.local_app_data == {}
    assert relation.local_unit_data == _DEFAULT_JUJU_DATABAG
    assert relation.remote_app_name == "remote"
    assert relation.limit == 1
    assert relation.remote_app_data == {}
    assert relation.remote_units_data == {0: _DEFAULT_JUJU_DATABAG}


def test_subordinate_relation_default_values():
    expected_id = _next_relation_id(update=False)
    endpoint = "database"
    interface = "postgresql"
    relation = SubordinateRelation(endpoint, interface)
    assert relation.id == expected_id
    assert relation.endpoint == endpoint
    assert relation.interface == interface
    assert relation.local_app_data == {}
    assert relation.local_unit_data == _DEFAULT_JUJU_DATABAG
    assert relation.remote_app_name == "remote"
    assert relation.remote_unit_id == 0
    assert relation.remote_app_data == {}
    assert relation.remote_unit_data == _DEFAULT_JUJU_DATABAG


def test_peer_relation_default_values():
    expected_id = _next_relation_id(update=False)
    endpoint = "peers"
    interface = "shared"
    relation = PeerRelation(endpoint, interface)
    assert relation.id == expected_id
    assert relation.endpoint == endpoint
    assert relation.interface == interface
    assert relation.local_app_data == {}
    assert relation.local_unit_data == _DEFAULT_JUJU_DATABAG
    assert relation.peers_data == {0: _DEFAULT_JUJU_DATABAG}
