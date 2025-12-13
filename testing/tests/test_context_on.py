# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

from __future__ import annotations

import copy
import datetime
import typing

import pytest
import scenario

import ops

META = {
    'name': 'context-charm',
    'containers': {
        'bar': {},
    },
    'requires': {
        'baz': {
            'interface': 'charmlink',
        }
    },
    'storage': {
        'foo': {
            'type': 'filesystem',
        }
    },
}
ACTIONS = {
    'act': {
        'params': {
            'param': {
                'description': 'some parameter',
                'type': 'string',
                'default': '',
            }
        }
    },
}


class ContextCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self.observed: list[ops.EventBase] = []
        for event in self.on.events().values():
            framework.observe(event, self._on_event)

    def _on_event(self, event: ops.EventBase):
        self.observed.append(event)


@pytest.mark.parametrize(
    'event_name, event_kind',
    [
        ('install', ops.InstallEvent),
        ('start', ops.StartEvent),
        ('stop', ops.StopEvent),
        ('remove', ops.RemoveEvent),
        ('update_status', ops.UpdateStatusEvent),
        ('config_changed', ops.ConfigChangedEvent),
        ('upgrade_charm', ops.UpgradeCharmEvent),
        ('leader_elected', ops.LeaderElectedEvent),
    ],
)
def test_simple_events(event_name: str, event_kind: type[ops.EventBase]):
    ctx = scenario.Context(ContextCharm, meta=META, actions=ACTIONS)
    # These look like:
    #   ctx.run(ctx.on.install(), state)
    with ctx(getattr(ctx.on, event_name)(), scenario.State()) as mgr:
        mgr.run()
        juju_event, status = mgr.charm.observed
        assert isinstance(juju_event, event_kind)
        assert isinstance(status, ops.CollectStatusEvent)


@pytest.mark.parametrize(
    'event_name, event_kind',
    [
        ('pre_series_upgrade', ops.PreSeriesUpgradeEvent),
        ('post_series_upgrade', ops.PostSeriesUpgradeEvent),
    ],
)
def test_simple_deprecated_events(event_name, event_kind):
    ctx = scenario.Context(ContextCharm, meta=META, actions=ACTIONS)
    # These look like:
    #   ctx.run(ctx.on.pre_series_upgrade(), state)
    with pytest.warns(DeprecationWarning):
        with ctx(getattr(ctx.on, event_name)(), scenario.State()) as mgr:
            mgr.run()
            deprecated_event, collect_status = mgr.charm.observed
            assert isinstance(deprecated_event, event_kind)
            assert isinstance(collect_status, ops.CollectStatusEvent)


@pytest.mark.parametrize('as_kwarg', [True, False])
@pytest.mark.parametrize(
    'event_name,event_kind,owner',
    [
        ('secret_changed', ops.SecretChangedEvent, None),
        ('secret_rotate', ops.SecretRotateEvent, 'app'),
    ],
)
def test_simple_secret_events(as_kwarg, event_name, event_kind, owner):
    ctx = scenario.Context(ContextCharm, meta=META, actions=ACTIONS)
    secret = scenario.Secret({'password': 'xxxx'}, owner=owner)
    state_in = scenario.State(secrets={secret})
    # These look like:
    #   ctx.run(ctx.on.secret_changed(secret=secret), state)
    # The secret must always be passed because the same event name is used for
    # all secrets.
    if as_kwarg:
        args = ()
        kwargs = {'secret': secret}
    else:
        args = (secret,)
        kwargs = {}
    with ctx(getattr(ctx.on, event_name)(*args, **kwargs), state_in) as mgr:
        mgr.run()
        secret_event, collect_status = mgr.charm.observed
        assert isinstance(secret_event, event_kind)
        assert secret_event.secret.id == secret.id
        assert isinstance(collect_status, ops.CollectStatusEvent)


@pytest.mark.parametrize(
    'event_name, event_kind',
    [
        ('secret_expired', ops.SecretExpiredEvent),
        ('secret_remove', ops.SecretRemoveEvent),
    ],
)
def test_revision_secret_events(event_name, event_kind):
    ctx = scenario.Context(ContextCharm, meta=META, actions=ACTIONS)
    secret = scenario.Secret(
        tracked_content={'password': 'yyyy'},
        latest_content={'password': 'xxxx'},
        owner='app',
    )
    state_in = scenario.State(secrets={secret})
    # These look like:
    #   ctx.run(ctx.on.secret_expired(secret=secret, revision=revision), state)
    # The secret and revision must always be passed because the same event name
    # is used for all secrets.
    with ctx(getattr(ctx.on, event_name)(secret, revision=42), state_in) as mgr:
        mgr.run()
        secret_event, collect_status = mgr.charm.observed
        assert isinstance(secret_event, event_kind)
        assert secret_event.secret.id == secret.id
        assert secret_event.revision == 42
        assert isinstance(collect_status, ops.CollectStatusEvent)


@pytest.mark.parametrize('event_name', ['secret_expired', 'secret_remove'])
def test_revision_secret_events_as_positional_arg(event_name):
    ctx = scenario.Context(ContextCharm, meta=META, actions=ACTIONS)
    secret = scenario.Secret(
        tracked_content={'password': 'yyyy'},
        latest_content={'password': 'xxxx'},
        owner=None,
    )
    state_in = scenario.State(secrets={secret})
    with pytest.raises(TypeError):
        ctx.run(getattr(ctx.on, event_name)(secret, 42), state_in)


@pytest.mark.parametrize(
    'event_name, event_kind',
    [
        ('storage_attached', ops.StorageAttachedEvent),
        ('storage_detaching', ops.StorageDetachingEvent),
    ],
)
def test_storage_events(event_name, event_kind):
    ctx = scenario.Context(ContextCharm, meta=META, actions=ACTIONS)
    storage = scenario.Storage('foo')
    state_in = scenario.State(storages=[storage])
    # These look like:
    #   ctx.run(ctx.on.storage_attached(storage), state)
    with ctx(getattr(ctx.on, event_name)(storage), state_in) as mgr:
        mgr.run()
        storage_event, collect_status = mgr.charm.observed
        assert isinstance(storage_event, event_kind)
        assert storage_event.storage.name == storage.name
        assert storage_event.storage.index == storage.index
        assert isinstance(collect_status, ops.CollectStatusEvent)


def test_action_event_no_params():
    ctx = scenario.Context(ContextCharm, meta=META, actions=ACTIONS)
    # These look like:
    #   ctx.run(ctx.on.action(action_name), state)
    with ctx(ctx.on.action('act'), scenario.State()) as mgr:
        mgr.run()
        action_event, collect_status = mgr.charm.observed
        assert isinstance(action_event, ops.ActionEvent)
        assert isinstance(collect_status, ops.CollectStatusEvent)


def test_action_event_with_params():
    ctx = scenario.Context(ContextCharm, meta=META, actions=ACTIONS)
    # These look like:
    #   ctx.run(ctx.on.action(action=action), state)
    # So that any parameters can be included and the ID can be customised.
    call_event = ctx.on.action('act', params={'param': 'hello'})
    with ctx(call_event, scenario.State()) as mgr:
        mgr.run()
        action_event, collect_status = mgr.charm.observed
        assert isinstance(action_event, ops.ActionEvent)
        assert action_event.id == call_event.action.id
        assert action_event.params['param'] == call_event.action.params['param']
        assert isinstance(collect_status, ops.CollectStatusEvent)


def test_pebble_ready_event():
    ctx = scenario.Context(ContextCharm, meta=META, actions=ACTIONS)
    container = scenario.Container('bar', can_connect=True)
    state_in = scenario.State(containers=[container])
    # These look like:
    #   ctx.run(ctx.on.pebble_ready(container), state)
    with ctx(ctx.on.pebble_ready(container), state_in) as mgr:
        mgr.run()
        pebble_ready_event, collect_status = mgr.charm.observed
        assert isinstance(pebble_ready_event, ops.PebbleReadyEvent)
        assert pebble_ready_event.workload.name == container.name
        assert isinstance(collect_status, ops.CollectStatusEvent)


@pytest.mark.parametrize('as_kwarg', [True, False])
@pytest.mark.parametrize(
    'event_name, event_kind',
    [
        ('relation_created', ops.RelationCreatedEvent),
        ('relation_broken', ops.RelationBrokenEvent),
    ],
)
def test_relation_app_events(as_kwarg, event_name, event_kind):
    ctx = scenario.Context(ContextCharm, meta=META, actions=ACTIONS)
    relation = scenario.Relation('baz')
    state_in = scenario.State(relations=[relation])
    # These look like:
    #   ctx.run(ctx.on.relation_created(relation), state)
    if as_kwarg:
        args = ()
        kwargs = {'relation': relation}
    else:
        args = (relation,)
        kwargs = {}
    with ctx(getattr(ctx.on, event_name)(*args, **kwargs), state_in) as mgr:
        mgr.run()
        relation_event, collect_status = mgr.charm.observed
        assert isinstance(relation_event, event_kind)
        assert relation_event.relation.id == relation.id
        assert relation_event.app.name == relation.remote_app_name
        assert relation_event.unit is None
        assert isinstance(collect_status, ops.CollectStatusEvent)


def test_relation_complex_name():
    meta = copy.deepcopy(META)
    meta['requires']['foo-bar-baz'] = {'interface': 'another-one'}
    ctx = scenario.Context(ContextCharm, meta=meta, actions=ACTIONS)
    relation = scenario.Relation('foo-bar-baz')
    state_in = scenario.State(relations=[relation])
    with ctx(ctx.on.relation_created(relation), state_in) as mgr:
        mgr.run()
        relation_event, collect_status = mgr.charm.observed
        assert isinstance(relation_event, ops.RelationCreatedEvent)
        assert relation_event.relation.id == relation.id
        assert relation_event.app.name == relation.remote_app_name
        assert relation_event.unit is None
        assert isinstance(collect_status, ops.CollectStatusEvent)


@pytest.mark.parametrize('event_name', ['relation_created', 'relation_broken'])
def test_relation_events_as_positional_arg(event_name):
    ctx = scenario.Context(ContextCharm, meta=META, actions=ACTIONS)
    relation = scenario.Relation('baz')
    state_in = scenario.State(relations=[relation])
    with pytest.raises(TypeError):
        ctx.run(getattr(ctx.on, event_name)(relation, 0), state_in)


@pytest.mark.parametrize(
    'event_name, event_kind',
    [
        ('relation_joined', ops.RelationJoinedEvent),
        ('relation_changed', ops.RelationChangedEvent),
    ],
)
def test_relation_unit_events_default_unit(event_name, event_kind):
    ctx = scenario.Context(ContextCharm, meta=META, actions=ACTIONS)
    relation = scenario.Relation('baz', remote_units_data={1: {'x': 'y'}})
    state_in = scenario.State(relations=[relation])
    # These look like:
    #   ctx.run(ctx.on.baz_relation_changed, state)
    # The unit is chosen automatically.
    with ctx(getattr(ctx.on, event_name)(relation), state_in) as mgr:
        mgr.run()
        relation_event, collect_status = mgr.charm.observed
        assert isinstance(relation_event, event_kind)
        assert relation_event.relation.id == relation.id
        assert relation_event.app.name == relation.remote_app_name
        assert relation_event.unit.name == 'remote/1'
        assert isinstance(collect_status, ops.CollectStatusEvent)


@pytest.mark.parametrize(
    'event_name, event_kind',
    [
        ('relation_joined', ops.RelationJoinedEvent),
        ('relation_changed', ops.RelationChangedEvent),
    ],
)
def test_relation_unit_events(event_name, event_kind):
    ctx = scenario.Context(ContextCharm, meta=META, actions=ACTIONS)
    relation = scenario.Relation('baz', remote_units_data={1: {'x': 'y'}, 2: {'x': 'z'}})
    state_in = scenario.State(relations=[relation])
    # These look like:
    #   ctx.run(ctx.on.baz_relation_changed(unit=unit_ordinal), state)
    with ctx(getattr(ctx.on, event_name)(relation, remote_unit=2), state_in) as mgr:
        mgr.run()
        relation_event, collect_status = mgr.charm.observed
        assert isinstance(relation_event, event_kind)
        assert relation_event.relation.id == relation.id
        assert relation_event.app.name == relation.remote_app_name
        assert relation_event.unit.name == 'remote/2'
        assert isinstance(collect_status, ops.CollectStatusEvent)


def test_relation_departed_event():
    ctx = scenario.Context(ContextCharm, meta=META, actions=ACTIONS)
    relation = scenario.Relation('baz')
    state_in = scenario.State(relations=[relation])
    # These look like:
    #   ctx.run(ctx.on.baz_relation_departed(unit=unit_num, departing_unit=unit_num), state)
    with ctx(ctx.on.relation_departed(relation, remote_unit=2, departing_unit=1), state_in) as mgr:
        mgr.run()
        relation_event, collect_status = mgr.charm.observed
        assert isinstance(relation_event, ops.RelationDepartedEvent)
        assert relation_event.relation.id == relation.id
        assert relation_event.app.name == relation.remote_app_name
        assert relation_event.unit.name == 'remote/2'
        assert relation_event.departing_unit.name == 'remote/1'
        assert isinstance(collect_status, ops.CollectStatusEvent)


class CustomEvent(ops.EventBase):
    pass


class CustomEventWithArgs(CustomEvent):
    arg0: str
    arg1: int

    def __init__(self, handle: ops.Handle, arg0: str = '', arg1: int = 0):
        super().__init__(handle)
        self.arg0 = arg0
        self.arg1 = arg1

    def snapshot(self):
        base = super().snapshot()
        base.update({'arg0': self.arg0, 'arg1': self.arg1})
        return base

    def restore(self, snapshot: dict[str, typing.Any]):
        super().restore(snapshot)
        self.arg0 = snapshot['arg0']
        self.arg1 = snapshot['arg1']


class CustomRelationEvent(ops.RelationChangedEvent):
    pass


class CustomEventWithScenarioArgs(CustomEvent):
    cloudcredential: ops.CloudCredential
    cloudspec: ops.CloudSpec
    secret: ops.Secret
    relation: ops.Relation
    peerrelation: ops.Relation
    subordinaterelation: ops.Relation
    notice: ops.pebble.Notice
    checkinfo: ops.pebble.CheckInfo
    container: ops.Container
    errorstatus: ops.ErrorStatus
    activestatus: ops.ActiveStatus
    blockedstatus: ops.BlockedStatus
    maintenancestatus: ops.MaintenanceStatus
    waitingstatus: ops.WaitingStatus
    tcpport: ops.Port
    udpport: ops.Port
    icmpport: ops.Port
    storage: ops.Storage

    def __init__(self, handle: ops.Handle, **kwargs: typing.Any):
        super().__init__(handle)
        for key, value in kwargs.items():
            setattr(self, key, value)

    def snapshot(self):
        base = super().snapshot()
        # This loses a lot of the details, but for the test all we care about is
        # that the type and the 'primary key' are correct.
        base['cloudcredential'] = self.cloudcredential.auth_type
        base['cloudspec'] = self.cloudspec.name
        base['secret'] = self.secret.id
        base['relation'] = self.relation.name
        base['peerrelation'] = self.peerrelation.name
        base['subordinaterelation'] = self.subordinaterelation.name
        base['relation_id'] = self.relation.id
        base['peerrelation_id'] = self.peerrelation.id
        base['subordinaterelation_id'] = self.subordinaterelation.id
        base['notice_id'] = self.notice.id
        base['notice_key'] = self.notice.key
        base['checkinfo'] = self.checkinfo.name
        base['container'] = self.container.name
        base['errorstatus'] = self.errorstatus.message
        base['activestatus'] = self.activestatus.message
        base['blockedstatus'] = self.blockedstatus.message
        base['maintenancestatus'] = self.maintenancestatus.message
        base['waitingstatus'] = self.waitingstatus.message
        base['tcpport'] = self.tcpport.port
        base['udpport'] = self.udpport.port
        base['storage_name'] = self.storage.name
        base['storage_index'] = self.storage.index
        return base

    def restore(self, snapshot: dict[str, typing.Any]):
        super().restore(snapshot)
        self.cloudcredential = ops.CloudCredential(auth_type=snapshot['cloudcredential'])
        self.cloudspec = ops.CloudSpec('', snapshot['cloudspec'])
        self.secret = self.framework.model.get_secret(id=snapshot['secret'])
        relation = self.framework.model.get_relation(
            snapshot['relation'], relation_id=snapshot['relation_id']
        )
        assert relation is not None
        self.relation = relation
        peerrelation = self.framework.model.get_relation(
            snapshot['peerrelation'], relation_id=snapshot['peerrelation_id']
        )
        assert peerrelation is not None
        self.peerrelation = peerrelation
        subordinaterelation = self.framework.model.get_relation(
            snapshot['subordinaterelation'],
            relation_id=snapshot['subordinaterelation_id'],
        )
        assert subordinaterelation is not None
        self.subordinaterelation = subordinaterelation
        now = datetime.datetime.now()
        self.notice = ops.pebble.Notice(
            snapshot['notice_id'],
            None,
            '',
            snapshot['notice_key'],
            now,
            now,
            now,
            1,
        )
        self.checkinfo = ops.pebble.CheckInfo(snapshot['checkinfo'], None, '')
        self.container = self.framework.model.unit.get_container(snapshot['container'])
        self.errorstatus = ops.ErrorStatus(message=snapshot['errorstatus'])
        self.activestatus = ops.ActiveStatus(message=snapshot['activestatus'])
        self.blockedstatus = ops.BlockedStatus(message=snapshot['blockedstatus'])
        self.maintenancestatus = ops.MaintenanceStatus(message=snapshot['maintenancestatus'])
        self.waitingstatus = ops.WaitingStatus(message=snapshot['waitingstatus'])
        self.tcpport = ops.Port(protocol='tcp', port=snapshot['tcpport'])
        self.udpport = ops.Port(protocol='udp', port=snapshot['udpport'])
        self.icmpport = ops.Port(protocol='icmp', port=None)
        for storage in self.framework.model.storages[snapshot['storage_name']]:
            if storage.index == snapshot['storage_index']:
                self.storage = storage
                break


class CustomEvents(ops.ObjectEvents):
    foo_started = ops.EventSource(CustomEvent)
    foo_changed = ops.EventSource(CustomEventWithArgs)
    foo_relation_changed = ops.EventSource(CustomRelationEvent)
    state_event = ops.EventSource(CustomEventWithScenarioArgs)


class MyConsumer(ops.Object):
    on = CustomEvents()  # type: ignore

    def __init__(self, charm: ops.CharmBase):
        super().__init__(charm, 'my-consumer')


class CustomCharm(ContextCharm):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self.consumer = MyConsumer(self)
        framework.observe(self.consumer.on.foo_started, self._on_event)
        framework.observe(self.consumer.on.foo_changed, self._on_event)
        framework.observe(self.consumer.on.foo_relation_changed, self._on_event)
        framework.observe(self.consumer.on.state_event, self._on_event)


def test_custom_event_no_args():
    ctx = scenario.Context(CustomCharm, meta=META, actions=ACTIONS)
    with ctx(ctx.on.custom(MyConsumer.on.foo_started), scenario.State()) as mgr:
        mgr.run()
        custom_event, collect_status = mgr.charm.observed
        assert isinstance(collect_status, ops.CollectStatusEvent)
        assert isinstance(custom_event, CustomEvent)


def test_custom_event_with_args():
    ctx = scenario.Context(CustomCharm, meta=META, actions=ACTIONS)
    with ctx(
        ctx.on.custom(MyConsumer.on.foo_changed, 'foo', arg1=42),
        scenario.State(),
    ) as mgr:
        mgr.run()
        custom_event, collect_status = mgr.charm.observed
        assert isinstance(collect_status, ops.CollectStatusEvent)
        assert isinstance(custom_event, CustomEventWithArgs)
        assert custom_event.arg0 == 'foo'
        assert custom_event.arg1 == 42


def test_custom_event_is_hookevent():
    ctx = scenario.Context(CustomCharm, meta=META, actions=ACTIONS)
    with pytest.raises(ValueError):
        ctx.on.custom(MyConsumer.on.foo_relation_changed)


def test_custom_event_with_scenario_args():
    meta = META.copy()
    meta['requires']['endpoint'] = {'interface': 'int1'}
    meta['requires']['sub-endpoint'] = {'interface': 'int2', 'scope': 'container'}
    meta['peers'] = {'peer-endpoint': {'interface': 'int3'}}
    meta['containers']['container'] = {}
    meta['storage']['store'] = {'type': 'filesystem'}
    ctx = scenario.Context(CustomCharm, meta=meta, actions=ACTIONS)

    cloudcredential = scenario.CloudCredential(auth_type='auth')
    cloudspec = scenario.CloudSpec('cloud')
    secret = scenario.Secret({'password': 'xxxx'})
    relation = scenario.Relation('endpoint')
    peerrelation = scenario.PeerRelation('peer-endpoint')
    subordinaterelation = scenario.SubordinateRelation('sub-endpoint')
    notice = scenario.Notice('key.example.com')
    layer = ops.pebble.Layer({
        'checks': {'check1': {'override': 'replace', 'startup': 'enabled', 'threshold': 3}}
    })
    checkinfo = scenario.CheckInfo('check1', level=ops.pebble.CheckLevel.UNSET)
    container = scenario.Container(
        'container', notices=[notice], check_infos={checkinfo}, layers={'layer': layer}
    )
    errorstatus = scenario.ErrorStatus('error')
    activestatus = scenario.ActiveStatus('working')
    blockedstatus = scenario.BlockedStatus('blocked')
    maintenancestatus = scenario.MaintenanceStatus('maintaining')
    waitingstatus = scenario.WaitingStatus('waiting')
    tcpport = scenario.TCPPort(8000)
    udpport = scenario.UDPPort(8001)
    icmpport = scenario.ICMPPort()
    storage = scenario.Storage('store')

    state = scenario.State(
        secrets={secret},
        relations={relation, peerrelation, subordinaterelation},
        containers={container},
        storages={storage},
    )

    with ctx(
        ctx.on.custom(
            MyConsumer.on.state_event,
            cloudcredential=cloudcredential,
            cloudspec=cloudspec,
            secret=secret,
            relation=relation,
            peerrelation=peerrelation,
            subordinaterelation=subordinaterelation,
            notice=notice,
            checkinfo=checkinfo,
            container=container,
            errorstatus=errorstatus,
            activestatus=activestatus,
            blockedstatus=blockedstatus,
            maintenancestatus=maintenancestatus,
            waitingstatus=waitingstatus,
            tcpport=tcpport,
            udpport=udpport,
            icmpport=icmpport,
            storage=storage,
        ),
        state,
    ) as mgr:
        mgr.run()
        evt, cs = mgr.charm.observed
        assert isinstance(cs, ops.CollectStatusEvent)
        assert isinstance(evt, CustomEventWithScenarioArgs)
        assert isinstance(evt.cloudcredential, ops.CloudCredential)
        assert evt.cloudcredential.auth_type == cloudcredential.auth_type
        assert isinstance(evt.cloudspec, ops.CloudSpec)
        assert evt.cloudspec.name == cloudspec.name
        assert isinstance(evt.secret, ops.Secret)
        assert evt.secret.id == secret.id
        assert isinstance(evt.relation, ops.Relation)
        assert evt.relation.name == relation.endpoint
        assert isinstance(evt.peerrelation, ops.Relation)
        assert evt.peerrelation.name == peerrelation.endpoint
        assert isinstance(evt.subordinaterelation, ops.Relation)
        assert evt.subordinaterelation.name == subordinaterelation.endpoint
        assert isinstance(evt.notice, ops.pebble.Notice)
        assert evt.notice.key == notice.key
        assert isinstance(evt.checkinfo, ops.pebble.CheckInfo)
        assert evt.checkinfo.name == checkinfo.name
        assert isinstance(evt.container, ops.Container)
        assert evt.container.name == container.name
        assert isinstance(evt.errorstatus, ops.ErrorStatus)
        assert evt.errorstatus.message == errorstatus.message
        assert isinstance(evt.activestatus, ops.ActiveStatus)
        assert evt.activestatus.message == activestatus.message
        assert isinstance(evt.blockedstatus, ops.BlockedStatus)
        assert evt.blockedstatus.message == blockedstatus.message
        assert isinstance(evt.maintenancestatus, ops.MaintenanceStatus)
        assert evt.maintenancestatus.message == maintenancestatus.message
        assert isinstance(evt.waitingstatus, ops.WaitingStatus)
        assert evt.waitingstatus.message == waitingstatus.message
        assert isinstance(evt.tcpport, ops.Port)
        assert evt.tcpport.protocol == 'tcp'
        assert evt.tcpport.port == tcpport.port
        assert isinstance(evt.udpport, ops.Port)
        assert evt.udpport.protocol == 'udp'
        assert evt.udpport.port == udpport.port
        assert isinstance(evt.icmpport, ops.Port)
        assert evt.icmpport.protocol == 'icmp'
        assert isinstance(evt.storage, ops.Storage)
        assert evt.storage.name == storage.name


class OtherEvent(ops.EventBase):
    pass


class OtherEvents(ops.ObjectEvents):
    foo_changed = ops.EventSource(OtherEvent)


class OtherConsumer(ops.Object):
    on = OtherEvents()  # type: ignore

    def __init__(self, charm: ops.CharmBase, relation_name: str):
        super().__init__(charm, relation_name)


class TwoLibraryCharm(ContextCharm):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self.consumer1 = MyConsumer(self)
        self.consumer2 = OtherConsumer(self, 'some-relation')
        framework.observe(self.consumer1.on.foo_changed, self._on_event)
        framework.observe(self.consumer2.on.foo_changed, self._on_event)


def test_custom_event_two_libraries():
    ctx = scenario.Context(TwoLibraryCharm, meta=META, actions=ACTIONS)

    with ctx(ctx.on.custom(MyConsumer.on.foo_changed), scenario.State()) as mgr:
        mgr.run()
        evt, cs = mgr.charm.observed
        assert isinstance(cs, ops.CollectStatusEvent)
        assert isinstance(evt, CustomEvent)

    with ctx(ctx.on.custom(OtherConsumer.on.foo_changed), scenario.State()) as mgr:
        mgr.run()
        evt, collect_status = mgr.charm.observed
        assert isinstance(collect_status, ops.CollectStatusEvent)
        assert isinstance(evt, OtherEvent)
