import pytest
from ops import RelationNotFoundError
from ops.charm import CharmBase
from ops.framework import Framework

from scenario import Context
from scenario.state import (
    Address,
    BindAddress,
    Network,
    Relation,
    State,
    SubordinateRelation,
)


@pytest.fixture(scope="function")
def mycharm():
    class MyCharm(CharmBase):
        _call = None
        called = False

        def __init__(self, framework: Framework):
            super().__init__(framework)

            for evt in self.on.events().values():
                self.framework.observe(evt, self._on_event)

        def _on_event(self, event):
            if MyCharm._call:
                MyCharm.called = True
                MyCharm._call(self, event)

    return MyCharm


def test_ip_get(mycharm):
    ctx = Context(
        mycharm,
        meta={
            "name": "foo",
            "requires": {
                "metrics-endpoint": {"interface": "foo"},
                "deadnodead": {"interface": "bar"},
            },
            "extra-bindings": {"foo": {}},
        },
    )

    with ctx(
        ctx.on.update_status(),
        State(
            relations=[
                Relation(
                    interface="foo",
                    remote_app_name="remote",
                    endpoint="metrics-endpoint",
                    id=1,
                ),
            ],
            networks={Network("foo", [BindAddress([Address("4.4.4.4")])])},
        ),
    ) as mgr:
        # we have a network for the relation
        rel = mgr.charm.model.get_relation("metrics-endpoint")
        assert str(mgr.charm.model.get_binding(rel).network.bind_address) == "192.0.2.0"

        # we have a network for a binding without relations on it
        assert (
            str(mgr.charm.model.get_binding("deadnodead").network.bind_address)
            == "192.0.2.0"
        )

        # and an extra binding
        assert str(mgr.charm.model.get_binding("foo").network.bind_address) == "4.4.4.4"


def test_no_sub_binding(mycharm):
    ctx = Context(
        mycharm,
        meta={
            "name": "foo",
            "requires": {"bar": {"interface": "foo", "scope": "container"}},
        },
    )

    with ctx(
        ctx.on.update_status(),
        State(
            relations=[
                SubordinateRelation("bar"),
            ]
        ),
    ) as mgr:
        with pytest.raises(RelationNotFoundError):
            # sub relations have no network
            mgr.charm.model.get_binding("bar").network


def test_no_relation_error(mycharm):
    """Attempting to call get_binding on a non-existing relation -> RelationNotFoundError"""

    ctx = Context(
        mycharm,
        meta={
            "name": "foo",
            "requires": {"metrics-endpoint": {"interface": "foo"}},
            "extra-bindings": {"bar": {}},
        },
    )

    with ctx(
        ctx.on.update_status(),
        State(
            relations=[
                Relation(
                    interface="foo",
                    remote_app_name="remote",
                    endpoint="metrics-endpoint",
                    id=1,
                ),
            ],
            networks={Network("bar")},
        ),
    ) as mgr:
        with pytest.raises(RelationNotFoundError):
            mgr.charm.model.get_binding("foo").network


def test_juju_info_network_default(mycharm):
    ctx = Context(
        mycharm,
        meta={"name": "foo"},
    )

    with ctx(
        ctx.on.update_status(),
        State(),
    ) as mgr:
        # we have a network for the relation
        assert (
            str(mgr.charm.model.get_binding("juju-info").network.bind_address)
            == "192.0.2.0"
        )


def test_explicit_juju_info_network_override(mycharm):
    ctx = Context(
        mycharm,
        meta={
            "name": "foo",
            # this charm for whatever reason explicitly defines a juju-info endpoint
            "requires": {"juju-info": {"interface": "juju-info"}},
        },
    )

    with ctx(
        ctx.on.update_status(),
        State(),
    ) as mgr:
        assert mgr.charm.model.get_binding("juju-info").network.bind_address
