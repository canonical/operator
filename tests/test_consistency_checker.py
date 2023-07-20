import pytest
from ops.charm import CharmBase

from scenario.consistency_checker import check_consistency
from scenario.runtime import InconsistentScenarioError
from scenario.state import (
    RELATION_EVENTS_SUFFIX,
    Action,
    Container,
    Event,
    PeerRelation,
    Relation,
    Secret,
    State,
    SubordinateRelation,
    _CharmSpec,
)


class MyCharm(CharmBase):
    pass


def assert_inconsistent(
    state: "State",
    event: "Event",
    charm_spec: "_CharmSpec",
    juju_version="3.0",
):
    with pytest.raises(InconsistentScenarioError):
        check_consistency(state, event, charm_spec, juju_version)


def assert_consistent(
    state: "State",
    event: "Event",
    charm_spec: "_CharmSpec",
    juju_version="3.0",
):
    check_consistency(state, event, charm_spec, juju_version)


def test_base():
    state = State()
    event = Event("update_status")
    spec = _CharmSpec(MyCharm, {})
    assert_consistent(state, event, spec)


def test_workload_event_without_container():
    assert_inconsistent(
        State(),
        Event("foo-pebble-ready", container=Container("foo")),
        _CharmSpec(MyCharm, {}),
    )
    assert_consistent(
        State(containers=[Container("foo")]),
        Event("foo-pebble-ready", container=Container("foo")),
        _CharmSpec(MyCharm, {"containers": {"foo": {}}}),
    )


def test_container_meta_mismatch():
    assert_inconsistent(
        State(containers=[Container("bar")]),
        Event("foo"),
        _CharmSpec(MyCharm, {"containers": {"baz": {}}}),
    )
    assert_consistent(
        State(containers=[Container("bar")]),
        Event("foo"),
        _CharmSpec(MyCharm, {"containers": {"bar": {}}}),
    )


def test_container_in_state_but_no_container_in_meta():
    assert_inconsistent(
        State(containers=[Container("bar")]),
        Event("foo"),
        _CharmSpec(MyCharm, {}),
    )
    assert_consistent(
        State(containers=[Container("bar")]),
        Event("foo"),
        _CharmSpec(MyCharm, {"containers": {"bar": {}}}),
    )


def test_evt_bad_container_name():
    assert_inconsistent(
        State(),
        Event("foo-pebble-ready", container=Container("bar")),
        _CharmSpec(MyCharm, {}),
    )
    assert_consistent(
        State(containers=[Container("bar")]),
        Event("bar-pebble-ready", container=Container("bar")),
        _CharmSpec(MyCharm, {"containers": {"bar": {}}}),
    )


@pytest.mark.parametrize("suffix", RELATION_EVENTS_SUFFIX)
def test_evt_bad_relation_name(suffix):
    assert_inconsistent(
        State(),
        Event(f"foo{suffix}", relation=Relation("bar")),
        _CharmSpec(MyCharm, {"requires": {"foo": {"interface": "xxx"}}}),
    )
    assert_consistent(
        State(relations=[Relation("bar")]),
        Event(f"bar{suffix}", relation=Relation("bar")),
        _CharmSpec(MyCharm, {"requires": {"bar": {"interface": "xxx"}}}),
    )


@pytest.mark.parametrize("suffix", RELATION_EVENTS_SUFFIX)
def test_evt_no_relation(suffix):
    assert_inconsistent(State(), Event(f"foo{suffix}"), _CharmSpec(MyCharm, {}))
    assert_consistent(
        State(relations=[Relation("bar")]),
        Event(f"bar{suffix}", relation=Relation("bar")),
        _CharmSpec(MyCharm, {"requires": {"bar": {"interface": "xxx"}}}),
    )


def test_config_key_missing_from_meta():
    assert_inconsistent(
        State(config={"foo": True}),
        Event("bar"),
        _CharmSpec(MyCharm, {}),
    )
    assert_consistent(
        State(config={"foo": True}),
        Event("bar"),
        _CharmSpec(MyCharm, {}, config={"options": {"foo": {"type": "boolean"}}}),
    )


def test_bad_config_option_type():
    assert_inconsistent(
        State(config={"foo": True}),
        Event("bar"),
        _CharmSpec(MyCharm, {}, config={"options": {"foo": {"type": "string"}}}),
    )
    assert_consistent(
        State(config={"foo": True}),
        Event("bar"),
        _CharmSpec(MyCharm, {}, config={"options": {"foo": {"type": "boolean"}}}),
    )


@pytest.mark.parametrize("bad_v", ("1.0", "0", "1.2", "2.35.42", "2.99.99", "2.99"))
def test_secrets_jujuv_bad(bad_v):
    assert_inconsistent(
        State(secrets=[Secret("secret:foo", {0: {"a": "b"}})]),
        Event("bar"),
        _CharmSpec(MyCharm, {}),
        bad_v,
    )


@pytest.mark.parametrize("good_v", ("3.0", "3.1", "3", "3.33", "4", "100"))
def test_secrets_jujuv_bad(good_v):
    assert_consistent(
        State(secrets=[Secret("secret:foo", {0: {"a": "b"}})]),
        Event("bar"),
        _CharmSpec(MyCharm, {}),
        good_v,
    )


def test_peer_relation_consistency():
    assert_inconsistent(
        State(relations=[Relation("foo")]),
        Event("bar"),
        _CharmSpec(MyCharm, {"peers": {"foo": {"interface": "bar"}}}),
    )
    assert_consistent(
        State(relations=[PeerRelation("foo")]),
        Event("bar"),
        _CharmSpec(MyCharm, {"peers": {"foo": {"interface": "bar"}}}),
    )


def test_sub_relation_consistency():
    assert_inconsistent(
        State(relations=[Relation("foo")]),
        Event("bar"),
        _CharmSpec(
            MyCharm,
            {"requires": {"foo": {"interface": "bar", "scope": "container"}}},
        ),
    )
    assert_consistent(
        State(relations=[SubordinateRelation("foo")]),
        Event("bar"),
        _CharmSpec(
            MyCharm,
            {"requires": {"foo": {"interface": "bar", "scope": "container"}}},
        ),
    )


def test_relation_sub_inconsistent():
    assert_inconsistent(
        State(relations=[SubordinateRelation("foo")]),
        Event("bar"),
        _CharmSpec(MyCharm, {"requires": {"foo": {"interface": "bar"}}}),
    )


def test_dupe_containers_inconsistent():
    assert_inconsistent(
        State(containers=[Container("foo"), Container("foo")]),
        Event("bar"),
        _CharmSpec(MyCharm, {"containers": {"foo": {}}}),
    )


def test_container_pebble_evt_consistent():
    container = Container("foo-bar-baz")
    assert_consistent(
        State(containers=[container]),
        container.pebble_ready_event,
        _CharmSpec(MyCharm, {"containers": {"foo-bar-baz": {}}}),
    )


def test_action_name():
    action = Action("foo", params={"bar": "baz"})

    assert_consistent(
        State(),
        action.event,
        _CharmSpec(
            MyCharm, meta={}, actions={"foo": {"params": {"bar": {"type": "string"}}}}
        ),
    )
    assert_inconsistent(
        State(),
        Event("box_action", action=action),
        _CharmSpec(MyCharm, meta={}, actions={"foo": {}}),
    )


def test_action_params_type():
    action = Action("foo", params={"bar": "baz"})
    assert_consistent(
        State(),
        action.event,
        _CharmSpec(
            MyCharm, meta={}, actions={"foo": {"params": {"bar": {"type": "string"}}}}
        ),
    )
    assert_inconsistent(
        State(),
        action.event,
        _CharmSpec(
            MyCharm, meta={}, actions={"foo": {"params": {"bar": {"type": "boolean"}}}}
        ),
    )


def test_duplicate_relation_ids():
    assert_inconsistent(
        State(
            relations=[Relation("foo", relation_id=1), Relation("bar", relation_id=1)]
        ),
        Event("start"),
        _CharmSpec(
            MyCharm,
            meta={
                "requires": {"foo": {"interface": "foo"}, "bar": {"interface": "bar"}}
            },
        ),
    )


def test_relation_without_endpoint():
    assert_inconsistent(
        State(
            relations=[Relation("foo", relation_id=1), Relation("bar", relation_id=1)]
        ),
        Event("start"),
        _CharmSpec(MyCharm, meta={}),
    )

    assert_consistent(
        State(
            relations=[Relation("foo", relation_id=1), Relation("bar", relation_id=2)]
        ),
        Event("start"),
        _CharmSpec(
            MyCharm,
            meta={
                "requires": {"foo": {"interface": "foo"}, "bar": {"interface": "bar"}}
            },
        ),
    )
