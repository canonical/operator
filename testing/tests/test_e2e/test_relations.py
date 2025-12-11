# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

from __future__ import annotations

from collections.abc import Callable

import pytest
import scenario
from scenario import Context
from scenario.errors import UncaughtCharmError
from scenario.state import (
    _DEFAULT_JUJU_DATABAG,
    PeerRelation,
    Relation,
    RelationBase,
    State,
    StateValidationError,
    SubordinateRelation,
    _Event,
    _next_relation_id,
)

import ops
from ops.charm import (
    CharmBase,
    CharmEvents,
    CollectStatusEvent,
    RelationBrokenEvent,
    RelationCreatedEvent,
    RelationDepartedEvent,
    RelationEvent,
)
from ops.framework import EventBase, Framework
from tests.helpers import trigger


@pytest.fixture(scope='function')
def mycharm():
    class MyCharmEvents(CharmEvents):
        @classmethod
        def define_event(cls, event_kind: str, event_type: type[EventBase]):
            if getattr(cls, event_kind, None):
                delattr(cls, event_kind)
            return super().define_event(event_kind, event_type)

    class MyCharm(CharmBase):
        _call: Callable[[MyCharm, _Event], None] | None = None
        called = False
        on = MyCharmEvents()

        def __init__(self, framework: Framework):
            super().__init__(framework)
            for evt in self.on.events().values():
                self.framework.observe(evt, self._on_event)

        def _on_event(self, event):
            if self._call:
                MyCharm.called = True
                self._call(event)

    return MyCharm


def test_get_relation(mycharm):
    def pre_event(charm: CharmBase):
        assert charm.model.get_relation('foo')
        assert charm.model.get_relation('bar') is None
        assert charm.model.get_relation('qux')
        assert charm.model.get_relation('zoo') is None

    trigger(
        State(
            config={'foo': 'bar'},
            leader=True,
            relations={
                Relation(endpoint='foo', interface='foo', remote_app_name='remote'),
                Relation(endpoint='qux', interface='qux', remote_app_name='remote'),
            },
        ),
        'start',
        mycharm,
        meta={
            'name': 'local',
            'requires': {
                'foo': {'interface': 'foo'},
                'bar': {'interface': 'bar'},
            },
            'provides': {
                'qux': {'interface': 'qux'},
                'zoo': {'interface': 'zoo'},
            },
        },
        config={'options': {'foo': {'type': 'string'}}},
        pre_event=pre_event,
    )


@pytest.mark.parametrize('test_context', ['init', 'event'])
@pytest.mark.parametrize(
    'is_leader', [pytest.param(True, id='leader'), pytest.param(False, id='minion')]
)
def test_relation_validates_access(is_leader: bool, test_context: str):
    """Test that relation databag read/write access in __init__ is the same as in observers."""

    class Charm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            framework.observe(self.on['my-act'].action, self._on_action)
            self.test_validation('init')

        def _on_action(self, action: ops.ActionEvent):
            self.test_validation('event')

        def test_validation(self, context: str):
            if context != test_context:
                return
            nonlocal validated
            validated += 1
            rel = self.model.get_relation('my-rel')
            assert rel is not None

            # remote application databag
            # any unit can read the remote application databag
            remote_app_data = rel.data[rel.app]
            assert remote_app_data['k'] == 'remote val'
            assert len(remote_app_data.items()) == 1
            # no unit can write to the remote application databag
            with pytest.raises(ops.RelationDataAccessError):
                remote_app_data['k'] = 'something'

            # local application databag
            local_app_data = rel.data[self.app]
            # only the leader can read or write the local application databag
            if self.unit.is_leader():
                assert local_app_data['k'] == 'local val'  # test read
                local_app_data['k'] = 'new val'  # test write
            else:
                with pytest.raises(ops.RelationDataAccessError):
                    local_app_data['k']
            # these probably fail at real runtime with a ModelError
            # but pass here because the validation methods are only hooked up to get/set
            assert len(local_app_data.items()) == 1
            assert 'k' in local_app_data

    ctx = Context(
        Charm,
        meta={
            'name': 'charm',
            'requires': {'my-rel': {'interface': 'my-face'}},
        },
        actions={'my-act': {}},
    )
    rel_in = scenario.Relation(
        endpoint='my-rel',
        local_app_data={'k': 'local val'},
        remote_app_data={'k': 'remote val'},
    )
    validated = 0
    ctx.run(ctx.on.action('my-act'), State(relations={rel_in}, leader=is_leader))
    assert validated


def test_relation_set_single_add_del_change():
    relation_name = 'relation-name'

    class Charm(CharmBase):
        def __init__(self, framework: Framework):
            super().__init__(framework)
            framework.observe(self.on.update_status, self._update_status)

        def _update_status(self, event: EventBase):
            rel = self.model.get_relation(relation_name)
            assert rel is not None
            data = rel.data[self.unit]
            data['to-change-key'] = 'to-change-val-new'
            del data['to-remove-key']
            data['new-key'] = 'new-val'

    ctx = Context(
        Charm,
        meta={
            'name': 'charm-name',
            'peers': {relation_name: {'interface': 'interface-name'}},
        },
    )
    rel_in = PeerRelation(
        endpoint=relation_name,
        local_unit_data={
            'to-ignore-key': 'to-ignore-val',
            'to-change-key': 'to-change-val-original',
            'to-remove-key': 'to-remove-val',
        },
    )
    state = ctx.run(ctx.on.update_status(), State(relations={rel_in}))
    rel_out = state.get_relation(rel_in.id)
    assert rel_out.local_unit_data == {
        'to-ignore-key': 'to-ignore-val',
        'to-change-key': 'to-change-val-new',
        'new-key': 'new-val',
    }


@pytest.mark.parametrize(
    ('original_data', 'new_data', 'result_data'),
    [
        pytest.param(
            {},
            {'NEW-KEY-1': 'NEW-VAL-1', 'NEW-KEY-2': 'NEW-VAL-2'},
            {'NEW-KEY-1': 'NEW-VAL-1', 'NEW-KEY-2': 'NEW-VAL-2'},
            id='populate the relation data from scratch',
        ),
        pytest.param(
            {'old-key-1': 'old-val-1', 'old-key-2': 'old-val-2'},
            {},
            {'old-key-1': 'old-val-1', 'old-key-2': 'old-val-2'},
            id='make no changes',
        ),
        pytest.param(
            {'old-key-1': 'old-val-1', 'old-key-2': 'old-val-2'},
            {'NEW-KEY-1': 'NEW-VAL-1'},
            {
                'old-key-1': 'old-val-1',
                'old-key-2': 'old-val-2',
                'NEW-KEY-1': 'NEW-VAL-1',
            },
            id='insert a new key and value into existing relation data',
        ),
        pytest.param(
            {'old-key-1': 'old-val-1'},
            {'NEW-KEY-1': 'NEW-VAL-1', 'NEW-KEY-2': 'NEW-VAL-2'},
            {
                'old-key-1': 'old-val-1',
                'NEW-KEY-1': 'NEW-VAL-1',
                'NEW-KEY-2': 'NEW-VAL-2',
            },
            id='insert multiple new keys and values',
        ),
        pytest.param(
            {'old-key-1': 'old-val-1', 'old-key-2': 'old-val-2'},
            {'old-key-1': 'NEW-VAL-1'},
            {'old-key-1': 'NEW-VAL-1', 'old-key-2': 'old-val-2'},
            id='update an existing entry',
        ),
        pytest.param(
            {'old-key-1': 'old-val-1', 'old-key-2': 'old-val-2'},
            {'old-key-1': 'NEW-VAL-1', 'old-key-2': 'NEW-VAL-2'},
            {'old-key-1': 'NEW-VAL-1', 'old-key-2': 'NEW-VAL-2'},
            id='update multiple existing entries',
        ),
        pytest.param(
            {'old-key-1': 'old-val-1', 'old-key-2': 'old-val-2'},
            {
                'old-key-1': 'NEW-VAL-1',
                'old-key-2': 'NEW-VAL-2',
                'NEW-KEY-3': 'NEW-VAL-3',
            },
            {
                'old-key-1': 'NEW-VAL-1',
                'old-key-2': 'NEW-VAL-2',
                'NEW-KEY-3': 'NEW-VAL-3',
            },
            id='update multiple existing entries and add a new one',
        ),
        pytest.param(
            {'old-key-1': 'old-val-1', 'old-key-2': 'old-val-2'},
            {'old-key-1': ''},
            {'old-key-2': 'old-val-2'},
            id='delete an existing entry',
        ),
        pytest.param(
            {'old-key-1': 'old-val-1', 'old-key-2': 'old-val-2'},
            {'old-key-1': '', 'old-key-2': ''},
            {},
            id='delete multiple existing entries',
        ),
        pytest.param(
            {'old-key-1': 'old-val-1', 'old-key-2': 'old-val-2'},
            {'NEW-KEY-1': ''},
            {'old-key-1': 'old-val-1', 'old-key-2': 'old-val-2'},
            id='deleting a non-existing key has no effect',
        ),
        pytest.param(
            {'old-key-1': 'old-val-1', 'old-key-2': 'old-val-2'},
            {'old-key-1': '', 'old-key-2': '', 'NEW-KEY-1': ''},
            {},
            id='delete multiple existing entries and a non-existing key',
        ),
        pytest.param(
            {
                'old-key-1': 'old-val-1',
                'old-key-2': 'old-val-2',
                'old-key-3': 'old-val-3',
            },
            {'NEW-KEY-1': 'NEW-VAL-1', 'old-key-2': 'NEW-VAL-2', 'old-key-3': ''},
            {
                'old-key-1': 'old-val-1',
                'NEW-KEY-1': 'NEW-VAL-1',
                'old-key-2': 'NEW-VAL-2',
            },
            id='add a key, update another, and delete a third',
        ),
    ],
)
def test_relation_set_bulk_update(
    original_data: dict[str, str], new_data: dict[str, str], result_data: dict[str, str]
):
    relation_name = 'relation-name'

    class Charm(CharmBase):
        def __init__(self, framework: Framework):
            super().__init__(framework)
            framework.observe(self.on.update_status, self._update_status)

        def _update_status(self, event: EventBase):
            rel = self.model.get_relation(relation_name)
            assert rel is not None
            data = rel.data[self.unit]
            data.update(new_data)

    ctx = Context(
        Charm,
        meta={
            'name': 'charm-name',
            'peers': {relation_name: {'interface': 'interface-name'}},
        },
    )
    rel_in = PeerRelation(endpoint=relation_name, local_unit_data=original_data)
    state = ctx.run(ctx.on.update_status(), State(relations={rel_in}))
    rel_out = state.get_relation(rel_in.id)
    assert rel_out.local_unit_data == result_data


@pytest.mark.parametrize(
    'evt_name',
    ('changed', 'broken', 'departed', 'joined', 'created'),
)
@pytest.mark.parametrize(
    'remote_app_name',
    ('remote', 'prometheus', 'aodeok123'),
)
def test_relation_events(mycharm, evt_name, remote_app_name):
    relation = Relation(endpoint='foo', interface='foo', remote_app_name=remote_app_name)

    def callback(charm: CharmBase, e):
        if not isinstance(e, RelationEvent):
            return  # filter out collect status events

        if evt_name == 'broken':
            assert charm.model.get_relation('foo') is None
            assert e.relation.app.name == remote_app_name
        else:
            assert charm.model.get_relation('foo').app is not None
            assert charm.model.get_relation('foo').app.name == remote_app_name

    mycharm._call = callback

    trigger(
        State(
            relations={
                relation,
            },
        ),
        f'relation_{evt_name}',
        mycharm,
        meta={
            'name': 'local',
            'requires': {
                'foo': {'interface': 'foo'},
            },
        },
    )


@pytest.mark.parametrize(
    'evt_name,has_unit',
    [
        ('changed', True),
        ('broken', False),
        ('departed', True),
        ('joined', True),
        ('created', False),
    ],
)
@pytest.mark.parametrize(
    'remote_app_name',
    ('remote', 'prometheus', 'aodeok123'),
)
@pytest.mark.parametrize(
    'remote_unit_id',
    (0, 1),
)
def test_relation_events_attrs(mycharm, evt_name, has_unit, remote_app_name, remote_unit_id):
    relation = Relation(endpoint='foo', interface='foo', remote_app_name=remote_app_name)

    def callback(charm: CharmBase, event):
        if isinstance(event, CollectStatusEvent):
            return

        assert event.app
        if not isinstance(event, (RelationCreatedEvent, RelationBrokenEvent)):
            assert event.unit
        if isinstance(event, RelationDepartedEvent):
            assert event.departing_unit

    mycharm._call = callback

    ctx = Context(
        charm_type=mycharm,
        meta={
            'name': 'local',
            'requires': {
                'foo': {'interface': 'foo'},
            },
        },
    )
    state = State(relations={relation})
    kwargs = {}
    if has_unit:
        kwargs['remote_unit'] = remote_unit_id
    event = getattr(ctx.on, f'relation_{evt_name}')(relation, **kwargs)
    ctx.run(event, state=state)


@pytest.mark.parametrize(
    'evt_name',
    ('changed', 'broken', 'departed', 'joined', 'created'),
)
@pytest.mark.parametrize(
    'remote_app_name',
    ('remote', 'prometheus', 'aodeok123'),
)
def test_relation_events_no_attrs(mycharm, evt_name, remote_app_name, caplog):
    relation = Relation(
        endpoint='foo',
        interface='foo',
        remote_app_name=remote_app_name,
        remote_units_data={0: {}, 1: {}},  # 2 units
    )

    def callback(charm: CharmBase, event):
        if isinstance(event, CollectStatusEvent):
            return

        assert event.app  # that's always present
        # .unit is always None for created and broken.
        if isinstance(event, (RelationCreatedEvent, RelationBrokenEvent)):
            assert event.unit is None
        else:
            assert event.unit
        assert (evt_name == 'departed') is bool(getattr(event, 'departing_unit', False))

    mycharm._call = callback

    trigger(
        State(
            relations={
                relation,
            },
        ),
        f'relation_{evt_name}',
        mycharm,
        meta={
            'name': 'local',
            'requires': {
                'foo': {'interface': 'foo'},
            },
        },
    )

    if evt_name not in ('created', 'broken'):
        assert 'remote unit ID unset, and multiple remote unit IDs are present' in caplog.text


def test_relation_default_unit_data_regular():
    relation = Relation('baz')
    assert relation.local_unit_data == _DEFAULT_JUJU_DATABAG
    assert relation.remote_units_data == {0: _DEFAULT_JUJU_DATABAG}


def test_relation_default_unit_data_sub():
    relation = SubordinateRelation('baz')
    assert relation.local_unit_data == _DEFAULT_JUJU_DATABAG
    assert relation.remote_unit_data == _DEFAULT_JUJU_DATABAG


def test_relation_default_unit_data_peer():
    relation = PeerRelation('baz')
    assert relation.local_unit_data == _DEFAULT_JUJU_DATABAG


@pytest.mark.parametrize('evt_name', ('broken', 'created'))
def test_relation_events_no_remote_units(mycharm, evt_name, caplog):
    relation = Relation(
        endpoint='foo',
        interface='foo',
        remote_units_data={},  # no units
    )

    def callback(charm: CharmBase, event):
        if isinstance(event, CollectStatusEvent):
            return

        assert event.app  # that's always present
        assert not event.unit

    mycharm._call = callback

    trigger(
        State(
            relations={
                relation,
            },
        ),
        f'relation_{evt_name}',
        mycharm,
        meta={
            'name': 'local',
            'requires': {
                'foo': {'interface': 'foo'},
            },
        },
    )

    if evt_name not in ('created', 'broken'):
        assert 'remote unit ID unset; no remote unit data present' in caplog.text


@pytest.mark.parametrize('data', (set(), {}, [], (), 1, 1.0, None, b''))
def test_relation_unit_data_bad_types(mycharm, data):
    with pytest.raises(StateValidationError):
        Relation(endpoint='foo', interface='foo', remote_units_data={0: {'a': data}})


@pytest.mark.parametrize('data', (set(), {}, [], (), 1, 1.0, None, b''))
def test_relation_app_data_bad_types(mycharm, data):
    with pytest.raises(StateValidationError):
        Relation(endpoint='foo', interface='foo', local_app_data={'a': data})


@pytest.mark.parametrize(
    'evt_name',
    ('changed', 'broken', 'departed', 'joined', 'created'),
)
@pytest.mark.parametrize(
    'relation',
    (
        Relation('a', remote_units_data={0: {}}),
        PeerRelation('b', peers_data={1: {}}),
        SubordinateRelation('c'),
    ),
)
def test_relation_event_trigger(relation, evt_name, mycharm):
    meta = {
        'name': 'mycharm',
        'requires': {'a': {'interface': 'i1'}},
        'provides': {
            'c': {
                'interface': 'i3',
                # this is a subordinate relation.
                'scope': 'container',
            }
        },
        'peers': {'b': {'interface': 'i2'}},
    }
    trigger(
        State(relations={relation}),
        f'relation_{evt_name}',
        mycharm,
        meta=meta,
    )


def test_trigger_sub_relation(mycharm):
    meta = {
        'name': 'mycharm',
        'provides': {
            'foo': {
                'interface': 'bar',
                # this is a subordinate relation.
                'scope': 'container',
            }
        },
    }

    sub1 = SubordinateRelation('foo', remote_unit_data={'1': '2'}, remote_app_name='primary1')
    sub2 = SubordinateRelation('foo', remote_unit_data={'3': '4'}, remote_app_name='primary2')

    def post_event(charm: CharmBase):
        b_relations = charm.model.relations['foo']
        assert len(b_relations) == 2
        for relation in b_relations:
            assert len(relation.units) == 1

    trigger(
        State(relations={sub1, sub2}),
        'update_status',
        mycharm,
        meta=meta,
        post_event=post_event,
    )


def test_cannot_instantiate_relationbase():
    with pytest.raises(RuntimeError):
        RelationBase('')


def test_relation_ids():
    from scenario.state import _next_relation_id_counter

    initial_id = _next_relation_id_counter
    for i in range(10):
        rel = Relation('foo')
        assert rel.id == initial_id + i


def test_broken_relation_not_in_model_relations(mycharm):
    rel = Relation('foo')

    ctx = Context(mycharm, meta={'name': 'local', 'requires': {'foo': {'interface': 'foo'}}})
    with ctx(ctx.on.relation_broken(rel), state=State(relations={rel})) as mgr:
        charm = mgr.charm

        assert charm.model.get_relation('foo') is None
        assert charm.model.relations['foo'] == []


def test_get_relation_when_missing():
    class MyCharm(CharmBase):
        def __init__(self, framework):
            super().__init__(framework)
            self.framework.observe(self.on.update_status, self._on_update_status)
            self.framework.observe(self.on.config_changed, self._on_config_changed)
            self.relation = None

        def _on_update_status(self, _):
            self.relation = self.model.get_relation('foo')

        def _on_config_changed(self, _):
            self.relation = self.model.get_relation('foo', self.config['relation-id'])

    ctx = Context(
        MyCharm,
        meta={'name': 'foo', 'requires': {'foo': {'interface': 'foo'}}},
        config={'options': {'relation-id': {'type': 'int', 'description': 'foo'}}},
    )
    # There should be no error if the relation is missing - get_relation returns
    # None in that case.
    with ctx(ctx.on.update_status(), State()) as mgr:
        mgr.run()
        assert mgr.charm.relation is None

    # There should also be no error if the relation is present, of course.
    rel = Relation('foo')
    with ctx(ctx.on.update_status(), State(relations={rel})) as mgr:
        mgr.run()
        assert mgr.charm.relation.id == rel.id

    # If a relation that doesn't exist is requested, that should also not raise
    # an error.
    with ctx(ctx.on.config_changed(), State(config={'relation-id': 42})) as mgr:
        mgr.run()
        rel = mgr.charm.relation
        assert rel.id == 42
        assert not rel.active

    # If there's no defined relation with the name, then get_relation raises KeyError.
    ctx = Context(MyCharm, meta={'name': 'foo'})
    with pytest.raises((KeyError, UncaughtCharmError)) as exc:
        ctx.run(ctx.on.update_status(), State())
    assert isinstance(exc.value, KeyError) or isinstance(exc.value.__cause__, KeyError)


@pytest.mark.parametrize('klass', (Relation, PeerRelation, SubordinateRelation))
def test_relation_positional_arguments(klass):
    with pytest.raises(TypeError):
        klass('foo', 'bar', None)


def test_relation_default_values():
    expected_id = _next_relation_id(update=False)
    endpoint = 'database'
    interface = 'postgresql'
    relation = Relation(endpoint, interface)
    assert relation.id == expected_id
    assert relation.endpoint == endpoint
    assert relation.interface == interface
    assert relation.local_app_data == {}
    assert relation.local_unit_data == _DEFAULT_JUJU_DATABAG
    assert relation.remote_app_name == 'remote'
    assert relation.limit == 1
    assert relation.remote_app_data == {}
    assert relation.remote_units_data == {0: _DEFAULT_JUJU_DATABAG}


def test_subordinate_relation_default_values():
    expected_id = _next_relation_id(update=False)
    endpoint = 'database'
    interface = 'postgresql'
    relation = SubordinateRelation(endpoint, interface)
    assert relation.id == expected_id
    assert relation.endpoint == endpoint
    assert relation.interface == interface
    assert relation.local_app_data == {}
    assert relation.local_unit_data == _DEFAULT_JUJU_DATABAG
    assert relation.remote_app_name == 'remote'
    assert relation.remote_unit_id == 0
    assert relation.remote_app_data == {}
    assert relation.remote_unit_data == _DEFAULT_JUJU_DATABAG


def test_peer_relation_default_values():
    expected_id = _next_relation_id(update=False)
    endpoint = 'peers'
    interface = 'shared'
    relation = PeerRelation(endpoint, interface)
    assert relation.id == expected_id
    assert relation.endpoint == endpoint
    assert relation.interface == interface
    assert relation.local_app_data == {}
    assert relation.local_unit_data == _DEFAULT_JUJU_DATABAG
    assert relation.peers_data == {}


def test_relation_remote_model():
    class MyCharm(CharmBase):
        def __init__(self, framework):
            super().__init__(framework)
            self.framework.observe(self.on.start, self._on_start)

        def _on_start(self, event):
            relation = self.model.get_relation('foo')
            assert relation is not None
            self.remote_model_uuid = relation.remote_model.uuid

    ctx = Context(MyCharm, meta={'name': 'foo', 'requires': {'foo': {'interface': 'foo'}}})
    state = State(relations={Relation('foo')})
    with ctx(ctx.on.start(), state) as mgr:
        mgr.run()
        assert mgr.charm.remote_model_uuid
        assert mgr.charm.remote_model_uuid == mgr.charm.model.uuid

    state = State(relations={Relation('foo', remote_model_uuid='UUID')})
    with ctx(ctx.on.start(), state) as mgr:
        mgr.run()
        assert mgr.charm.remote_model_uuid == 'UUID'
        assert mgr.charm.remote_model_uuid != mgr.charm.model.uuid


def test_peer_relation_units_does_not_contain_this_unit():
    relation_name = 'relation-name'

    class Charm(CharmBase):
        def __init__(self, framework: Framework):
            super().__init__(framework)
            framework.observe(self.on.update_status, self._update_status)

        def _update_status(self, _: EventBase):
            rel = self.model.get_relation(relation_name)
            assert rel is not None
            assert self.unit not in rel.units
            data = rel.data[self.unit]
            data['this-unit'] = str(self.unit)

    ctx = Context(
        Charm,
        meta={
            'name': 'charm-name',
            'peers': {relation_name: {'interface': 'interface-name'}},
        },
    )
    rel_in = PeerRelation(
        endpoint=relation_name,
    )
    state = ctx.run(ctx.on.update_status(), State(relations={rel_in}))
    rel_out = state.get_relation(rel_in.id)
    assert rel_out.local_unit_data.get('this-unit') == '<ops.model.Unit charm-name/0>'
