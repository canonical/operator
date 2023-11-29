import pytest
from ops import RelationNotFoundError
from ops.charm import CharmBase
from ops.framework import Framework

from scenario import Context
from scenario.state import Network, Relation, State
from tests.helpers import trigger


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
            "requires": {"metrics-endpoint": {"interface": "foo"}},
            "extra-bindings": {"foo": {}},
        },
    )

    with ctx.manager(
        "update_status",
        State(
            relations=[
                Relation(
                    interface="foo",
                    remote_app_name="remote",
                    endpoint="metrics-endpoint",
                    relation_id=1,
                ),
            ],
            extra_bindings={"foo": Network.default(private_address="4.4.4.4")},
        ),
    ) as mgr:
        # we have a network for the relation
        rel = mgr.charm.model.get_relation("metrics-endpoint")
        assert str(mgr.charm.model.get_binding(rel).network.bind_address) == "1.1.1.1"

        # and an extra binding
        assert str(mgr.charm.model.get_binding("foo").network.bind_address) == "4.4.4.4"


def test_no_relation_error(mycharm):
    """Attempting to call get_binding on a non-existing relation -> RelationNotFoundError"""
    mycharm._call = lambda *_: True

    def fetch_unit_address(charm: CharmBase):
        with pytest.raises(RelationNotFoundError):
            _ = charm.model.get_binding("foo").network

    trigger(
        State(
            relations=[
                Relation(
                    interface="foo",
                    remote_app_name="remote",
                    endpoint="metrics-endpoint",
                    relation_id=1,
                ),
            ],
            extra_bindings={"foo": Network.default()},
        ),
        "update_status",
        mycharm,
        meta={
            "name": "foo",
            "requires": {"metrics-endpoint": {"interface": "foo"}},
        },
        post_event=fetch_unit_address,
    )
