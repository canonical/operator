import pytest
from ops.charm import CharmBase

from scenario.consistency_checker import check_consistency
from scenario.runtime import InconsistentScenarioError
from scenario.state import (
    RELATION_EVENTS_SUFFIX,
    Container,
    Event,
    Relation,
    Secret,
    State,
    _CharmSpec,
)


class MyCharm(CharmBase):
    pass


def assert_inconsistent(
    state: "State", event: "Event", charm_spec: "_CharmSpec", juju_version="3.0"
):
    with pytest.raises(InconsistentScenarioError):
        check_consistency(state, event, charm_spec, juju_version)


def assert_consistent(
    state: "State", event: "Event", charm_spec: "_CharmSpec", juju_version="3.0"
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
        State(containers=[Container("bar")]), Event("foo"), _CharmSpec(MyCharm, {})
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
        State(config={"foo": True}), Event("bar"), _CharmSpec(MyCharm, {})
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
