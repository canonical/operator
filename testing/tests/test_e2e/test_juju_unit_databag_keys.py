# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""The keys that Juju writes to each unit's relation databag.

Juju writes ``ingress-address``, ``egress-subnets``, and (on Juju 3)
``private-address`` to each unit databag when the unit enters the relation's
scope. Scenario doesn't put these in the state, but shows them to the charm
when it reads a unit databag.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import pytest
from scenario import Context
from scenario.state import (
    Network,
    PeerRelation,
    Relation,
    RelationBase,
    State,
    SubordinateRelation,
)

import ops

JUJU_3 = '3.6.14'
JUJU_4 = '4.0.12'

META: dict[str, Any] = {
    'name': 'local',
    'requires': {
        'db': {'interface': 'db'},
        'info': {'interface': 'info', 'scope': 'container'},
    },
    'peers': {'cluster': {'interface': 'cluster'}},
}


class Charm(ops.CharmBase):
    """A charm that runs a callback from the test on ``update-status``."""

    callback: Callable[[ops.CharmBase], None] | None = None

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on.update_status, self._on_update_status)

    def _on_update_status(self, _: ops.UpdateStatusEvent):
        assert Charm.callback is not None
        Charm.callback(self)


@pytest.fixture(autouse=True)
def reset_callback():
    Charm.callback = None


def run(
    state: State,
    callback: Callable[[ops.CharmBase], None],
    juju_version: str = JUJU_3,
) -> State:
    Charm.callback = callback
    ctx = Context(Charm, meta=META, juju_version=juju_version)
    return ctx.run(ctx.on.update_status(), state)


def seen_databags(state: State, juju_version: str = JUJU_3) -> dict[str, dict[str, str]]:
    """Run the charm and return the unit databags it sees, keyed by unit name."""
    seen: dict[str, dict[str, str]] = {}

    def read(charm: ops.CharmBase):
        for endpoint in ('db', 'cluster', 'info'):
            for relation in charm.model.relations[endpoint]:
                seen[f'{endpoint}:{charm.unit.name}'] = dict(relation.data[charm.unit])
                for unit in relation.units:
                    seen[f'{endpoint}:{unit.name}'] = dict(relation.data[unit])

    run(state, read, juju_version)
    return seen


def addresses(address: str, egress: str, juju_version: str) -> dict[str, str]:
    keys = {'egress-subnets': egress, 'ingress-address': address}
    if juju_version.startswith('3.'):
        keys['private-address'] = address
    return keys


@pytest.mark.parametrize('juju_version', [JUJU_3, JUJU_4])
def test_charm_sees_juju_keys_in_every_unit_databag(juju_version: str):
    relation = Relation('db', remote_units_data={0: {}, 1: {}})
    peer = PeerRelation('cluster', peers_data={1: {}, 2: {}})
    sub = SubordinateRelation('info')
    state = State(relations={relation, peer, sub})

    seen = seen_databags(state, juju_version)

    local = addresses('192.0.2.0', '192.0.2.0/24', juju_version)
    assert seen == {
        'db:local/0': local,
        'db:remote/0': addresses('203.0.113.0', '203.0.113.0/32', juju_version),
        'db:remote/1': addresses('203.0.113.1', '203.0.113.1/32', juju_version),
        'cluster:local/0': local,
        'cluster:local/1': addresses('198.51.100.1', '198.51.100.1/32', juju_version),
        'cluster:local/2': addresses('198.51.100.2', '198.51.100.2/32', juju_version),
        'info:local/0': local,
        # The principal unit is on the same machine as the subordinate.
        'info:remote/0': local,
    }


@pytest.mark.parametrize('juju_version', [JUJU_3, JUJU_4])
def test_output_state_has_no_juju_keys(juju_version: str):
    relation = Relation('db')
    peer = PeerRelation('cluster', peers_data={1: {}})
    sub = SubordinateRelation('info')

    def read_everything(charm: ops.CharmBase):
        for endpoint in ('db', 'cluster', 'info'):
            for rel in charm.model.relations[endpoint]:
                for entity in (charm.unit, charm.app, *rel.units):
                    dict(rel.data[entity])

    out = run(State(leader=True, relations={relation, peer, sub}), read_everything, juju_version)

    rel_out = out.get_relation(relation.id)
    assert isinstance(rel_out, Relation)
    assert rel_out.local_unit_data == {}
    assert rel_out.remote_units_data == {0: {}}
    peer_out = out.get_relation(peer.id)
    assert isinstance(peer_out, PeerRelation)
    assert peer_out.local_unit_data == {}
    assert peer_out.peers_data == {1: {}}
    sub_out = out.get_relation(sub.id)
    assert isinstance(sub_out, SubordinateRelation)
    assert sub_out.local_unit_data == {}
    assert sub_out.remote_unit_data == {}
    # The input state is untouched too.
    assert relation.local_unit_data == {}
    assert relation.remote_units_data == {0: {}}


def test_app_databags_have_no_juju_keys():
    relation = Relation('db', remote_app_data={'a': 'b'})
    seen: dict[str, dict[str, str]] = {}

    def read(charm: ops.CharmBase):
        rel = charm.model.get_relation('db')
        assert rel is not None
        assert rel.app is not None
        seen['local'] = dict(rel.data[charm.app])
        seen['remote'] = dict(rel.data[rel.app])

    run(State(leader=True, relations={relation}), read)
    assert seen == {'local': {}, 'remote': {'a': 'b'}}


@pytest.mark.parametrize('juju_version', [JUJU_3, JUJU_4])
def test_local_unit_keys_come_from_network(juju_version: str):
    relation = Relation('db')
    network = Network(
        'db',
        ingress_addresses=['10.0.0.10', '10.0.0.11'],
        egress_subnets=['10.0.0.0/24', '10.1.0.0/24'],
    )
    seen: dict[str, Any] = {}

    def read(charm: ops.CharmBase):
        rel = charm.model.get_relation('db')
        assert rel is not None
        seen['databag'] = dict(rel.data[charm.unit])
        binding = charm.model.get_binding(rel)
        assert binding is not None
        seen['network-get'] = str(binding.network.ingress_address)

    run(State(relations={relation}, networks={network}), read, juju_version)

    assert seen['databag'] == addresses('10.0.0.10', '10.0.0.0/24,10.1.0.0/24', juju_version)
    # The databag and network-get agree.
    assert seen['network-get'] == '10.0.0.10'


def test_network_for_another_endpoint_is_not_used():
    relation = Relation('db')
    network = Network('cluster', ingress_addresses=['10.0.0.10'], egress_subnets=['10.0.0.0/24'])
    seen = seen_databags(State(relations={relation}, networks={network}))
    assert seen['db:local/0'] == addresses('192.0.2.0', '192.0.2.0/24', JUJU_3)


@pytest.mark.parametrize(
    'juju_version,ingress,egress,expected',
    [
        (JUJU_3, [], ['10.0.0.0/24'], {'egress-subnets': '10.0.0.0/24'}),
        (JUJU_4, [], ['10.0.0.0/24'], {'egress-subnets': '10.0.0.0/24'}),
        (
            JUJU_3,
            ['10.0.0.10'],
            [],
            {'ingress-address': '10.0.0.10', 'private-address': '10.0.0.10'},
        ),
        (JUJU_4, ['10.0.0.10'], [], {'ingress-address': '10.0.0.10'}),
        (JUJU_3, [], [], {}),
        (JUJU_4, [], [], {}),
    ],
)
def test_network_without_addresses_gives_no_keys(
    juju_version: str, ingress: list[str], egress: list[str], expected: dict[str, str]
):
    relation = Relation('db')
    network = Network('db', [], ingress_addresses=ingress, egress_subnets=egress)
    seen = seen_databags(State(relations={relation}, networks={network}), juju_version)
    assert seen['db:local/0'] == expected


def test_subordinate_remote_unit_has_local_addresses():
    # State.networks can't have a Network for a container-scoped endpoint, so
    # both units get the default Network's values.
    sub = SubordinateRelation('info', remote_app_name='principal', remote_unit_id=3)
    seen = seen_databags(State(relations={sub}))
    expected = addresses('192.0.2.0', '192.0.2.0/24', JUJU_3)
    assert seen == {'info:local/0': expected, 'info:principal/3': expected}


def test_remote_and_peer_units_get_distinct_addresses():
    relation = Relation('db', remote_units_data={i: {} for i in range(5)})
    peer = PeerRelation('cluster', peers_data={i: {} for i in range(1, 5)})
    seen = seen_databags(State(relations={relation, peer}))
    ingress = [bag['ingress-address'] for bag in seen.values()]
    # Five remote units, four peers, and the local unit (twice: once per relation).
    assert len(ingress) == 11
    assert len(set(ingress)) == 10


def test_unit_id_wraps_at_256():
    relation = Relation('db', remote_units_data={1: {}, 257: {}})
    seen = seen_databags(State(relations={relation}))
    assert seen['db:remote/1'] == seen['db:remote/257']
    assert seen['db:remote/257']['ingress-address'] == '203.0.113.1'


@pytest.mark.parametrize('juju_version', [JUJU_3, JUJU_4])
def test_values_in_state_win(juju_version: str):
    relation = Relation(
        'db',
        local_unit_data={'private-address': '10.0.0.5', 'extra': 'kept'},
        remote_units_data={0: {'ingress-address': '10.9.9.9'}},
    )
    peer = PeerRelation('cluster', peers_data={1: {'egress-subnets': '10.8.0.0/16'}})

    seen = seen_databags(State(relations={relation, peer}), juju_version)

    local = addresses('192.0.2.0', '192.0.2.0/24', juju_version)
    assert seen['db:local/0'] == {**local, 'private-address': '10.0.0.5', 'extra': 'kept'}
    remote = addresses('203.0.113.0', '203.0.113.0/32', juju_version)
    assert seen['db:remote/0'] == {**remote, 'ingress-address': '10.9.9.9'}
    peer_1 = addresses('198.51.100.1', '198.51.100.1/32', juju_version)
    assert seen['cluster:local/1'] == {**peer_1, 'egress-subnets': '10.8.0.0/16'}


def test_untouched_relation_is_reusable():
    relation = Relation('db')
    ctx = Context(Charm, meta=META)
    Charm.callback = lambda charm: None
    out = ctx.run(ctx.on.update_status(), State(relations={relation}))
    assert out.get_relation(relation.id) == relation
    # So the input relation can be used for the next event.
    ctx.run(ctx.on.relation_changed(relation, remote_unit=0), out)


def test_writing_back_the_same_value_is_not_in_output():
    relation = Relation('db')

    def write(charm: ops.CharmBase):
        rel = charm.model.get_relation('db')
        assert rel is not None
        address = rel.data[charm.unit]['ingress-address']
        # ops doesn't call relation-set when the value doesn't change.
        rel.data[charm.unit]['ingress-address'] = address
        rel.data[charm.unit]['mine'] = address

    out = run(State(relations={relation}), write)
    assert out.get_relation(relation.id).local_unit_data == {'mine': '192.0.2.0'}


@pytest.mark.parametrize('key', ['ingress-address', 'egress-subnets', 'private-address'])
def test_juju_3_keeps_charm_writes(key: str, caplog: pytest.LogCaptureFixture):
    relation = Relation('db')

    def write(charm: ops.CharmBase):
        rel = charm.model.get_relation('db')
        assert rel is not None
        rel.data[charm.unit][key] = 'charm-value'

    with caplog.at_level(logging.WARNING, logger='ops-scenario'):
        out = run(State(relations={relation}), write, JUJU_3)
    assert out.get_relation(relation.id).local_unit_data == {key: 'charm-value'}
    assert 'ignores changes' not in caplog.text


@pytest.mark.parametrize('key', ['ingress-address', 'egress-subnets'])
def test_juju_4_drops_charm_writes(key: str, caplog: pytest.LogCaptureFixture):
    relation = Relation('db')
    seen: list[str] = []

    def write(charm: ops.CharmBase):
        rel = charm.model.get_relation('db')
        assert rel is not None
        rel.data[charm.unit][key] = 'charm-value'
        rel.data[charm.unit]['other'] = 'kept'
        # The charm still sees its own value for the rest of the hook.
        seen.append(rel.data[charm.unit][key])

    with caplog.at_level(logging.WARNING, logger='ops-scenario'):
        out = run(State(relations={relation}), write, JUJU_4)
    assert seen == ['charm-value']
    assert out.get_relation(relation.id).local_unit_data == {'other': 'kept'}
    assert f"ignores changes to '{key}'" in caplog.text


def test_juju_4_drops_charm_deletes(caplog: pytest.LogCaptureFixture):
    relation = Relation('db', local_unit_data={'ingress-address': '192.0.2.0'})
    seen: list[bool] = []

    def delete(charm: ops.CharmBase):
        rel = charm.model.get_relation('db')
        assert rel is not None
        del rel.data[charm.unit]['ingress-address']
        seen.append('ingress-address' in rel.data[charm.unit])

    with caplog.at_level(logging.WARNING, logger='ops-scenario'):
        out = run(State(relations={relation}), delete, JUJU_4)
    assert seen == [False]
    assert out.get_relation(relation.id).local_unit_data == {'ingress-address': '192.0.2.0'}
    assert "ignores changes to 'ingress-address'" in caplog.text


def test_juju_4_keeps_private_address_writes(caplog: pytest.LogCaptureFixture):
    relation = Relation('db')

    def write(charm: ops.CharmBase):
        rel = charm.model.get_relation('db')
        assert rel is not None
        rel.data[charm.unit]['private-address'] = '10.0.0.5'

    with caplog.at_level(logging.WARNING, logger='ops-scenario'):
        out = run(State(relations={relation}), write, JUJU_4)
    assert out.get_relation(relation.id).local_unit_data == {'private-address': '10.0.0.5'}
    assert 'ignores changes' not in caplog.text


def test_juju_4_keeps_app_databag_writes():
    relation = Relation('db')

    def write(charm: ops.CharmBase):
        rel = charm.model.get_relation('db')
        assert rel is not None
        rel.data[charm.app]['ingress-address'] = '10.0.0.5'

    out = run(State(leader=True, relations={relation}), write, JUJU_4)
    assert out.get_relation(relation.id).local_app_data == {'ingress-address': '10.0.0.5'}


def _run_with_relation(relation: RelationBase, juju_version: str, network: Network | None = None):
    state = State(relations={relation}, networks={network} if network else ())
    return run(state, lambda charm: None, juju_version)


@pytest.mark.parametrize(
    'local_unit_data',
    [
        {'ingress-address': '10.0.0.5'},
        {'egress-subnets': '10.0.0.0/24'},
    ],
)
def test_checker_warns_on_juju_4_local_mismatch(
    local_unit_data: dict[str, str], caplog: pytest.LogCaptureFixture
):
    relation = Relation('db', local_unit_data=local_unit_data)
    with caplog.at_level(logging.WARNING, logger='ops-scenario'):
        _run_with_relation(relation, JUJU_4)
    assert 'only Juju sets that key' in caplog.text


def test_checker_warns_on_juju_4_key_without_network_address(caplog: pytest.LogCaptureFixture):
    relation = Relation('db', local_unit_data={'ingress-address': '192.0.2.0'})
    network = Network('db', ingress_addresses=[], egress_subnets=[])
    with caplog.at_level(logging.WARNING, logger='ops-scenario'):
        _run_with_relation(relation, JUJU_4, network)
    assert "wouldn't be set" in caplog.text


@pytest.mark.parametrize(
    'juju_version,relation',
    [
        # Matches the default Network.
        (JUJU_4, Relation('db', local_unit_data={'ingress-address': '192.0.2.0'})),
        (JUJU_4, Relation('db', local_unit_data={'egress-subnets': '192.0.2.0/24'})),
        # An ordinary key on Juju 4.
        (JUJU_4, Relation('db', local_unit_data={'private-address': '10.0.0.5'})),
        # Remote and peer databags are how a test sets another unit's address.
        (JUJU_4, Relation('db', remote_units_data={0: {'ingress-address': '10.0.0.5'}})),
        (JUJU_4, PeerRelation('cluster', peers_data={1: {'ingress-address': '10.0.0.5'}})),
        # On Juju 3, the charm may have written them in an earlier hook.
        (JUJU_3, Relation('db', local_unit_data={'ingress-address': '10.0.0.5'})),
        (JUJU_3, Relation('db', local_unit_data={'egress-subnets': '10.0.0.0/24'})),
    ],
)
def test_checker_allows_juju_keys(
    juju_version: str, relation: RelationBase, caplog: pytest.LogCaptureFixture
):
    with caplog.at_level(logging.WARNING, logger='ops-scenario'):
        _run_with_relation(relation, juju_version)
    assert 'only Juju sets that key' not in caplog.text


def test_checker_uses_network_on_juju_4(caplog: pytest.LogCaptureFixture):
    relation = Relation(
        'db',
        local_unit_data={'ingress-address': '10.0.0.5', 'egress-subnets': '10.0.0.0/24'},
    )
    network = Network('db', ingress_addresses=['10.0.0.5'], egress_subnets=['10.0.0.0/24'])
    with caplog.at_level(logging.WARNING, logger='ops-scenario'):
        _run_with_relation(relation, JUJU_4, network)
    assert 'only Juju sets that key' not in caplog.text
