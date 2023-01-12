from typing import Optional

import pytest

from ops.charm import CharmBase
from ops.framework import Framework
from ops.model import BlockedStatus, ActiveStatus
from scenario.scenario import Scenario
from scenario.structs import CharmSpec, Scene, State, event, relation, Status


@pytest.fixture(scope="function")
def mycharm():
    class MyCharm(CharmBase):
        _call = None
        called = False

        def __init__(self, framework: Framework, key: Optional[str] = None):
            super().__init__(framework, key)

            for evt in self.on.events().values():
                self.framework.observe(evt, self._on_event)

        def _on_event(self, event):
            if MyCharm._call:
                MyCharm.called = True
                MyCharm._call(self, event)

    return MyCharm


def test_charm_heals_on_start(mycharm):
    scenario = Scenario(CharmSpec(mycharm, meta={"name": "foo"}))

    def pre_event(charm):
        pre_event._called = True
        assert not charm.is_ready()
        assert charm.unit.status == BlockedStatus("foo")
        assert not charm.called

    def call(charm, _):
        if charm.unit.status.message == "foo":
            charm.unit.status = ActiveStatus("yabadoodle")

    def post_event(charm):
        post_event._called = True

        assert charm.is_ready()
        assert charm.unit.status == ActiveStatus("yabadoodle")
        assert charm.called

    mycharm._call = call

    initial_state = State(
        config={"foo": "bar"}, leader=True,
        status=Status(unit=('blocked', 'foo'))
    )

    out = scenario.play(
        Scene(
            event("update-status"),
            state=initial_state),
    )

    assert out.status.unit == ('active', 'yabadoodle')

    out.juju_log = []  # exclude juju log from delta
    assert out.delta(initial_state) == [
        {
            "op": "replace",
            "path": "/status/unit",
            "value": ("active", "yabadoodle"),
        }
    ]


def test_relation_data_access(mycharm):
    mycharm._call = lambda *_: True
    scenario = Scenario(
        CharmSpec(
            mycharm,
            meta={
                "name": "foo",
                "requires": {"relation_test": {"interface": "azdrubales"}},
            },
        )
    )

    def check_relation_data(charm):
        foo_relations = charm.model.relations["relation_test"]
        assert len(foo_relations) == 1
        foo_rel = foo_relations[0]
        assert len(foo_rel.units) == 2

        remote_units_data = {}
        for remote_unit in foo_rel.units:
            remote_units_data[remote_unit.name] = dict(foo_rel.data[remote_unit])

        remote_app_data = foo_rel.data[foo_rel.app]

        assert remote_units_data == {
            "karlos/0": {"foo": "bar"},
            "karlos/1": {"baz": "qux"},
        }

        assert remote_app_data == {"yaba": "doodle"}

    scene = Scene(
            state=State(
                relations=[
                    relation(
                        endpoint="relation_test",
                        interface="azdrubales",
                        remote_app_name="karlos",
                        remote_app_data={"yaba": "doodle"},
                        remote_units_data={0: {"foo": "bar"},
                                           1: {"baz": "qux"}},
                    )
                ]
            ),
            event=event("update-status"),
        )

    scenario.play(
        scene,
        post_event=check_relation_data,
    )
