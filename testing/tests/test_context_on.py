from __future__ import annotations

import copy
import typing

import ops
import pytest

import scenario

META = {
    "name": "context-charm",
    "containers": {
        "bar": {},
    },
    "requires": {
        "baz": {
            "interface": "charmlink",
        }
    },
    "storage": {
        "foo": {
            "type": "filesystem",
        }
    },
}
ACTIONS = {
    "act": {
        "params": {
            "param": {
                "description": "some parameter",
                "type": "string",
                "default": "",
            }
        }
    },
}


class ContextCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self.observed: typing.List[ops.EventBase] = []
        for event in self.on.events().values():
            framework.observe(event, self._on_event)

    def _on_event(self, event: ops.EventBase):
        self.observed.append(event)


@pytest.mark.parametrize(
    "event_name, event_kind",
    [
        ("install", ops.InstallEvent),
        ("start", ops.StartEvent),
        ("stop", ops.StopEvent),
        ("remove", ops.RemoveEvent),
        ("update_status", ops.UpdateStatusEvent),
        ("config_changed", ops.ConfigChangedEvent),
        ("upgrade_charm", ops.UpgradeCharmEvent),
        ("leader_elected", ops.LeaderElectedEvent),
    ],
)
def test_simple_events(event_name: str, event_kind: typing.Type[ops.EventBase]):
    ctx = scenario.Context(ContextCharm, meta=META, actions=ACTIONS)
    # These look like:
    #   ctx.run(ctx.on.install(), state)
    with ctx(getattr(ctx.on, event_name)(), scenario.State()) as mgr:
        mgr.run()
        assert len(mgr.charm.observed) == 2
        assert isinstance(mgr.charm.observed[1], ops.CollectStatusEvent)
        assert isinstance(mgr.charm.observed[0], event_kind)


@pytest.mark.parametrize(
    "event_name, event_kind",
    [
        ("pre_series_upgrade", ops.PreSeriesUpgradeEvent),
        ("post_series_upgrade", ops.PostSeriesUpgradeEvent),
    ],
)
def test_simple_deprecated_events(event_name, event_kind):
    ctx = scenario.Context(ContextCharm, meta=META, actions=ACTIONS)
    # These look like:
    #   ctx.run(ctx.on.pre_series_upgrade(), state)
    with pytest.warns(DeprecationWarning):
        with ctx(getattr(ctx.on, event_name)(), scenario.State()) as mgr:
            mgr.run()
            assert len(mgr.charm.observed) == 2
            assert isinstance(mgr.charm.observed[1], ops.CollectStatusEvent)
            assert isinstance(mgr.charm.observed[0], event_kind)


@pytest.mark.parametrize("as_kwarg", [True, False])
@pytest.mark.parametrize(
    "event_name,event_kind,owner",
    [
        ("secret_changed", ops.SecretChangedEvent, None),
        ("secret_rotate", ops.SecretRotateEvent, "app"),
    ],
)
def test_simple_secret_events(as_kwarg, event_name, event_kind, owner):
    ctx = scenario.Context(ContextCharm, meta=META, actions=ACTIONS)
    secret = scenario.Secret({"password": "xxxx"}, owner=owner)
    state_in = scenario.State(secrets={secret})
    # These look like:
    #   ctx.run(ctx.on.secret_changed(secret=secret), state)
    # The secret must always be passed because the same event name is used for
    # all secrets.
    if as_kwarg:
        args = ()
        kwargs = {"secret": secret}
    else:
        args = (secret,)
        kwargs = {}
    with ctx(getattr(ctx.on, event_name)(*args, **kwargs), state_in) as mgr:
        mgr.run()
        assert len(mgr.charm.observed) == 2
        assert isinstance(mgr.charm.observed[1], ops.CollectStatusEvent)
        evt = mgr.charm.observed[0]
        assert isinstance(evt, event_kind)
        assert evt.secret.id == secret.id


@pytest.mark.parametrize(
    "event_name, event_kind",
    [
        ("secret_expired", ops.SecretExpiredEvent),
        ("secret_remove", ops.SecretRemoveEvent),
    ],
)
def test_revision_secret_events(event_name, event_kind):
    ctx = scenario.Context(ContextCharm, meta=META, actions=ACTIONS)
    secret = scenario.Secret(
        tracked_content={"password": "yyyy"},
        latest_content={"password": "xxxx"},
        owner="app",
    )
    state_in = scenario.State(secrets={secret})
    # These look like:
    #   ctx.run(ctx.on.secret_expired(secret=secret, revision=revision), state)
    # The secret and revision must always be passed because the same event name
    # is used for all secrets.
    with ctx(getattr(ctx.on, event_name)(secret, revision=42), state_in) as mgr:
        mgr.run()
        assert len(mgr.charm.observed) == 2
        assert isinstance(mgr.charm.observed[1], ops.CollectStatusEvent)
        evt = mgr.charm.observed[0]
        assert isinstance(evt, event_kind)
        assert evt.secret.id == secret.id
        assert evt.revision == 42


@pytest.mark.parametrize("event_name", ["secret_expired", "secret_remove"])
def test_revision_secret_events_as_positional_arg(event_name):
    ctx = scenario.Context(ContextCharm, meta=META, actions=ACTIONS)
    secret = scenario.Secret(
        tracked_content={"password": "yyyy"},
        latest_content={"password": "xxxx"},
        owner=None,
    )
    state_in = scenario.State(secrets={secret})
    with pytest.raises(TypeError):
        ctx.run(getattr(ctx.on, event_name)(secret, 42), state_in)


@pytest.mark.parametrize(
    "event_name, event_kind",
    [
        ("storage_attached", ops.StorageAttachedEvent),
        ("storage_detaching", ops.StorageDetachingEvent),
    ],
)
def test_storage_events(event_name, event_kind):
    ctx = scenario.Context(ContextCharm, meta=META, actions=ACTIONS)
    storage = scenario.Storage("foo")
    state_in = scenario.State(storages=[storage])
    # These look like:
    #   ctx.run(ctx.on.storage_attached(storage), state)
    with ctx(getattr(ctx.on, event_name)(storage), state_in) as mgr:
        mgr.run()
        assert len(mgr.charm.observed) == 2
        assert isinstance(mgr.charm.observed[1], ops.CollectStatusEvent)
        evt = mgr.charm.observed[0]
        assert isinstance(evt, event_kind)
        assert evt.storage.name == storage.name
        assert evt.storage.index == storage.index


def test_action_event_no_params():
    ctx = scenario.Context(ContextCharm, meta=META, actions=ACTIONS)
    # These look like:
    #   ctx.run(ctx.on.action(action_name), state)
    with ctx(ctx.on.action("act"), scenario.State()) as mgr:
        mgr.run()
        assert len(mgr.charm.observed) == 2
        assert isinstance(mgr.charm.observed[1], ops.CollectStatusEvent)
        evt = mgr.charm.observed[0]
        assert isinstance(evt, ops.ActionEvent)


def test_action_event_with_params():
    ctx = scenario.Context(ContextCharm, meta=META, actions=ACTIONS)
    # These look like:
    #   ctx.run(ctx.on.action(action=action), state)
    # So that any parameters can be included and the ID can be customised.
    call_event = ctx.on.action("act", params={"param": "hello"})
    with ctx(call_event, scenario.State()) as mgr:
        mgr.run()
        assert len(mgr.charm.observed) == 2
        assert isinstance(mgr.charm.observed[1], ops.CollectStatusEvent)
        evt = mgr.charm.observed[0]
        assert isinstance(evt, ops.ActionEvent)
        assert evt.id == call_event.action.id
        assert evt.params["param"] == call_event.action.params["param"]


def test_pebble_ready_event():
    ctx = scenario.Context(ContextCharm, meta=META, actions=ACTIONS)
    container = scenario.Container("bar", can_connect=True)
    state_in = scenario.State(containers=[container])
    # These look like:
    #   ctx.run(ctx.on.pebble_ready(container), state)
    with ctx(ctx.on.pebble_ready(container), state_in) as mgr:
        mgr.run()
        assert len(mgr.charm.observed) == 2
        assert isinstance(mgr.charm.observed[1], ops.CollectStatusEvent)
        evt = mgr.charm.observed[0]
        assert isinstance(evt, ops.PebbleReadyEvent)
        assert evt.workload.name == container.name


@pytest.mark.parametrize("as_kwarg", [True, False])
@pytest.mark.parametrize(
    "event_name, event_kind",
    [
        ("relation_created", ops.RelationCreatedEvent),
        ("relation_broken", ops.RelationBrokenEvent),
    ],
)
def test_relation_app_events(as_kwarg, event_name, event_kind):
    ctx = scenario.Context(ContextCharm, meta=META, actions=ACTIONS)
    relation = scenario.Relation("baz")
    state_in = scenario.State(relations=[relation])
    # These look like:
    #   ctx.run(ctx.on.relation_created(relation), state)
    if as_kwarg:
        args = ()
        kwargs = {"relation": relation}
    else:
        args = (relation,)
        kwargs = {}
    with ctx(getattr(ctx.on, event_name)(*args, **kwargs), state_in) as mgr:
        mgr.run()
        assert len(mgr.charm.observed) == 2
        assert isinstance(mgr.charm.observed[1], ops.CollectStatusEvent)
        evt = mgr.charm.observed[0]
        assert isinstance(evt, event_kind)
        assert evt.relation.id == relation.id
        assert evt.app.name == relation.remote_app_name
        assert evt.unit is None


def test_relation_complex_name():
    meta = copy.deepcopy(META)
    meta["requires"]["foo-bar-baz"] = {"interface": "another-one"}
    ctx = scenario.Context(ContextCharm, meta=meta, actions=ACTIONS)
    relation = scenario.Relation("foo-bar-baz")
    state_in = scenario.State(relations=[relation])
    with ctx(ctx.on.relation_created(relation), state_in) as mgr:
        mgr.run()
        assert len(mgr.charm.observed) == 2
        evt = mgr.charm.observed[0]
        assert isinstance(evt, ops.RelationCreatedEvent)
        assert evt.relation.id == relation.id
        assert evt.app.name == relation.remote_app_name
        assert evt.unit is None


@pytest.mark.parametrize("event_name", ["relation_created", "relation_broken"])
def test_relation_events_as_positional_arg(event_name):
    ctx = scenario.Context(ContextCharm, meta=META, actions=ACTIONS)
    relation = scenario.Relation("baz")
    state_in = scenario.State(relations=[relation])
    with pytest.raises(TypeError):
        ctx.run(getattr(ctx.on, event_name)(relation, 0), state_in)


@pytest.mark.parametrize(
    "event_name, event_kind",
    [
        ("relation_joined", ops.RelationJoinedEvent),
        ("relation_changed", ops.RelationChangedEvent),
    ],
)
def test_relation_unit_events_default_unit(event_name, event_kind):
    ctx = scenario.Context(ContextCharm, meta=META, actions=ACTIONS)
    relation = scenario.Relation("baz", remote_units_data={1: {"x": "y"}})
    state_in = scenario.State(relations=[relation])
    # These look like:
    #   ctx.run(ctx.on.baz_relation_changed, state)
    # The unit is chosen automatically.
    with ctx(getattr(ctx.on, event_name)(relation), state_in) as mgr:
        mgr.run()
        assert len(mgr.charm.observed) == 2
        assert isinstance(mgr.charm.observed[1], ops.CollectStatusEvent)
        evt = mgr.charm.observed[0]
        assert isinstance(evt, event_kind)
        assert evt.relation.id == relation.id
        assert evt.app.name == relation.remote_app_name
        assert evt.unit.name == "remote/1"


@pytest.mark.parametrize(
    "event_name, event_kind",
    [
        ("relation_joined", ops.RelationJoinedEvent),
        ("relation_changed", ops.RelationChangedEvent),
    ],
)
def test_relation_unit_events(event_name, event_kind):
    ctx = scenario.Context(ContextCharm, meta=META, actions=ACTIONS)
    relation = scenario.Relation(
        "baz", remote_units_data={1: {"x": "y"}, 2: {"x": "z"}}
    )
    state_in = scenario.State(relations=[relation])
    # These look like:
    #   ctx.run(ctx.on.baz_relation_changed(unit=unit_ordinal), state)
    with ctx(getattr(ctx.on, event_name)(relation, remote_unit=2), state_in) as mgr:
        mgr.run()
        assert len(mgr.charm.observed) == 2
        assert isinstance(mgr.charm.observed[1], ops.CollectStatusEvent)
        evt = mgr.charm.observed[0]
        assert isinstance(evt, event_kind)
        assert evt.relation.id == relation.id
        assert evt.app.name == relation.remote_app_name
        assert evt.unit.name == "remote/2"


def test_relation_departed_event():
    ctx = scenario.Context(ContextCharm, meta=META, actions=ACTIONS)
    relation = scenario.Relation("baz")
    state_in = scenario.State(relations=[relation])
    # These look like:
    #   ctx.run(ctx.on.baz_relation_departed(unit=unit_ordinal, departing_unit=unit_ordinal), state)
    with ctx(
        ctx.on.relation_departed(relation, remote_unit=2, departing_unit=1), state_in
    ) as mgr:
        mgr.run()
        assert len(mgr.charm.observed) == 2
        assert isinstance(mgr.charm.observed[1], ops.CollectStatusEvent)
        evt = mgr.charm.observed[0]
        assert isinstance(evt, ops.RelationDepartedEvent)
        assert evt.relation.id == relation.id
        assert evt.app.name == relation.remote_app_name
        assert evt.unit.name == "remote/2"
        assert evt.departing_unit.name == "remote/1"


class CustomEvent(ops.EventBase):
    pass


class CustomEventWithArgs(CustomEvent):
    arg0: str
    arg1: int

    def __init__(self, handle: ops.Handle, arg0: str = "", arg1: int = 0):
        super().__init__(handle)
        self.arg0 = arg0
        self.arg1 = arg1

    def snapshot(self):
        base = super().snapshot()
        base.update({"arg0": self.arg0, "arg1": self.arg1})
        return base

    def restore(self, snapshot: dict[str, typing.Any]):
        super().restore(snapshot)
        self.arg0 = snapshot["arg0"]
        self.arg1 = snapshot["arg1"]


class CustomRelationEvent(ops.RelationChangedEvent):
    def __init__(
        self,
        handle: ops.Handle,
        relation: ops.Relation,
        app: ops.Application | None = None,
        unit: ops.Unit | None = None,
        *,
        arg0: str = "",
        arg1: int = 0,
    ):
        super().__init__(handle, relation)
        self.arg0 = arg0
        self.arg1 = arg1

    def snapshot(self):
        base = super().snapshot()
        base.update({"arg0": self.arg0, "arg1": self.arg1})
        return base

    def restore(self, snapshot: dict[str, typing.Any]):
        super().restore(snapshot)
        self.arg0 = snapshot["arg0"]
        self.arg1 = snapshot["arg1"]


class CustomEvents(ops.ObjectEvents):
    foo_started = ops.EventSource(CustomEvent)
    foo_changed = ops.EventSource(CustomEventWithArgs)
    foo_relation_changed = ops.EventSource(CustomRelationEvent)


class MyConsumer(ops.Object):
    on = CustomEvents()  # type: ignore

    def __init__(self, charm: ops.CharmBase):
        super().__init__(charm, "my-consumer")


class CustomCharm(ContextCharm):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self.consumer = MyConsumer(self)
        framework.observe(self.consumer.on.foo_started, self._on_event)
        framework.observe(self.consumer.on.foo_changed, self._on_event)
        framework.observe(self.consumer.on.foo_relation_changed, self._on_event)


def test_custom_event_no_args():
    ctx = scenario.Context(CustomCharm, meta=META, actions=ACTIONS)
    with ctx(ctx.on.custom(MyConsumer.on.foo_started), scenario.State()) as mgr:
        mgr.run()
        assert len(mgr.charm.observed) == 2
        assert isinstance(mgr.charm.observed[1], ops.CollectStatusEvent)
        evt = mgr.charm.observed[0]
        assert isinstance(evt, CustomEvent)


def test_custom_event_with_args():
    ctx = scenario.Context(CustomCharm, meta=META, actions=ACTIONS)
    with ctx(
        ctx.on.custom(MyConsumer.on.foo_changed, "foo", arg1=42),
        scenario.State(),
    ) as mgr:
        mgr.run()
        assert len(mgr.charm.observed) == 2
        assert isinstance(mgr.charm.observed[1], ops.CollectStatusEvent)
        evt = mgr.charm.observed[0]
        assert isinstance(evt, CustomEventWithArgs)
        assert evt.arg0 == "foo"
        assert evt.arg1 == 42


def test_custom_event_from_juju_event():
    meta = META.copy()
    meta["requires"]["db"] = {"interface": "db"}
    ctx = scenario.Context(CustomCharm, meta=meta, actions=ACTIONS)
    relation = scenario.Relation("db")
    originating_event = ctx.on.relation_changed(relation)
    event = ctx.on.custom(
        MyConsumer.on.foo_relation_changed,
        arg0="foo",
        arg1=42,
        from_=originating_event,
    )
    with ctx(event, scenario.State(relations={relation})) as mgr:
        mgr.run()
        assert len(mgr.charm.observed) == 2
        assert isinstance(mgr.charm.observed[1], ops.CollectStatusEvent)
        evt = mgr.charm.observed[0]
        assert isinstance(evt, CustomRelationEvent)
        assert evt.relation.id == relation.id
        assert evt.arg0 == "foo"
        assert evt.arg1 == 42
