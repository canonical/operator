import datetime

import pytest
from ops.charm import CharmBase
from ops.framework import Framework
from ops.model import Secret as ops_Secret
from ops.model import SecretNotFoundError, SecretRotate

from scenario import Context
from scenario.state import Relation, Secret, State


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
    with Context(mycharm, meta={"name": "local"}).manager(
        "update_status", State()
    ) as mgr:
        with pytest.raises(SecretNotFoundError):
            assert mgr.charm.model.get_secret(id="foo")
        with pytest.raises(SecretNotFoundError):
            assert mgr.charm.model.get_secret(label="foo")


def test_get_secret(mycharm):
    with Context(mycharm, meta={"name": "local"}).manager(
        state=State(
            secrets=[Secret(id="foo", contents={0: {"a": "b"}}, granted="unit")]
        ),
        event="update_status",
    ) as mgr:
        assert mgr.charm.model.get_secret(id="foo").get_content()["a"] == "b"


def test_get_secret_not_granted(mycharm):
    with Context(mycharm, meta={"name": "local"}).manager(
        state=State(secrets=[Secret(id="foo", contents={0: {"a": "b"}})]),
        event="update_status",
    ) as mgr:
        with pytest.raises(SecretNotFoundError) as e:
            assert mgr.charm.model.get_secret(id="foo").get_content()["a"] == "b"


@pytest.mark.parametrize("owner", ("app", "unit", "application"))
# "application" is deprecated but still supported
def test_get_secret_get_refresh(mycharm, owner):
    with Context(mycharm, meta={"name": "local"}).manager(
        "update_status",
        State(
            secrets=[
                Secret(
                    id="foo",
                    contents={
                        0: {"a": "b"},
                        1: {"a": "c"},
                    },
                    owner=owner,
                )
            ]
        ),
    ) as mgr:
        charm = mgr.charm
        assert charm.model.get_secret(id="foo").get_content(refresh=True)["a"] == "c"


@pytest.mark.parametrize("app", (True, False))
def test_get_secret_nonowner_peek_update(mycharm, app):
    with Context(mycharm, meta={"name": "local"}).manager(
        "update_status",
        State(
            leader=app,
            secrets=[
                Secret(
                    id="foo",
                    contents={
                        0: {"a": "b"},
                        1: {"a": "c"},
                    },
                    granted="app" if app else "unit",
                ),
            ],
        ),
    ) as mgr:
        charm = mgr.charm
        assert charm.model.get_secret(id="foo").get_content()["a"] == "b"
        assert charm.model.get_secret(id="foo").peek_content()["a"] == "c"
        assert charm.model.get_secret(id="foo").get_content()["a"] == "b"

        assert charm.model.get_secret(id="foo").get_content(refresh=True)["a"] == "c"
        assert charm.model.get_secret(id="foo").get_content()["a"] == "c"


@pytest.mark.parametrize("owner", ("app", "unit", "application"))
# "application" is deprecated but still supported
def test_get_secret_owner_peek_update(mycharm, owner):
    with Context(mycharm, meta={"name": "local"}).manager(
        "update_status",
        State(
            secrets=[
                Secret(
                    id="foo",
                    contents={
                        0: {"a": "b"},
                        1: {"a": "c"},
                    },
                    owner=owner,
                )
            ]
        ),
    ) as mgr:
        charm = mgr.charm
        assert charm.model.get_secret(id="foo").get_content()["a"] == "c"
        assert charm.model.get_secret(id="foo").peek_content()["a"] == "c"
        assert charm.model.get_secret(id="foo").get_content(refresh=True)["a"] == "c"


@pytest.mark.parametrize("owner", ("app", "unit", "application"))
# "application" is deprecated but still supported
def test_secret_changed_owner_evt_fails(mycharm, owner):
    with pytest.raises(ValueError):
        _ = Secret(
            id="foo",
            contents={
                0: {"a": "b"},
                1: {"a": "c"},
            },
            owner=owner,
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


@pytest.mark.parametrize("app", (True, False))
def test_add(mycharm, app):
    with Context(mycharm, meta={"name": "local"}).manager(
        "update_status",
        State(leader=app),
    ) as mgr:
        charm = mgr.charm
        if app:
            charm.app.add_secret({"foo": "bar"}, label="mylabel")
        else:
            charm.unit.add_secret({"foo": "bar"}, label="mylabel")

    assert mgr.output.secrets
    secret = mgr.output.secrets[0]
    assert secret.contents[0] == {"foo": "bar"}
    assert secret.label == "mylabel"


def test_set(mycharm):
    rev1, rev2, rev3 = {"foo": "bar"}, {"foo": "baz"}, {"foo": "baz", "qux": "roz"}
    with Context(mycharm, meta={"name": "local"}).manager(
        "update_status",
        State(),
    ) as mgr:
        charm = mgr.charm
        secret: ops_Secret = charm.unit.add_secret(rev1, label="mylabel")
        assert (
            secret.get_content()
            == secret.peek_content()
            == secret.get_content(refresh=True)
            == rev1
        )

        secret.set_content(rev2)
        assert (
            secret.get_content()
            == secret.peek_content()
            == secret.get_content(refresh=True)
            == rev2
        )

        secret.set_content(rev3)
        state_out = mgr.run()
        assert (
            secret.get_content()
            == secret.peek_content()
            == secret.get_content(refresh=True)
            == rev3
        )

    assert state_out.secrets[0].contents == {
        0: rev1,
        1: rev2,
        2: rev3,
    }


def test_set_juju33(mycharm):
    rev1, rev2, rev3 = {"foo": "bar"}, {"foo": "baz"}, {"foo": "baz", "qux": "roz"}
    with Context(mycharm, meta={"name": "local"}, juju_version="3.3").manager(
        "update_status",
        State(),
    ) as mgr:
        charm = mgr.charm
        secret: ops_Secret = charm.unit.add_secret(rev1, label="mylabel")
        assert secret.get_content() == rev1

        secret.set_content(rev2)
        assert secret.get_content() == rev1
        assert secret.peek_content() == rev2
        assert secret.get_content(refresh=True) == rev2

        secret.set_content(rev3)
        state_out = mgr.run()
        assert secret.get_content() == rev2
        assert secret.peek_content() == rev3
        assert secret.get_content(refresh=True) == rev3

    assert state_out.secrets[0].contents == {
        0: rev1,
        1: rev2,
        2: rev3,
    }


@pytest.mark.parametrize("app", (True, False))
def test_meta(mycharm, app):
    with Context(mycharm, meta={"name": "local"}).manager(
        "update_status",
        State(
            leader=True,
            secrets=[
                Secret(
                    owner="app" if app else "unit",
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
    ) as mgr:
        charm = mgr.charm
        assert charm.model.get_secret(label="mylabel")

        secret = charm.model.get_secret(id="foo")
        info = secret.get_info()

        assert secret.label is None
        assert info.label == "mylabel"
        assert info.rotation == SecretRotate.HOURLY


@pytest.mark.parametrize("leader", (True, False))
@pytest.mark.parametrize("owner", ("app", "unit", None))
@pytest.mark.parametrize("granted", ("app", "unit", None))
def test_secret_permission_model(mycharm, granted, leader, owner):
    if granted:
        owner = None

    expect_view = bool(
        # if you (or your app) owns the secret, you can always view it
        (owner is not None)
        # can read secrets you don't own if you've been granted them
        or granted
    )

    expect_manage = bool(
        # if you're the leader and own this app secret
        (owner == "app" and leader)
        # you own this secret
        or (owner == "unit")
    )

    if expect_manage:
        assert expect_view

    with Context(mycharm, meta={"name": "local"}).manager(
        "update_status",
        State(
            leader=leader,
            secrets=[
                Secret(
                    id="foo",
                    label="mylabel",
                    description="foobarbaz",
                    rotate=SecretRotate.HOURLY,
                    granted=granted,
                    owner=owner,
                    contents={
                        0: {"a": "b"},
                    },
                )
            ],
        ),
    ) as mgr:
        if expect_view:
            secret = mgr.charm.model.get_secret(id="foo")
            assert secret.get_content()["a"] == "b"
            assert secret.peek_content()
            assert secret.get_content(refresh=True)

        else:
            with pytest.raises(SecretNotFoundError):
                mgr.charm.model.get_secret(id="foo")

            # nothing else to do directly if you can't get a hold of the Secret instance
            # but we can try some raw backend calls
            with pytest.raises(SecretNotFoundError):
                mgr.charm.model._backend.secret_info_get(id="foo")

            with pytest.raises(SecretNotFoundError):
                mgr.charm.model._backend.secret_set(id="foo", content={"bo": "fo"})

        if expect_manage:
            secret: ops_Secret = mgr.charm.model.get_secret(id="foo")
            assert secret.get_content()
            assert secret.peek_content()
            assert secret.get_content(refresh=True)

            assert secret.get_info()
            secret.set_content({"foo": "boo"})
            assert secret.get_content()["foo"] == "boo"
            secret.remove_all_revisions()


@pytest.mark.parametrize("app", (True, False))
def test_grant(mycharm, app):
    with Context(
        mycharm, meta={"name": "local", "requires": {"foo": {"interface": "bar"}}}
    ).manager(
        "update_status",
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
    ) as mgr:
        charm = mgr.charm
        secret = charm.model.get_secret(label="mylabel")
        foo = charm.model.get_relation("foo")
        if app:
            secret.grant(relation=foo)
        else:
            secret.grant(relation=foo, unit=foo.units.pop())
    vals = list(mgr.output.secrets[0].remote_grants.values())
    assert vals == [{"remote"}] if app else [{"remote/0"}]


def test_update_metadata(mycharm):
    exp = datetime.datetime(2050, 12, 12)

    with Context(mycharm, meta={"name": "local"}).manager(
        "update_status",
        State(
            secrets=[
                Secret(
                    owner="unit",
                    id="foo",
                    label="mylabel",
                    contents={
                        0: {"a": "b"},
                    },
                )
            ],
        ),
    ) as mgr:
        secret = mgr.charm.model.get_secret(label="mylabel")
        secret.set_info(
            label="babbuccia",
            description="blu",
            expire=exp,
            rotate=SecretRotate.DAILY,
        )

    secret_out = mgr.output.secrets[0]
    assert secret_out.label == "babbuccia"
    assert secret_out.rotate == SecretRotate.DAILY
    assert secret_out.description == "blu"
    assert secret_out.expire == exp


def test_grant_nonowner(mycharm):
    with Context(
        mycharm, meta={"name": "local", "requires": {"foo": {"interface": "bar"}}}
    ).manager(
        "update_status",
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
    ) as mgr:
        with pytest.raises(SecretNotFoundError):
            mgr.charm.model.get_secret(id="foo")


@pytest.mark.parametrize("leader", (True, False))
def test_grant_after_add(leader):
    class GrantingCharm(CharmBase):
        def __init__(self, *args):
            super().__init__(*args)
            self.framework.observe(self.on.start, self._on_start)

        def _on_start(self, _):
            if leader:
                secret = self.app.add_secret({"foo": "bar"})
            else:
                secret = self.unit.add_secret({"foo": "bar"})
            secret.grant(self.model.relations["bar"][0])

    context = Context(
        GrantingCharm, meta={"name": "foo", "provides": {"bar": {"interface": "bar"}}}
    )
    state = State(leader=leader, relations=[Relation("bar")])
    context.run("start", state)
