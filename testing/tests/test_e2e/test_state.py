import copy
from dataclasses import asdict, replace
from typing import Any, Dict, Optional, Type

import ops
import pytest
from ops.charm import CharmBase, CharmEvents, CollectStatusEvent
from ops.framework import EventBase, Framework
from ops.model import ActiveStatus, UnknownStatus, WaitingStatus

from scenario.state import (
    _DEFAULT_JUJU_DATABAG,
    Address,
    BindAddress,
    CheckInfo,
    CloudCredential,
    CloudSpec,
    Container,
    Model,
    Network,
    Notice,
    PeerRelation,
    Relation,
    Resource,
    Secret,
    State,
    Storage,
    StoredState,
    SubordinateRelation,
    TCPPort,
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


def test_checkinfo_changeid_none():
    info = CheckInfo("foo", change_id=None)
    assert info.change_id, "None should result in a random change_id"
    info2 = CheckInfo("foo")  # None is also the default.
    assert info.change_id != info2.change_id


@pytest.mark.parametrize("id", ("", "28"))
def test_checkinfo_changeid(id: Optional[str]):
    info = CheckInfo("foo", change_id=ops.pebble.ChangeID(id))
    assert info.change_id == ops.pebble.ChangeID(id)


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


@pytest.mark.parametrize(
    "component,attribute,required_args",
    [
        (CloudCredential, "attributes", {"auth_type": "foo"}),
        (Secret, "tracked_content", {}),
        (Secret, "latest_content", {"tracked_content": {"password": "password"}}),
        (Secret, "remote_grants", {"tracked_content": {"password": "password"}}),
        (Relation, "local_app_data", {"endpoint": "foo"}),
        (Relation, "local_unit_data", {"endpoint": "foo"}),
        (Relation, "remote_app_data", {"endpoint": "foo"}),
        (SubordinateRelation, "local_app_data", {"endpoint": "foo"}),
        (SubordinateRelation, "local_unit_data", {"endpoint": "foo"}),
        (SubordinateRelation, "remote_app_data", {"endpoint": "foo"}),
        (SubordinateRelation, "remote_unit_data", {"endpoint": "foo"}),
        (PeerRelation, "local_app_data", {"endpoint": "foo"}),
        (PeerRelation, "local_unit_data", {"endpoint": "foo"}),
        (Notice, "last_data", {"key": "foo"}),
        (Container, "layers", {"name": "foo"}),
        (Container, "service_statuses", {"name": "foo"}),
        (Container, "mounts", {"name": "foo"}),
        (Container, "notices", {"name": "foo"}),
        (StoredState, "content", {}),
    ],
)
def test_immutable_content_dict(
    component: Type[object], attribute: str, required_args: Dict[str, Any]
):
    content = {"foo": "bar"}
    obj1 = component(**required_args, **{attribute: content})
    obj2 = component(**required_args, **{attribute: content})
    assert getattr(obj1, attribute) == getattr(obj2, attribute) == content
    assert getattr(obj1, attribute) is not getattr(obj2, attribute)
    content["baz"] = "qux"
    assert getattr(obj1, attribute) == getattr(obj2, attribute) == {"foo": "bar"}
    # This shouldn't be done in a charm test, since the attribute should be immutable,
    # but it's convenient to verify that the content is not connected.
    object.__setattr__(obj1, attribute, {"baz": "qux"})
    assert getattr(obj1, attribute) == {"baz": "qux"}
    assert getattr(obj2, attribute) == {"foo": "bar"}


@pytest.mark.parametrize(
    "component,attribute,required_args",
    [
        (CloudCredential, "redacted", {"auth_type": "foo"}),
        (CloudSpec, "ca_certificates", {"type": "foo"}),
        (BindAddress, "addresses", {}),
        (Network, "bind_addresses", {"binding_name": "foo"}),
        (Network, "ingress_addresses", {"binding_name": "foo"}),
        (Network, "egress_subnets", {"binding_name": "foo"}),
    ],
)
def test_immutable_content_list(
    component: Type[object], attribute: str, required_args: Dict[str, Any]
):
    content = ["foo", "bar"]
    obj1 = component(**required_args, **{attribute: content})
    obj2 = component(**required_args, **{attribute: content})
    assert getattr(obj1, attribute) == getattr(obj2, attribute) == content
    assert getattr(obj1, attribute) is not getattr(obj2, attribute)
    content.append("baz")
    assert getattr(obj1, attribute) == getattr(obj2, attribute) == ["foo", "bar"]
    # This shouldn't be done in a charm test, since the attribute should be immutable,
    # but it's convenient to verify that the content is not connected.
    object.__setattr__(obj1, attribute, ["baz", "qux"])
    assert getattr(obj1, attribute) == ["baz", "qux"]
    assert getattr(obj2, attribute) == ["foo", "bar"]


@pytest.mark.parametrize(
    "component,attribute,required_args",
    [
        (Relation, "remote_units_data", {"endpoint": "foo"}),
        (PeerRelation, "peers_data", {"endpoint": "foo"}),
    ],
)
def test_immutable_content_dict_of_dicts(
    component: Type[object], attribute: str, required_args: Dict[str, Any]
):
    content = {0: {"foo": "bar"}, 1: {"baz": "qux"}}
    obj1 = component(**required_args, **{attribute: content})
    obj2 = component(**required_args, **{attribute: content})
    assert getattr(obj1, attribute) == getattr(obj2, attribute) == content
    assert getattr(obj1, attribute) is not getattr(obj2, attribute)
    content[0]["baz"] = "quux"
    assert (
        getattr(obj1, attribute)
        == getattr(obj2, attribute)
        == {0: {"foo": "bar"}, 1: {"baz": "qux"}}
    )
    # This shouldn't be done in a charm test, since the attribute should be immutable,
    # but it's convenient to verify that the content is not connected.
    object.__setattr__(obj1, attribute, {0: {"foo": "qux"}})
    assert getattr(obj1, attribute) == {0: {"foo": "qux"}}
    assert getattr(obj2, attribute) == {0: {"foo": "bar"}, 1: {"baz": "qux"}}


@pytest.mark.parametrize(
    "obj_in,attribute,get_method,key_attr",
    [
        ({"foo": "bar"}, "config", "", ""),
        (Relation("rel"), "relations", "get_relation", "id"),
        (PeerRelation("peer"), "relations", "get_relation", "id"),
        (SubordinateRelation("sub"), "relations", "get_relation", "id"),
        (Network("foo"), "networks", "get_network", "binding_name"),
        (Container("foo"), "containers", "get_container", "name"),
        (Storage("foo"), "storages", "get_storage", "name"),
        (TCPPort(80), "opened_ports", "", ""),
        (Secret({"foo": "bar"}), "secrets", "", ""),
        (Resource(name="foo", path="bar"), "resources", "", ""),
        (StoredState(), "stored_states", "get_stored_state", "name"),
    ],
)
def test_state_immutable(
    obj_in, attribute: str, get_method: str, key_attr: str, mycharm
):
    state_in = State(**{attribute: obj_in if isinstance(obj_in, dict) else [obj_in]})

    state_out: State = trigger(
        state_in,
        event="start",
        charm_type=mycharm,
        meta={
            "name": "foo",
            "containers": {"foo": {"resource": "bar"}},
            "extra-bindings": {"foo": {}},
            "peers": {"peer": {"interface": "bar"}},
            "requires": {
                "rel": {"interface": "bar"},
                "sub": {"interface": "bar", "scope": "container"},
            },
            "resources": {"foo": {"type": "bar"}},
            "storage": {"foo": {"type": "file"}},
        },
        config={"options": {"foo": {"type": "string"}}},
    )

    if attribute == "config":
        # There's no State.get_config, we just get it directly.
        obj_out = state_out.config
    elif attribute == "opened_ports":
        # There's no State.get_opened_ports, because in a charm tests you just
        # want to assert the port is/is not in the set.
        obj_out = [p for p in state_out.opened_ports if p == obj_in][0]
    elif attribute == "secrets":
        # State.get_secret only takes keyword arguments, while the others take
        # only positional arguments.
        obj_out = state_out.get_secret(id=obj_in.id)
    elif attribute == "resources":
        # Charms can't change resources, so there's no State.get_resource.
        obj_out = [r for r in state_out.resources if r == obj_in][0]
    else:
        obj_out = getattr(state_out, get_method)(getattr(obj_in, key_attr))
    assert obj_in is not obj_out


@pytest.mark.parametrize(
    "relation_type",
    [
        Relation,
        PeerRelation,
        SubordinateRelation,
    ],
)
def test_state_immutable_with_changed_data_relation(relation_type, mycharm):
    def event_handler(charm: CharmBase, _):
        rel = charm.model.get_relation(relation_type.__name__)
        rel.data[charm.app]["a"] = "b"
        rel.data[charm.unit]["c"] = "d"

    mycharm._call = event_handler

    relation_in = relation_type(relation_type.__name__)

    state_in = State(relations={relation_in}, leader=True)

    state_out = trigger(
        state_in,
        event="start",
        charm_type=mycharm,
        meta={
            "name": "foo",
            "peers": {"PeerRelation": {"interface": "bar"}},
            "requires": {
                "Relation": {"interface": "bar"},
                "SubordinateRelation": {"interface": "bar", "scope": "container"},
            },
        },
    )

    relation_out = state_out.get_relation(relation_in.id)
    assert not relation_in.local_app_data
    assert relation_out.local_app_data == {"a": "b"}
    assert relation_out.local_unit_data == {"c": "d", **_DEFAULT_JUJU_DATABAG}


def test_state_immutable_with_changed_data_container(mycharm):
    layer_name = "my-layer"
    layer = ops.pebble.Layer({
        "services": {
            "foo": {
                "command": "bar",
                "override": "replace",
            },
        }
    })

    def event_handler(charm: CharmBase, _):
        container = charm.model.unit.get_container("foo")
        container.add_layer(layer_name, layer, combine=True)

    mycharm._call = event_handler

    container_in = Container("foo", can_connect=True)
    state_in = State(containers={container_in})

    state_out = trigger(
        state_in,
        event="start",
        charm_type=mycharm,
        meta={
            "name": "foo",
            "containers": {"foo": {"resource": "bar"}},
        },
    )

    container_out = state_out.get_container(container_in.name)
    assert not container_in.layers
    assert container_out.layers == {layer_name: layer}


def test_state_immutable_with_changed_data_ports(mycharm):
    def event_handler(charm: CharmBase, _):
        charm.model.unit.open_port(protocol="tcp", port=80)

    mycharm._call = event_handler

    state_in = State()
    state_out = trigger(
        state_in,
        event="start",
        charm_type=mycharm,
        meta={"name": "foo"},
    )

    assert not state_in.opened_ports
    assert state_out.opened_ports == {TCPPort(80)}


def test_state_immutable_with_changed_data_secret(mycharm):
    def event_handler(charm: CharmBase, _):
        secret = charm.model.get_secret(label="my-secret")
        secret.set_content({"password": "bar"})

    mycharm._call = event_handler

    secret_in = Secret({"password": "foo"}, label="my-secret", owner="unit")
    state_in = State(secrets={secret_in})

    state_out = trigger(
        state_in,
        event="start",
        charm_type=mycharm,
        meta={"name": "foo"},
    )

    secret_out = state_out.get_secret(id=secret_in.id)
    assert secret_in.latest_content == {"password": "foo"}
    assert secret_out.latest_content == {"password": "bar"}


def test_state_immutable_with_changed_data_stored_state():
    class MyCharm(ops.CharmBase):
        _stored = ops.StoredState()

        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            self._stored.set_default(seen=set())
            framework.observe(self.on.start, self._on_start)

        def _on_start(self, event: ops.StartEvent):
            self._stored.seen.add(str(event))

    stored_state_in = StoredState(owner_path="MyCharm")
    state_in = State(stored_states={stored_state_in})

    state_out = trigger(
        state_in,
        event="start",
        charm_type=MyCharm,
        meta={"name": "foo"},
    )

    stored_state_out = state_out.get_stored_state(
        stored_state_in.name, owner_path=stored_state_in.owner_path
    )
    assert not stored_state_in.content
    assert "seen" in stored_state_out.content
