import pytest
from ops.charm import CharmBase
from ops.framework import Framework

from scenario.state import Secret, State


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


def test_get_secret_no_secret(mycharm):
    def post_event(charm: CharmBase):
        with pytest.raises(RuntimeError):
            assert charm.model.get_secret(id="foo")
        with pytest.raises(RuntimeError):
            assert charm.model.get_secret(label="foo")

    State().trigger(
        "update-status", mycharm, meta={"name": "local"}, post_event=post_event
    )


def test_get_secret(mycharm):
    def post_event(charm: CharmBase):
        assert charm.model.get_secret(id="foo").get_content()["a"] == "b"

    State(secrets=[Secret(id="foo", contents={0: {"a": "b"}})]).trigger(
        "update-status", mycharm, meta={"name": "local"}, post_event=post_event
    )


def test_get_secret_peek_update(mycharm):
    def post_event(charm: CharmBase):
        assert charm.model.get_secret(id="foo").get_content()["a"] == "b"
        assert charm.model.get_secret(id="foo").peek_content()["a"] == "c"
        assert charm.model.get_secret(id="foo").get_content()["a"] == "b"

        assert charm.model.get_secret(id="foo").get_content(refresh=True)["a"] == "c"
        assert charm.model.get_secret(id="foo").get_content()["a"] == "c"

    State(
        secrets=[
            Secret(
                id="foo",
                contents={
                    0: {"a": "b"},
                    1: {"a": "c"},
                },
            )
        ]
    ).trigger("update-status", mycharm, meta={"name": "local"}, post_event=post_event)


def test_secret_changed_owner_evt_fails(mycharm):
    with pytest.raises(ValueError):
        _ = Secret(
            id="foo",
            contents={
                0: {"a": "b"},
                1: {"a": "c"},
            },
            owned_by_this_unit=True,
        ).changed_event


@pytest.mark.parametrize("evt_prefix", ("rotate", "expired", "remove"))
def test_consumer_events_failures(mycharm, evt_prefix):
    with pytest.raises(ValueError):
        _ = getattr(
            Secret(
                id="foo",
                contents={
                    0: {"a": "b"},
                    1: {"a": "c"},
                },
                owned_by_this_unit=False,
            ),
            evt_prefix + "_event",
        )
