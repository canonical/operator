import datetime
import warnings

import pytest
from ops import (
    SecretChangedEvent,
    SecretExpiredEvent,
    SecretRemoveEvent,
    SecretRotateEvent,
)
from ops.charm import CharmBase
from ops.framework import Framework
from ops.model import ModelError
from ops.model import Secret as ops_Secret
from ops.model import SecretNotFoundError, SecretRotate

from scenario import Context
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
    with Context(mycharm, meta={"name": "local"}).manager(
        "update_status", State()
    ) as mgr:
        with pytest.raises(SecretNotFoundError):
            assert mgr.charm.model.get_secret(id="foo")
        with pytest.raises(SecretNotFoundError):
            assert mgr.charm.model.get_secret(label="foo")


def test_get_secret(mycharm):
    with Context(mycharm, meta={"name": "local"}).manager(
        state=State(secrets=[Secret(id="foo", contents={0: {"a": "b"}}, granted=True)]),
        event="update_status",
    ) as mgr:
        assert mgr.charm.model.get_secret(id="foo").get_content()["a"] == "b"


def test_get_secret_not_granted(mycharm):
    with Context(mycharm, meta={"name": "local"}).manager(
        state=State(secrets=[]),
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
        assert charm.model.get_secret(id="foo").get_content()["a"] == "b"
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


def test_set_legacy_behaviour(mycharm):
    # in juju < 3.1.7, secret owners always used to track the latest revision.
    # ref: https://bugs.launchpad.net/juju/+bug/2037120
    rev1, rev2, rev3 = {"foo": "bar"}, {"foo": "baz"}, {"foo": "baz", "qux": "roz"}
    with Context(mycharm, meta={"name": "local"}, juju_version="3.1.6").manager(
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
        secret = charm.model.get_secret(label="mylabel")
        assert (
            secret.get_content()
            == secret.peek_content()
            == secret.get_content(refresh=True)
            == rev2
        )

        secret.set_content(rev3)
        state_out = mgr.run()
        secret = charm.model.get_secret(label="mylabel")
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
        assert secret.get_content() == rev1
        assert secret.peek_content() == secret.get_content(refresh=True) == rev2

        secret.set_content(rev3)
        state_out = mgr.run()
        assert secret.get_content() == rev2
        assert secret.peek_content() == secret.get_content(refresh=True) == rev3

    assert state_out.secrets[0].contents == {
        0: rev1,
        1: rev2,
        2: rev3,
    }


def test_set_juju33(mycharm):
    rev1, rev2, rev3 = {"foo": "bar"}, {"foo": "baz"}, {"foo": "baz", "qux": "roz"}
    with Context(mycharm, meta={"name": "local"}, juju_version="3.3.1").manager(
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


def test_secret_deprecation_application(mycharm):
    with warnings.catch_warnings(record=True) as captured:
        s = Secret("123", {}, owner="application")
        assert s.owner == "app"
    msg = captured[0].message
    assert isinstance(msg, DeprecationWarning)
    assert msg.args[0] == (
        "Secret.owner='application' is deprecated in favour of "
        "'app' and will be removed in Scenario 7+."
    )


@pytest.mark.parametrize("granted", ("app", "unit", False))
def test_secret_deprecation_granted(mycharm, granted):
    with warnings.catch_warnings(record=True) as captured:
        s = Secret("123", {}, granted=granted)
        assert s.granted == granted
    msg = captured[0].message
    assert isinstance(msg, DeprecationWarning)
    assert msg.args[0] == (
        "``state.Secret.granted`` is deprecated and will be removed in Scenario 7+. "
        "If a Secret is not owned by the app/unit you are testing, nor has been granted to "
        "it by the (remote) owner, then omit it from ``State.secrets`` altogether."
    )


@pytest.mark.parametrize("leader", (True, False))
@pytest.mark.parametrize("owner", ("app", "unit", None))
def test_secret_permission_model(mycharm, leader, owner):
    expect_manage = bool(
        # if you're the leader and own this app secret
        (owner == "app" and leader)
        # you own this secret
        or (owner == "unit")
    )

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
                    owner=owner,
                    contents={
                        0: {"a": "b"},
                    },
                )
            ],
        ),
    ) as mgr:
        secret = mgr.charm.model.get_secret(id="foo")
        assert secret.get_content()["a"] == "b"
        assert secret.peek_content()
        assert secret.get_content(refresh=True)

        # can always view
        secret: ops_Secret = mgr.charm.model.get_secret(id="foo")

        if expect_manage:
            assert secret.get_content()
            assert secret.peek_content()
            assert secret.get_content(refresh=True)

            assert secret.get_info()
            secret.set_content({"foo": "boo"})
            assert secret.get_content() == {"a": "b"}  # rev1!
            assert secret.get_content(refresh=True) == {"foo": "boo"}

            secret.remove_all_revisions()

        else:  # cannot manage
            # nothing else to do directly if you can't get a hold of the Secret instance
            # but we can try some raw backend calls
            with pytest.raises(ModelError):
                secret.get_info()

            with pytest.raises(ModelError):
                secret.set_content(content={"boo": "foo"})


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

    state = State(leader=leader, relations=[Relation("bar")])
    context = Context(
        GrantingCharm, meta={"name": "foo", "provides": {"bar": {"interface": "bar"}}}
    )
    context.run("start", state)


def test_grant_nonowner(mycharm):
    def post_event(charm: CharmBase):
        secret = charm.model.get_secret(id="foo")

        secret = charm.model.get_secret(label="mylabel")
        foo = charm.model.get_relation("foo")

        with pytest.raises(ModelError):
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


def test_add_grant_revoke_remove():
    class GrantingCharm(CharmBase):
        def __init__(self, *args):
            super().__init__(*args)

    context = Context(
        GrantingCharm, meta={"name": "foo", "provides": {"bar": {"interface": "bar"}}}
    )
    relation_remote_app = "remote_secret_desirerer"
    relation_id = 42

    state = State(
        leader=True,
        relations=[
            Relation(
                "bar", remote_app_name=relation_remote_app, relation_id=relation_id
            )
        ],
    )

    with context.manager("start", state) as mgr:
        charm = mgr.charm
        secret = charm.app.add_secret({"foo": "bar"}, label="mylabel")
        bar_relation = charm.model.relations["bar"][0]

        secret.grant(bar_relation)

    assert mgr.output.secrets
    scenario_secret = mgr.output.secrets[0]
    assert relation_remote_app in scenario_secret.remote_grants[relation_id]

    with context.manager("start", mgr.output) as mgr:
        charm: GrantingCharm = mgr.charm
        secret = charm.model.get_secret(label="mylabel")
        secret.revoke(bar_relation)

    scenario_secret = mgr.output.secrets[0]
    assert scenario_secret.remote_grants == {}

    with context.manager("start", mgr.output) as mgr:
        charm: GrantingCharm = mgr.charm
        secret = charm.model.get_secret(label="mylabel")
        secret.remove_all_revisions()

    assert not mgr.output.secrets[0].contents  # secret wiped


@pytest.mark.parametrize(
    "evt,owner,cls",
    (
        ("changed", None, SecretChangedEvent),
        ("rotate", "app", SecretRotateEvent),
        ("expired", "app", SecretExpiredEvent),
        ("remove", "app", SecretRemoveEvent),
    ),
)
def test_emit_event(evt, owner, cls):
    class MyCharm(CharmBase):
        def __init__(self, framework):
            super().__init__(framework)
            for evt in self.on.events().values():
                self.framework.observe(evt, self._on_event)
            self.events = []

        def _on_event(self, event):
            self.events.append(event)

    ctx = Context(MyCharm, meta={"name": "local"})
    secret = Secret(contents={"foo": "bar"}, id="foo", owner=owner)
    with ctx.manager(getattr(secret, evt + "_event"), State(secrets=[secret])) as mgr:
        mgr.run()
        juju_event = mgr.charm.events[0]  # Ignore collect-status etc.
        assert isinstance(juju_event, cls)
