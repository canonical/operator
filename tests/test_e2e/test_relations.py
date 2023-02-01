from typing import Type

import pytest
from ops.charm import CharmBase, CharmEvents
from ops.framework import EventBase, Framework

from scenario.state import Event, Relation, State, _CharmSpec


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
    )
