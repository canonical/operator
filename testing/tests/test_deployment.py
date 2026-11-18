# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

from __future__ import annotations

import dataclasses
import importlib.util
import itertools
import pathlib
import sys
import textwrap
from collections.abc import Iterator, Sequence
from typing import Any

import pytest
from scenario import (
    ActiveStatus,
    CloudSpec,
    Container,
    Exec,
    Model,
    PeerRelation,
    Secret,
    State,
    Storage,
    UnknownStatus,
)
from scenario._deployment import App, CharmSpec, Dispatch, Juju, Unit
from scenario._juju_errors import JujuError
from scenario.errors import InconsistentScenarioError, UncaughtCharmError

import ops

META: dict[str, Any] = {'name': 'myapp'}
CONFIG: dict[str, Any] = {'options': {'log_level': {'type': 'string', 'default': 'info'}}}


class MyCharm(ops.CharmBase):
    """Sets its status from the event and its config."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        for event in (
            self.on.install,
            self.on.start,
            self.on.config_changed,
            self.on.leader_elected,
            self.on.leader_settings_changed,
        ):
            framework.observe(event, self._on_any)

    def _on_any(self, event: ops.EventBase):
        self.unit.status = ops.ActiveStatus(f'{event.handle.kind}:{self.config["log_level"]}')


PEER_META: dict[str, Any] = {
    'name': 'myapp',
    'peers': {'replicas': {'interface': 'myapp-peer'}},
}


class PeerCharm(MyCharm):
    """Also lists its peers on a change."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on['replicas'].relation_changed, self._on_peer_changed)

    def _on_peer_changed(self, _: ops.EventBase):
        relation = self.model.get_relation('replicas')
        assert relation is not None
        names = sorted(unit.name for unit in relation.units)
        self.unit.status = ops.ActiveStatus(f'peers={names}')


class PublishingCharm(ops.CharmBase):
    """Writes to its peer databags on start, so peers have something to observe."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on.start, self._on_start)
        framework.observe(self.on['replicas'].relation_changed, self._on_changed)

    def _on_start(self, _: ops.EventBase):
        relation = self.model.get_relation('replicas')
        assert relation is not None
        relation.data[self.unit]['ready'] = 'yes'
        if self.unit.is_leader():
            relation.data[self.app]['cluster'] = 'formed'

    def _on_changed(self, _: ops.EventBase):
        relation = self.model.get_relation('replicas')
        assert relation is not None
        ready = sorted(u.name for u in relation.units if relation.data[u].get('ready') == 'yes')
        self.unit.status = ops.ActiveStatus(f'ready={ready}')


class ChattyCharm(ops.CharmBase):
    """Writes a new value to its databag on every change: never converges."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on['replicas'].relation_changed, self._on_changed)
        framework.observe(self.on.start, self._on_changed)

    def _on_changed(self, _: ops.EventBase):
        relation = self.model.get_relation('replicas')
        assert relation is not None
        previous = int(relation.data[self.unit].get('counter', '0'))
        relation.data[self.unit]['counter'] = str(previous + 1)


class FlipFlopCharm(ops.CharmBase):
    """Flips its published flag whenever a peer changes: loops between two states."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on.start, self._on_changed)
        framework.observe(self.on['replicas'].relation_changed, self._on_changed)

    def _on_changed(self, _: ops.EventBase):
        relation = self.model.get_relation('replicas')
        assert relation is not None
        flag = relation.data[self.unit].get('flag')
        relation.data[self.unit]['flag'] = 'off' if flag == 'on' else 'on'


class SecretCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on.leader_elected, self._on_leader_elected)

    def _on_leader_elected(self, _: ops.EventBase):
        self.app.add_secret({'password': 'hunter2'}, label='admin')


class TwoSecretsCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on.leader_elected, self._add_secret)
        framework.observe(self.on.start, self._add_secret)

    def _add_secret(self, event: ops.EventBase):
        self.app.add_secret({'created': 'yes'}, label=event.handle.kind)


class VersionCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on.install, self._on_install)

    def _on_install(self, _: ops.EventBase):
        self.unit.status = ops.ActiveStatus(str(self.model.juju_version))


class TrustCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on.install, self._on_install)

    def _on_install(self, _: ops.EventBase):
        try:
            message = f'cloud={self.model.get_cloud_spec().name}'
        except ops.ModelError as e:
            message = str(e)
        self.unit.status = ops.ActiveStatus(message)


class ExecCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on['workload'].pebble_ready, self._on_ready)

    def _on_ready(self, event: ops.PebbleReadyEvent):
        stdout, _ = event.workload.exec(['update-ca-certificates']).wait_output()
        self.unit.status = ops.ActiveStatus(stdout.strip())


class WaitingCharm(ops.CharmBase):
    """Waits for its container, as a charm should, and records what it saw."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        for event in (self.on.install, self.on.config_changed, self.on.start):
            framework.observe(event, self._on_any)
        framework.observe(self.on['workload'].pebble_ready, self._on_any)

    def _on_any(self, event: ops.EventBase):
        if self.unit.get_container('workload').can_connect():
            self.unit.status = ops.ActiveStatus(f'{event.handle.kind}: connected')
        else:
            self.unit.status = ops.MaintenanceStatus(f'{event.handle.kind}: waiting')


class UnguardedCharm(ops.CharmBase):
    """Calls Pebble in install without checking it can connect."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on.install, self._on_install)

    def _on_install(self, _: ops.EventBase):
        self.unit.get_container('workload').replan()


class NoMetadataCharm(ops.CharmBase):
    pass


EXEC_META: dict[str, Any] = {'name': 'execy', 'containers': {'workload': {}}}
EXEC_TEMPLATE = State(
    containers={
        Container(
            'workload',
            execs={Exec(['update-ca-certificates'], stdout='updated\n')},
        )
    },
)


def spec(
    charm_type: type[ops.CharmBase],
    meta: dict[str, Any] = META,
    config: dict[str, Any] | None = CONFIG,
) -> CharmSpec[Any]:
    """A CharmSpec with the config options in charmcraft.yaml shape."""
    full = {**meta, 'config': config} if config is not None else meta
    return CharmSpec(charm_type, meta=full)


def deploy_mycharm(juju: Juju, *, config_schema: dict[str, Any] = CONFIG, **kwargs: Any) -> App:
    return juju.deploy(spec(MyCharm, config=config_schema), app='myapp', **kwargs)


def peer_relation(unit: Unit) -> PeerRelation:
    relation = unit.state.get_relations('replicas')[0]
    assert isinstance(relation, PeerRelation)
    return relation


def events(trace: Sequence[Dispatch], unit: str) -> list[str]:
    return [d.event.name for d in trace if d.unit_name == unit]


@pytest.fixture
def juju() -> Iterator[Juju]:
    with Juju() as j:
        yield j


# The model


def test_the_default_model_is_the_same_for_every_juju():
    with Juju() as one, Juju() as two:
        first = deploy_mycharm(one).leader.state.model
        second = deploy_mycharm(two).leader.state.model
    assert first == second
    assert type(first) is Model
    assert first.name == 'test-model'
    assert first.type == 'kubernetes'
    assert first.cloud_spec == CloudSpec(type='kubernetes', name='localhost')


def test_an_explicit_name_and_uuid_are_kept():
    uuid = '6b23fcd2-0b0c-4d2e-8d7a-6b23fcd2a88a'
    with Juju('mine', uuid=uuid) as j:
        app = deploy_mycharm(j, num_units=2)
        for unit in app.units.values():
            assert (unit.state.model.name, unit.state.model.uuid) == ('mine', uuid)


@pytest.mark.parametrize(
    ('cloud_type', 'model_type'), [('kubernetes', 'kubernetes'), ('lxd', 'lxd')]
)
def test_the_cloud_spec_s_type_decides_the_model_type(cloud_type: str, model_type: str):
    cloud_spec = CloudSpec(type=cloud_type, name='localhost')
    with Juju(cloud_spec=cloud_spec) as j:
        model = deploy_mycharm(j).leader.state.model
    assert model.type == model_type
    assert model.cloud_spec == cloud_spec


# deploy


def test_deploy_creates_units_with_unit_zero_the_leader(juju: Juju):
    app = deploy_mycharm(juju, num_units=3)
    assert app.name == 'myapp'
    assert juju.apps == {'myapp': app}
    assert [unit.name for unit in app.units.values()] == ['myapp/0', 'myapp/1', 'myapp/2']
    assert app.leader is app.units[0]
    assert [unit.is_leader for unit in app.units.values()] == [True, False, False]
    assert [unit.state.leader for unit in app.units.values()] == [True, False, False]
    assert {unit.state.planned_units for unit in app.units.values()} == {3}


def test_deploy_runs_the_startup_sequence(juju: Juju):
    deploy_mycharm(juju, num_units=2)
    trace = juju.settle()
    assert events(trace, 'myapp/0') == ['install', 'leader_elected', 'config_changed', 'start']
    assert events(trace, 'myapp/1') == [
        'install',
        'leader_settings_changed',
        'config_changed',
        'start',
    ]


@pytest.mark.parametrize('juju_version', ['4.0.0', '4.0.9', '4.1.2'])
def test_from_juju_4_non_leaders_get_no_leader_settings_changed(juju: Juju, juju_version: str):
    deploy_mycharm(juju, num_units=3, juju_version=juju_version)
    trace = juju.settle()
    assert events(trace, 'myapp/0') == ['install', 'leader_elected', 'config_changed', 'start']
    for unit in ('myapp/1', 'myapp/2'):
        assert events(trace, unit) == ['install', 'config_changed', 'start']


@pytest.mark.parametrize(
    ('juju_version', 'leadership'),
    [('3.6.14', ['leader_settings_changed']), ('4.0.9', [])],
)
def test_a_unit_added_later_gets_leader_settings_changed_only_before_juju_4(
    juju: Juju, juju_version: str, leadership: list[str]
):
    app = juju.deploy(CharmSpec(WaitingCharm, meta=EXEC_META), juju_version=juju_version)
    juju.settle()
    juju.add_unit(app)
    trace = juju.settle()
    assert events(trace, 'execy/1') == [
        'install',
        *leadership,
        'config_changed',
        'start',
        'workload_pebble_ready',
    ]


def test_from_juju_4_a_machine_model_keeps_the_rest_of_the_startup_order():
    meta = {**META, 'storage': {'data': {'type': 'filesystem'}}}
    with Juju(cloud_spec=CloudSpec(type='lxd', name='localhost')) as j:
        j.deploy(spec(MyCharm, meta), num_units=2, juju_version='4.0.9')
        trace = j.settle()
    assert events(trace, 'myapp/0') == [
        'data_storage_attached',
        'install',
        'leader_elected',
        'config_changed',
        'start',
    ]
    assert events(trace, 'myapp/1') == [
        'data_storage_attached',
        'install',
        'config_changed',
        'start',
    ]


@pytest.mark.parametrize(
    ('config', 'expected'), [(None, 'info'), ({'log_level': 'trace'}, 'trace')]
)
def test_deploy_config_is_merged_over_the_defaults(
    juju: Juju, config: dict[str, Any] | None, expected: str
):
    app = deploy_mycharm(juju, config=config)
    assert app.config == {'log_level': expected}
    juju.settle()
    assert app.leader.state.config == {'log_level': expected}
    assert app.leader.state.unit_status == ActiveStatus(f'start:{expected}')


def test_deploy_rejects_a_duplicate_app_name(juju: Juju):
    deploy_mycharm(juju)
    with pytest.raises(JujuError, match='already deployed'):
        deploy_mycharm(juju)


def test_deploy_needs_an_app_name_when_the_metadata_has_none(juju: Juju):
    with pytest.raises(JujuError, match='pass app='):
        juju.deploy(CharmSpec(MyCharm, meta={}))
    assert not juju.apps


def test_deploy_rejects_zero_units(juju: Juju):
    with pytest.raises(JujuError, match='at least 1'):
        deploy_mycharm(juju, num_units=0)
    assert not juju.apps


def test_deploy_creates_containers_and_runs_pebble_ready(juju: Juju):
    app = juju.deploy(spec(MyCharm, {**META, 'containers': {'workload': {}}}))
    trace = juju.settle()
    assert trace[-1].event.name == 'workload_pebble_ready'
    assert {c.name for c in app.leader.state.containers} == {'workload'}


def connectable_now(state: State) -> dict[str, bool]:
    return {c.name: c.can_connect for c in state.containers}


def connectable(dispatch: Dispatch) -> dict[str, bool]:
    return connectable_now(dispatch.state_in)


def test_a_container_can_be_connected_to_from_its_pebble_ready(juju: Juju):
    app = juju.deploy(CharmSpec(WaitingCharm, meta=EXEC_META))
    trace = juju.settle()
    assert [(d.event.name, connectable(d)) for d in trace] == [
        ('install', {'workload': False}),
        ('leader_elected', {'workload': False}),
        ('config_changed', {'workload': False}),
        ('start', {'workload': False}),
        ('workload_pebble_ready', {'workload': True}),
    ]
    assert trace[-1].event._container == Container('workload', can_connect=True)
    assert app.leader.state.unit_status == ActiveStatus('workload_pebble_ready: connected')


def test_a_charm_that_calls_pebble_in_install_fails(juju: Juju):
    juju.deploy(CharmSpec(UnguardedCharm, meta=EXEC_META))
    with pytest.raises(UncaughtCharmError, match='Cannot connect to Pebble'):
        juju.settle()


def test_each_container_is_connected_by_its_own_pebble_ready(juju: Juju):
    meta: dict[str, Any] = {'name': 'two', 'containers': {'first': {}, 'second': {}}}
    juju.deploy(CharmSpec(MyCharm, meta={**meta, 'config': CONFIG}))
    trace = juju.settle()
    assert [(d.event.name, connectable(d)) for d in trace[-2:]] == [
        ('first_pebble_ready', {'first': True, 'second': False}),
        ('second_pebble_ready', {'first': True, 'second': True}),
    ]


def test_a_unit_added_later_waits_for_its_own_pebble_ready(juju: Juju):
    app = juju.deploy(CharmSpec(WaitingCharm, meta=EXEC_META))
    juju.settle()
    unit = juju.add_unit(app)
    assert connectable_now(unit.state) == {'workload': False}
    assert connectable_now(app.leader.state) == {'workload': True}
    trace = juju.settle()
    assert [(d.event.name, connectable(d)) for d in trace] == [
        ('install', {'workload': False}),
        ('leader_settings_changed', {'workload': False}),
        ('config_changed', {'workload': False}),
        ('start', {'workload': False}),
        ('workload_pebble_ready', {'workload': True}),
    ]


def test_a_machine_model_has_unconnectable_containers_and_no_pebble_ready():
    with Juju(cloud_spec=CloudSpec(type='lxd', name='localhost')) as j:
        app = j.deploy(spec(MyCharm, {**META, 'containers': {'workload': {}}}))
        trace = j.settle()
    assert events(trace, 'myapp/0') == ['install', 'leader_elected', 'config_changed', 'start']
    assert app.leader.state.containers == {Container('workload', can_connect=False)}


def test_a_charm_spec_can_be_deployed_more_than_once(juju: Juju):
    charm = spec(MyCharm)
    one = juju.deploy(charm, app='one')
    two = juju.deploy(charm, app='two')
    juju.settle()
    assert one.leader.state.unit_status == ActiveStatus('start:info')
    assert two.leader.state.unit_status == ActiveStatus('start:info')


def test_app_meta_is_charmcraft_shaped_and_read_only(juju: Juju):
    app = juju.deploy(CharmSpec(MyCharm, meta={**META, 'config': CONFIG, 'actions': {}}))
    assert app.meta == {**META, 'config': CONFIG, 'actions': {}}
    with pytest.raises(TypeError):
        app.meta['name'] = 'other'  # pyright: ignore[reportIndexIssue]
    with pytest.raises(TypeError):
        app.units[5] = app.leader  # pyright: ignore[reportIndexIssue]


def test_a_charm_class_reads_its_metadata_from_disk(juju: Juju, tmp_path: pathlib.Path):
    (tmp_path / 'src').mkdir()
    (tmp_path / 'charmcraft.yaml').write_text(
        textwrap.dedent("""\
            name: ondisk
            type: charm
            summary: A charm on disk.
            description: A charm on disk.
            config:
              options:
                port: {type: int, default: 80}
        """)
    )
    (tmp_path / 'src' / 'charm.py').write_text(
        textwrap.dedent("""\
            import ops

            class OnDiskCharm(ops.CharmBase):
                def __init__(self, framework):
                    super().__init__(framework)
                    framework.observe(self.on.start, self._on_start)

                def _on_start(self, _):
                    self.unit.status = ops.ActiveStatus(f'port={self.config["port"]}')
        """)
    )
    module_spec = importlib.util.spec_from_file_location(
        '_test_deployment_ondisk', tmp_path / 'src' / 'charm.py'
    )
    assert module_spec is not None and module_spec.loader is not None
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[module_spec.name] = module
    try:
        module_spec.loader.exec_module(module)
        app = juju.deploy(module.OnDiskCharm)
        juju.settle()
    finally:
        del sys.modules[module_spec.name]
    assert app.name == 'ondisk'
    assert app.leader.state.unit_status == ActiveStatus('port=80')


def test_a_charm_class_with_no_metadata_needs_a_charm_spec(juju: Juju):
    with pytest.raises(JujuError, match='Wrap it in a CharmSpec'):
        juju.deploy(NoMetadataCharm)


def test_deploy_takes_only_a_charm_class_or_a_charm_spec(juju: Juju):
    with pytest.raises(JujuError, match='a charm class or a CharmSpec'):
        juju.deploy('./charms/myapp')  # pyright: ignore[reportArgumentType]


@pytest.mark.parametrize(
    ('cloud_type', 'trust', 'juju_version', 'message'),
    [
        ('kubernetes', True, '3.6.10', 'cloud=localhost'),
        ('kubernetes', False, '3.6.10', 'not trusted'),
        ('kubernetes', True, '3.6.9', 'cloud spec is empty'),
        ('lxd', True, '3.6.9', 'cloud=localhost'),
    ],
)
def test_a_trusted_charm_gets_the_cloud_spec(
    cloud_type: str, trust: bool, juju_version: str, message: str
):
    with Juju(cloud_spec=CloudSpec(type=cloud_type, name='localhost')) as j:
        app = j.deploy(
            CharmSpec(TrustCharm, meta={'name': 'trusty'}), trust=trust, juju_version=juju_version
        )
        j.settle()
    assert message in app.leader.state.unit_status.message


def test_the_charm_sees_the_juju_version_it_was_deployed_with(juju: Juju):
    app = juju.deploy(CharmSpec(VersionCharm, meta={'name': 'versioned'}), juju_version='3.5.4')
    juju.settle()
    assert app.leader.state.unit_status == ActiveStatus('3.5.4')


TYPED_CONFIG: dict[str, Any] = {
    'options': {
        'log_level': {'type': 'string', 'default': 'info'},
        'port': {'type': 'int'},
        'ratio': {'type': 'float'},
        'debug': {'type': 'boolean'},
    }
}


@pytest.mark.parametrize(
    'values',
    [
        {'log_level': 1},
        {'port': '8080'},
        {'port': True},
        {'ratio': 'half'},
        {'debug': 'yes'},
    ],
)
def test_deploy_rejects_config_of_the_wrong_type(juju: Juju, values: dict[str, Any]):
    with pytest.raises(JujuError, match=f'{next(iter(values))!r} is a'):
        deploy_mycharm(juju, config_schema=TYPED_CONFIG, config=values)
    assert not juju.apps


def test_deploy_accepts_config_of_the_right_type(juju: Juju):
    values = {'log_level': 'debug', 'port': 8080, 'ratio': 0.5, 'debug': True}
    app = deploy_mycharm(juju, config_schema=TYPED_CONFIG, config=values)
    juju.settle()
    assert app.leader.state.config == values


def test_deploy_rejects_an_unknown_config_option(juju: Juju):
    with pytest.raises(JujuError, match=r"no config option 'bogus'\. Its options are: log_level"):
        deploy_mycharm(juju, config={'bogus': 1})
    assert not juju.apps


# storage

STORAGE_META: dict[str, Any] = {
    **META,
    'containers': {'workload': {}},
    'storage': {
        'data': {'type': 'filesystem'},
        'logs': {'type': 'filesystem', 'multiple': {'range': '2-4'}},
        'cache': {'type': 'filesystem', 'multiple': {'range': '0+'}},
    },
}


def storage_events(trace: Sequence[Dispatch], unit: str) -> list[tuple[str, int | None]]:
    return [
        (d.event.name, d.event._storage.index if d.event._storage else None)
        for d in trace
        if d.unit_name == unit
    ]


def test_storage_attached_runs_before_install_in_a_machine_model():
    with Juju(cloud_spec=CloudSpec(type='lxd', name='localhost')) as j:
        j.deploy(spec(MyCharm, {**STORAGE_META, 'containers': {}}))
        trace = j.settle()
    assert storage_events(trace, 'myapp/0') == [
        ('data_storage_attached', 0),
        ('logs_storage_attached', 1),
        ('logs_storage_attached', 2),
        ('install', None),
        ('leader_elected', None),
        ('config_changed', None),
        ('start', None),
    ]


def test_storage_attached_runs_after_start_in_a_kubernetes_model(juju: Juju):
    juju.deploy(spec(MyCharm, STORAGE_META))
    trace = juju.settle()
    assert storage_events(trace, 'myapp/0') == [
        ('install', None),
        ('leader_elected', None),
        ('config_changed', None),
        ('start', None),
        ('data_storage_attached', 0),
        ('logs_storage_attached', 1),
        ('logs_storage_attached', 2),
        ('workload_pebble_ready', None),
    ]


def test_each_unit_gets_its_own_storage_numbered_across_the_model(juju: Juju):
    app = juju.deploy(spec(MyCharm, STORAGE_META), num_units=2)
    other = juju.deploy(spec(MyCharm, STORAGE_META), app='other')
    added = juju.add_unit(app)

    def ids(unit: Any) -> list[str]:
        return sorted(f'{s.name}/{s.index}' for s in unit.state.storages)

    assert ids(app.units[0]) == ['data/0', 'logs/1', 'logs/2']
    assert ids(app.units[1]) == ['data/3', 'logs/4', 'logs/5']
    assert ids(other.leader) == ['data/6', 'logs/7', 'logs/8']
    assert ids(added) == ['data/9', 'logs/10', 'logs/11']


def test_deploy_storage_sets_how_many_instances_each_unit_gets(juju: Juju):
    app = juju.deploy(spec(MyCharm, STORAGE_META), storage={'logs': 4, 'cache': 1})
    juju.add_unit(app)
    for unit in app.units.values():
        names = sorted(s.name for s in unit.state.storages)
        assert names == ['cache', 'data', 'logs', 'logs', 'logs', 'logs']


@pytest.mark.parametrize('count_range', [3, '3', '3-3'])
def test_a_fixed_storage_range_gives_that_many_instances(juju: Juju, count_range: int | str):
    meta = {
        **META,
        'storage': {'data': {'type': 'filesystem', 'multiple': {'range': count_range}}},
    }
    app = juju.deploy(spec(MyCharm, meta))
    assert len(app.leader.state.storages) == 3


@pytest.mark.parametrize(
    ('storage', 'match'),
    [
        ({'nope': 1}, "has no store called 'nope'"),
        ({'data': 2}, 'storage is singular, 2 specified'),
        ({'logs': 1}, '2 instances required, 1 specified'),
        ({'logs': 5}, 'at most 4 instances supported, 5 specified'),
    ],
)
def test_deploy_rejects_storage_the_charm_does_not_allow(
    juju: Juju, storage: dict[str, int], match: str
):
    with pytest.raises(JujuError, match=match):
        juju.deploy(spec(MyCharm, STORAGE_META), storage=storage)
    assert not juju.apps


@pytest.mark.parametrize(
    ('count_range', 'match'),
    [('lots', "does not match 'm', 'm-n', or 'm\\+'"), (0, 'invalid count 0')],
)
def test_deploy_rejects_a_malformed_storage_range(juju: Juju, count_range: int | str, match: str):
    meta = {
        **META,
        'storage': {'data': {'type': 'filesystem', 'multiple': {'range': count_range}}},
    }
    with pytest.raises(JujuError, match=match):
        juju.deploy(spec(MyCharm, meta))


# state_template


def test_state_template_reaches_every_unit_including_those_added_later(juju: Juju):
    app = juju.deploy(
        CharmSpec(ExecCharm, meta=EXEC_META), state_template=EXEC_TEMPLATE, num_units=2
    )
    juju.settle()
    juju.add_unit(app)
    juju.settle()
    for unit in app.units.values():
        assert unit.state.unit_status == ActiveStatus('updated')


def test_state_template_containers_the_metadata_does_not_declare_are_reported(juju: Juju):
    template = State(containers={Container('undeclared')})
    juju.deploy(spec(MyCharm), state_template=template)
    with pytest.raises(InconsistentScenarioError, match='undeclared'):
        juju.settle()


def test_state_template_leaves_the_juju_owned_fields_to_juju(juju: Juju):
    app = juju.deploy(spec(MyCharm), state_template=State(workload_version='1.2.3'))
    unit = app.leader
    assert unit.state.workload_version == '1.2.3'
    assert unit.state.leader
    assert unit.state.model.name == 'test-model'
    assert unit.state.config == {'log_level': 'info'}


@pytest.mark.parametrize(
    ('field', 'template'),
    [
        ('leader', State(leader=True)),
        ('planned_units', State(planned_units=3)),
        ('model', State(model=Model(type='lxd'))),
        ('config', State(config={'log_level': 'debug'})),
        ('relations', State(relations={PeerRelation('replicas')})),
        ('secrets', State(secrets={Secret({'a': 'b'})})),
        ('storages', State(storages={Storage('data', index=0)})),
    ],
)
def test_state_template_may_not_set_juju_owned_fields(juju: Juju, field: str, template: State):
    with pytest.raises(JujuError, match=f'may not set {field}'):
        juju.deploy(spec(MyCharm), state_template=template)


def test_state_template_may_not_make_a_container_connectable(juju: Juju):
    template = State(containers={Container('workload', can_connect=True)})
    with pytest.raises(JujuError, match="may not set can_connect on container 'workload'"):
        juju.deploy(CharmSpec(WaitingCharm, meta=EXEC_META), state_template=template)
    assert not juju.apps


# add_unit


def test_add_unit_runs_the_startup_sequence_for_the_new_unit(juju: Juju):
    app = deploy_mycharm(juju)
    juju.settle()
    unit = juju.add_unit(app)
    assert unit.id == 1
    assert app.units[1] is unit
    assert {u.state.planned_units for u in app.units.values()} == {2}
    trace = juju.settle()
    assert [(d.unit_name, d.event.name) for d in trace] == [
        ('myapp/1', 'install'),
        ('myapp/1', 'leader_settings_changed'),
        ('myapp/1', 'config_changed'),
        ('myapp/1', 'start'),
    ]


def test_add_unit_rejects_an_app_from_another_juju(juju: Juju):
    with Juju() as other:
        app = deploy_mycharm(other)
        deploy_mycharm(juju)
        with pytest.raises(JujuError, match='not deployed in this Juju'):
            juju.add_unit(app)


# Peers


def test_a_peer_relation_adds_relation_created_and_each_unit_sees_the_others_join(juju: Juju):
    app = juju.deploy(spec(PeerCharm, PEER_META), num_units=2)
    trace = juju.settle()
    assert events(trace, 'myapp/1') == [
        'install',
        'replicas_relation_created',
        'leader_settings_changed',
        'config_changed',
        'start',
        'replicas_relation_joined',
        'replicas_relation_changed',
    ]
    assert app.units[0].state.unit_status == ActiveStatus("peers=['myapp/1']")
    assert app.units[1].state.unit_status == ActiveStatus("peers=['myapp/0']")


def test_a_unit_has_its_peer_relation_from_its_relation_created(juju: Juju):
    juju.deploy(spec(PeerCharm, PEER_META))
    install, created = juju.settle()[:2]
    assert install.state_out.relations == frozenset()
    assert created.event.name == 'replicas_relation_created'
    (relation,) = created.state_in.relations
    assert isinstance(relation, PeerRelation)
    assert relation.peers_data == {}


def test_peers_see_a_new_unit_join_only_after_its_relation_created(juju: Juju):
    app = juju.deploy(spec(PeerCharm, PEER_META))
    juju.settle()
    juju.add_unit(app)
    trace = juju.settle()
    assert events(trace, 'myapp/0') == ['replicas_relation_joined', 'replicas_relation_changed']
    names = [(d.unit_id, d.event.name) for d in trace]
    created = names.index((1, 'replicas_relation_created'))
    assert names.index((0, 'replicas_relation_joined')) > created


def test_peer_databag_writes_reach_the_other_units_and_cause_relation_changed(juju: Juju):
    app = juju.deploy(spec(PublishingCharm, PEER_META, config=None), num_units=2)
    juju.settle()
    assert peer_relation(app.units[0]).peers_data[1]['ready'] == 'yes'
    assert peer_relation(app.units[1]).peers_data[0]['ready'] == 'yes'
    for unit in app.units.values():
        assert peer_relation(unit).local_app_data['cluster'] == 'formed'
    # Each unit saw the other ready, which needs the write to have reached it
    # and caused a relation-changed after the write.
    assert app.units[0].state.unit_status == ActiveStatus("ready=['myapp/1']")
    assert app.units[1].state.unit_status == ActiveStatus("ready=['myapp/0']")


def test_only_relations_change_between_a_unit_s_dispatches(juju: Juju):
    # Other units' writes reach a unit's relations between its own dispatches.
    app = juju.deploy(spec(PublishingCharm, PEER_META, config=None), num_units=2)
    trace = juju.settle()
    for unit in app.units.values():
        dispatches = [d for d in trace if d.unit_id == unit.id]
        for before, after in itertools.pairwise(dispatches):
            expected = dataclasses.replace(before.state_out, relations=after.state_in.relations)
            assert after.state_in == expected


def test_settle_raises_when_the_model_does_not_converge(juju: Juju):
    juju.deploy(spec(ChattyCharm, PEER_META, config=None), num_units=2)
    with pytest.raises(JujuError, match='Did not converge after 200 events') as exc_info:
        juju.settle()
    assert 'replicas_relation_changed on myapp/' in str(exc_info.value)


def test_settle_reports_the_same_dispatch_twice_as_a_loop(juju: Juju):
    juju.deploy(spec(FlipFlopCharm, PEER_META, config=None), num_units=2)
    with pytest.raises(JujuError, match='with the same State it had the last time') as exc_info:
        juju.settle()
    # Long before the convergence limit.
    assert str(exc_info.value).count(' on myapp/') <= 10


# settle


def test_settle_returns_the_trace_and_reading_state_runs_nothing(juju: Juju):
    app = deploy_mycharm(juju)
    assert app.leader.state.unit_status == UnknownStatus()
    trace = juju.settle()
    first = trace[0]
    assert first.event.name == 'install'
    assert (first.app_name, first.unit_id, first.unit_name) == (app.name, 0, app.leader.name)
    assert first.state_in.unit_status == UnknownStatus()
    assert first.state_out.unit_status == ActiveStatus('install:info')
    assert trace[-1].state_out == app.leader.state
    assert juju.settle() == []


def test_a_dispatch_s_state_in_is_the_unit_s_previous_state_out(juju: Juju):
    deploy_mycharm(juju)
    trace = juju.settle()
    for before, after in itertools.pairwise(trace):
        assert after.state_in == before.state_out


def test_dispatches_compare_by_value_and_hold_no_live_handles(juju: Juju):
    app = deploy_mycharm(juju)
    install = juju.settle()[0]
    assert install == dataclasses.replace(install)
    juju.add_unit(app)
    juju.settle()
    assert install.state_out.planned_units != app.leader.state.planned_units
    assert juju.apps[install.app_name] is app


def test_units_take_turns(juju: Juju):
    deploy_mycharm(juju, num_units=2)
    juju.deploy(spec(MyCharm), app='other')
    trace = juju.settle()
    assert [d.unit_name for d in trace[:6]] == [
        'myapp/0',
        'myapp/1',
        'other/0',
        'myapp/0',
        'myapp/1',
        'other/0',
    ]
    assert [d.event.name for d in trace[:3]] == ['install'] * 3


def test_the_next_settle_starts_from_the_unit_after_the_last_turn(juju: Juju):
    app = deploy_mycharm(juju, num_units=2)
    other = juju.deploy(spec(MyCharm), app='other')
    assert juju.settle()[-1].unit_name == 'other/0'
    juju.add_unit(app)
    juju.add_unit(other)
    # other/1 comes after other/0, then the turn wraps round to myapp/2.
    assert [d.unit_name for d in juju.settle()[:2]] == ['other/1', 'myapp/2']


def test_settle_is_deterministic():
    def run() -> list[Dispatch]:
        with Juju() as j:
            j.deploy(spec(PublishingCharm, PEER_META, config=None), num_units=3)
            j.deploy(spec(SecretCharm, {'name': 'secrets'}, config=None), num_units=2)
            return list(j.settle())

    first = run()
    assert first
    for _ in range(3):
        assert run() == first


def test_a_secret_s_id_depends_only_on_its_unit_s_own_history():
    def secret_id(*apps: str) -> str:
        with Juju() as j:
            for name in apps:
                charm = SecretCharm if name == 'secrets' else MyCharm
                j.deploy(spec(charm, {'name': name}), num_units=2)
            j.settle()
            (secret,) = j.apps['secrets'].leader.state.secrets
            return secret.id

    alone = secret_id('secrets')
    assert alone.startswith('secret:')
    assert secret_id('first', 'secrets') == alone
    assert secret_id('secrets', 'after') == alone


def test_each_secret_a_unit_creates_gets_its_own_id(juju: Juju):
    app = juju.deploy(CharmSpec(TwoSecretsCharm, meta={'name': 'secrets'}))
    juju.settle()
    assert len({secret.id for secret in app.leader.state.secrets}) == 2


# Lifecycle


def test_close_rejects_later_operations_and_can_be_repeated(juju: Juju):
    app = deploy_mycharm(juju)
    juju.close()
    juju.close()
    assert not juju.apps
    with pytest.raises(JujuError, match='been closed'):
        deploy_mycharm(juju)
    with pytest.raises(JujuError, match='been closed'):
        juju.add_unit(app)
    with pytest.raises(JujuError, match='been closed'):
        juju.settle()
