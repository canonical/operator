import pytest
from ops.charm import CharmBase
from ops.framework import Framework

from scenario.state import State
from ..helpers import trigger


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
        config={"options": {"foo": {"type": "string"}, "baz": {"type": "int"}}},
        post_event=check_cfg,
    )


def test_config_get_default_from_meta(mycharm):
    def check_cfg(charm: CharmBase):
        assert charm.config["foo"] == "bar"
        assert charm.config["baz"] == 2
        assert charm.config["qux"] is False

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
                "baz": {"type": "int", "default": 2},
                "qux": {"type": "boolean", "default": False},
            },
        },
        post_event=check_cfg,
    )


@pytest.mark.parametrize(
    "cfg_in",
    (
        {"foo": "bar"},
        {"baz": 4, "foo": "bar"},
        {"baz": 4, "foo": "bar", "qux": True},
    ),
)
def test_config_in_not_mutated(mycharm, cfg_in):
    class MyCharm(CharmBase):
        def __init__(self, framework: Framework):
            super().__init__(framework)
            for evt in self.on.events().values():
                self.framework.observe(evt, self._on_event)

        def _on_event(self, event):
            # access the config to trigger a config-get
            foo_cfg = self.config["foo"]  # noqa: F841
            baz_cfg = self.config["baz"]  # noqa: F841
            qux_cfg = self.config["qux"]  # noqa: F841

    state_out = trigger(
        State(
            config=cfg_in,
        ),
        "update_status",
        MyCharm,
        meta={"name": "foo"},
        config={
            "options": {
                "foo": {"type": "string"},
                "baz": {"type": "int", "default": 2},
                "qux": {"type": "boolean", "default": False},
            },
        },
    )
    # check config was not mutated by scenario
    assert state_out.config == cfg_in
