import pytest
from ops.charm import CharmBase
from ops.framework import Framework

from scenario.state import Event, Network, Relation, State, _CharmSpec
from tests.helpers import trigger


@pytest.fixture(scope="function")
def mycharm():
    class MyCharm(CharmBase):
        def __init__(self, framework: Framework):
            super().__init__(framework)
            for evt in self.on.events().values():
                self.framework.observe(evt, self._on_event)

        def _on_event(self, event):
            pass

    return MyCharm


def test_config_get(mycharm):
    def check_cfg(charm: CharmBase):
        assert charm.config["foo"] == "bar"
        assert charm.config["baz"] == 1

    trigger(
        State(
            config={"foo": "bar", "baz": 1},
        ),
        "update_status",
        mycharm,
        meta={"name": "foo"},
        config={"options": {"foo": {"type": "string"}, "baz": {"type": "integer"}}},
        post_event=check_cfg,
    )


def test_config_get_default_from_meta(mycharm):
    def check_cfg(charm: CharmBase):
        assert charm.config["foo"] == "bar"
        assert charm.config["baz"] == 2

    trigger(
        State(
            config={"foo": "bar"},
        ),
        "update_status",
        mycharm,
        meta={"name": "foo"},
        config={
            "options": {
                "foo": {"type": "string"},
                "baz": {"type": "integer", "default": 2},
            },
        },
        post_event=check_cfg,
    )
