import pytest
from ops.charm import CharmBase
from ops.framework import Framework
from ops.model import SecretRotate

from scenario.state import Relation, Secret, State
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


def test_get_secret_no_secret(mycharm):
    def post_event(charm: CharmBase):
        with pytest.raises(RuntimeError):
            assert charm.model.get_secret(id="foo")
        with pytest.raises(RuntimeError):
            assert charm.model.get_secret(label="foo")

    trigger(
        State(), "update_status", mycharm, meta={"name": "local"}, post_event=post_event
    )


def test_get_secret(mycharm):
    def post_event(charm: CharmBase):
        assert charm.model.get_secret(id="foo").get_content()["a"] == "b"

    trigger(
        State(secrets=[Secret(id="foo", contents={0: {"a": "b"}})]),
        "update_status",
        mycharm,
        meta={"name": "local"},
        post_event=post_event,
    )


def test_get_secret_peek_update(mycharm):
    def post_event(charm: CharmBase):
        assert charm.model.get_secret(id="foo").get_content()["a"] == "b"
        assert charm.model.get_secret(id="foo").peek_content()["a"] == "c"
        assert charm.model.get_secret(id="foo").get_content()["a"] == "b"

        assert charm.model.get_secret(id="foo").get_content(refresh=True)["a"] == "c"
        assert charm.model.get_secret(id="foo").get_content()["a"] == "c"

    trigger(
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
        ),
        "update_status",
        mycharm,
        meta={"name": "local"},
        post_event=post_event,
    )


def test_secret_changed_owner_evt_fails(mycharm):
    with pytest.raises(ValueError):
        _ = Secret(
            id="foo",
            contents={
                0: {"a": "b"},
                1: {"a": "c"},
            },
            owner="unit",
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
            ),
            evt_prefix + "_event",
        )


def test_add(mycharm):
    def post_event(charm: CharmBase):
        charm.unit.add_secret({"foo": "bar"}, label="mylabel")

    out = trigger(
        State(), "update_status", mycharm, meta={"name": "local"}, post_event=post_event
    )
    assert out.secrets
    secret = out.secrets[0]
    assert secret.contents[0] == {"foo": "bar"}
    assert secret.label == "mylabel"


def test_meta(mycharm):
    def post_event(charm: CharmBase):
        assert charm.model.get_secret(label="mylabel")

        secret = charm.model.get_secret(id="foo")
        info = secret.get_info()

        assert secret.label is None
        assert info.label == "mylabel"
        assert info.rotation == SecretRotate.HOURLY

    trigger(
        State(
            secrets=[
                Secret(
                    owner="unit",
                    id="foo",
                    label="mylabel",
                    description="foobarbaz",
                    rotate=SecretRotate.HOURLY,
                    contents={
                        0: {"a": "b"},
                    },
                )
            ]
        ),
        "update_status",
        mycharm,
        meta={"name": "local"},
        post_event=post_event,
    )


def test_meta_nonowner(mycharm):
    def post_event(charm: CharmBase):
        secret = charm.model.get_secret(id="foo")
        with pytest.raises(RuntimeError):
            info = secret.get_info()

    trigger(
        State(
            secrets=[
                Secret(
                    id="foo",
                    label="mylabel",
                    description="foobarbaz",
                    rotate=SecretRotate.HOURLY,
                    contents={
                        0: {"a": "b"},
                    },
                )
            ]
        ),
        "update_status",
        mycharm,
        meta={"name": "local"},
        post_event=post_event,
    )


@pytest.mark.parametrize("app", (True, False))
def test_grant(mycharm, app):
    def post_event(charm: CharmBase):
        secret = charm.model.get_secret(label="mylabel")
        foo = charm.model.get_relation("foo")
        if app:
            secret.grant(relation=foo)
        else:
            secret.grant(relation=foo, unit=foo.units.pop())

    out = trigger(
        State(
            relations=[Relation("foo", "remote")],
            secrets=[
                Secret(
                    owner="unit",
                    id="foo",
                    label="mylabel",
                    description="foobarbaz",
                    rotate=SecretRotate.HOURLY,
                    contents={
                        0: {"a": "b"},
                    },
                )
            ],
        ),
        "update_status",
        mycharm,
        meta={"name": "local", "requires": {"foo": {"interface": "bar"}}},
        post_event=post_event,
    )

    vals = list(out.secrets[0].remote_grants.values())
    assert vals == [{"remote"}] if app else [{"remote/0"}]


def test_grant_nonowner(mycharm):
    def post_event(charm: CharmBase):
        secret = charm.model.get_secret(id="foo")
        with pytest.raises(RuntimeError):
            secret = charm.model.get_secret(label="mylabel")
            foo = charm.model.get_relation("foo")
            secret.grant(relation=foo)

    out = trigger(
        State(
            relations=[Relation("foo", "remote")],
            secrets=[
                Secret(
                    id="foo",
                    label="mylabel",
                    description="foobarbaz",
                    rotate=SecretRotate.HOURLY,
                    contents={
                        0: {"a": "b"},
                    },
                )
            ],
        ),
        "update_status",
        mycharm,
        meta={"name": "local", "requires": {"foo": {"interface": "bar"}}},
        post_event=post_event,
    )
