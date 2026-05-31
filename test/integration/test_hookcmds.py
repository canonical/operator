# Copyright 2026 Canonical Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Integration tests for ops.hookcmds.

Each test deploys the test-hookcmds charm and runs an action that exercises a
specific slice of the hookcmds public API.  The action runs the hookcmds
function inside a real Juju hook context and returns results that the test can
inspect, verifying that:

  * Real Juju output is correctly parsed by the hookcmds JSON-decoding layer.
  * State changes made through hookcmds are visible to subsequent calls in the
    same dispatch (and, where appropriate, via jubilant).
  * The error path (hookcmds.Error) is raised when Juju returns a non-zero
    exit code.

Coverage that the unit tests already provide (correct CLI argument ordering,
mocked subprocess return values) is deliberately not duplicated here.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import jubilant
import pytest


def _juju_major(juju: jubilant.Juju) -> int:
    """Return the model's Juju agent major version (e.g. 3 or 4)."""
    return int(juju.status().model.version.split('.', 1)[0])


# Juju 4.0 has uniter commit-phase regressions: the hookcmds themselves
# succeed (the action results are all correct), but Juju fails to commit the
# queued changes at the end of the hook. Observed on both machine (LXD) and
# Kubernetes with Juju 4.0.5:
#   - state-delete  -> "runtime error: index out of range [0] with length 0"
#     (https://github.com/juju/juju/issues/22523)
#   - secret-remove -> "removing secrets: secret not found"
#     (https://github.com/juju/juju/issues/22524)
# These pass on Juju 3.6. Remove the guards in the affected tests once the
# fixes land.
_JUJU4_COMMIT_BUG = (
    'Juju 4.0 uniter commit-phase regression '
    '(juju/juju#22523, juju/juju#22524)'
)


# Deployment


def test_setup(build_hookcmds_charm: Callable[[], str], juju: jubilant.Juju):
    """Deploy the test-hookcmds charm with 2 units so that the peer relation
    is active for relation-data tests."""
    charm_path = build_hookcmds_charm()
    juju.deploy(charm_path, num_units=2)
    juju.wait(jubilant.all_active)


# Status (status_get / status_set)


def test_status_get_unit(juju: jubilant.Juju, any_unit: str):
    """status_get() (unit) returns the expected UnitStatus fields."""
    task = juju.run(any_unit, 'get-status')
    assert task.success
    results = task.results
    # The charm starts with ActiveStatus so unit-status should be 'active'.
    assert results['unit-status'] == 'active'
    # message may be empty string - just check the key is present.
    assert 'unit-message' in results


def test_status_get_app(juju: jubilant.Juju, leader: str):
    """status_get(app=True) from the leader returns AppStatus fields."""
    task = juju.run(leader, 'get-status')
    assert task.success
    results = task.results
    # Leader should also return app fields.
    assert 'app-status' in results
    assert 'app-message' in results
    assert 'app-unit-count' in results
    # Machine charms: status-get --application does not populate per-unit status (returns 0).
    # K8s charms: returns the unit count. Accept either.
    assert int(results['app-unit-count']) >= 0


def test_status_set_and_get(juju: jubilant.Juju, any_unit: str):
    """status_set then status_get reflects the new status and message."""
    task = juju.run(
        any_unit,
        'set-and-check-status',
        params={'status': 'maintenance', 'message': 'hookcmds test'},
    )
    assert task.success
    results = task.results
    assert results['status'] == 'maintenance'
    assert results['message'] == 'hookcmds test'


@pytest.mark.parametrize('status', ['blocked', 'waiting', 'maintenance', 'active'])
def test_status_set_all_settable_values(juju: jubilant.Juju, any_unit: str, status: str):
    """Every SettableStatusName value round-trips through status_set/get."""
    task = juju.run(any_unit, 'set-and-check-status', params={'status': status})
    assert task.success
    assert task.results['status'] == status


# Config (config_get)


def test_config_get_all(juju: jubilant.Juju, any_unit: str):
    """config_get() (no key) returns a dict with the configured options."""
    task = juju.run(any_unit, 'get-all-config')
    assert task.success
    config = json.loads(task.results['config'])
    assert 'string-opt' in config
    assert 'int-opt' in config
    assert config['string-opt'] == 'hello'
    assert config['int-opt'] == 42


def test_config_get_string_key(juju: jubilant.Juju, any_unit: str):
    """config_get(key) for a string option returns the string value."""
    task = juju.run(any_unit, 'get-config-value', params={'key': 'string-opt'})
    assert task.success
    assert task.results['value'] == 'hello'
    assert task.results['type'] == 'str'


def test_config_get_int_key(juju: jubilant.Juju, any_unit: str):
    """config_get(key) for an int option returns an int value."""
    task = juju.run(any_unit, 'get-config-value', params={'key': 'int-opt'})
    assert task.success
    assert task.results['value'] == '42'
    assert task.results['type'] == 'int'


# Leadership (is_leader)


def test_is_leader_true_for_leader(juju: jubilant.Juju, leader: str):
    """is_leader() returns True when run on the leader unit."""
    task = juju.run(leader, 'check-leadership')
    assert task.success
    assert task.results['is-leader'] == 'true'


def test_is_leader_false_for_nonleader(juju: jubilant.Juju, nonleader: str):
    """is_leader() returns False when run on a non-leader unit."""
    task = juju.run(nonleader, 'check-leadership')
    assert task.success
    assert task.results['is-leader'] == 'false'


# Logging (juju_log)


def test_juju_log_all_levels(juju: jubilant.Juju, any_unit: str):
    """juju_log at all five levels does not raise an error."""
    task = juju.run(any_unit, 'test-logging', params={'message': 'hookcmds integration test'})
    assert task.success
    assert task.results['ok'] == 'true'
    assert task.results['levels-logged'] == '5'


# Application version (app_version_set)


def test_app_version_set(juju: jubilant.Juju, leader: str):
    """app_version_set publishes the version string to Juju."""
    task = juju.run(leader, 'set-app-version', params={'version': '3.14.15'})
    assert task.success
    assert task.results['ok'] == 'true'
    # Verify Juju actually recorded the version.
    status = juju.status()
    assert status.apps['test-hookcmds'].version == '3.14.15'


# Network (network_get)


def test_network_get_returns_addresses(juju: jubilant.Juju, any_unit: str):
    """network_get for the peer binding returns at least one bind address."""
    task = juju.run(any_unit, 'get-network-info')
    assert task.success
    results = task.results
    assert results['has-bind-addresses'] == 'true'
    bind_count = int(results['bind-addresses-count'])
    assert bind_count > 0
    # At least one of egress_subnets or ingress_addresses should be populated.
    has_network_info = bool(results.get('egress-subnets')) or bool(
        results.get('ingress-addresses')
    )
    assert has_network_info
    # The bind address itself should be present.
    assert 'first-address' in results
    assert results['first-address']  # non-empty


# Ports (open_port / close_port / opened_ports)


def test_ports_open_close_cycle(juju: jubilant.Juju, any_unit: str):
    """open_port then close_port restores the original port count."""
    task = juju.run(any_unit, 'test-ports', params={'port': 9988})
    assert task.success
    r = task.results
    assert r['tcp-was-opened'] == 'true'
    assert r['udp-was-opened'] == 'true'
    assert r['tcp-was-closed'] == 'true'
    assert r['udp-still-open-after-tcp-close'] == 'true'
    assert r['back-to-initial'] == 'true'
    # Counts should be monotonically increasing then decreasing.
    initial = int(r['initial-count'])
    after_tcp = int(r['after-open-tcp-count'])
    after_both = int(r['after-open-both-count'])
    after_close_tcp = int(r['after-close-tcp-count'])
    final = int(r['final-count'])
    assert after_tcp == initial + 1
    assert after_both == initial + 2
    assert after_close_tcp == initial + 1
    assert final == initial


@pytest.mark.parametrize('port', [80, 443, 8080])
def test_ports_multiple_values(juju: jubilant.Juju, any_unit: str, port: int):
    """Port open/close cycle works across several common port values."""
    task = juju.run(any_unit, 'test-ports', params={'port': port})
    assert task.success
    assert task.results['tcp-was-opened'] == 'true'
    assert task.results['back-to-initial'] == 'true'


# Server-side state (state_set / state_get / state_delete)


def test_state_roundtrip(juju: jubilant.Juju, any_unit: str):
    """Full state lifecycle: set, get by key, get all, delete, verify gone."""
    try:
        task = juju.run(
            any_unit,
            'test-unit-state',
            params={'key': 'testkey', 'value': 'testvalue'},
        )
    except jubilant.TaskError:
        if _juju_major(juju) >= 4:
            pytest.xfail(_JUJU4_COMMIT_BUG)
        raise
    assert task.success
    r = task.results
    assert r['retrieved'] == 'testvalue'
    assert r['types-match'] == 'true'
    assert r['key-in-all'] == 'true'
    assert r['all-value-matches'] == 'true'
    assert r['key-deleted'] == 'true'


def test_state_special_chars(juju: jubilant.Juju, any_unit: str):
    """State values containing spaces and punctuation are preserved."""
    try:
        task = juju.run(
            any_unit,
            'test-unit-state',
            params={'key': 'mykey', 'value': 'hello world!'},
        )
    except jubilant.TaskError:
        if _juju_major(juju) >= 4:
            pytest.xfail(_JUJU4_COMMIT_BUG)
        raise
    assert task.success
    assert task.results['retrieved'] == 'hello world!'
    assert task.results['types-match'] == 'true'
    assert task.results['key-deleted'] == 'true'


# Secrets (secret_add / secret_ids / secret_info_get / secret_get /
#          secret_set / secret_remove)


def test_secret_full_lifecycle(juju: jubilant.Juju, leader: str):
    """Full secret CRUD lifecycle exercises all secret hookcmds."""
    try:
        task = juju.run(leader, 'test-secret-crud')
    except jubilant.TaskError:
        if _juju_major(juju) >= 4:
            pytest.xfail(_JUJU4_COMMIT_BUG)
        raise
    assert task.success
    r = task.results

    assert r['in-ids-list'] == 'true'
    assert r['initial-label'] == 'hookcmds-inttest'
    assert r['initial-description'] == 'Created by ops.hookcmds integration test'
    assert r['initial-revision'] == '1'
    assert r['initial-password'] == 'initial-secret'
    assert r['updated-password'] == 'updated-secret'
    assert r['updated-description'] == 'Updated by hookcmds test'
    # secret_get(label=...) should return the password too.
    assert r['label-lookup-password']  # non-empty

    # After the action the secret is fully removed; verify via juju.
    secrets = juju.secrets()
    owned = [s for s in secrets if s.owner == 'test-hookcmds']
    assert len(owned) == 0, f'Expected no secrets owned by test-hookcmds, found: {owned}'


# Goal state (goal_state)


def test_goal_state_reports_units(juju: jubilant.Juju, any_unit: str):
    """goal_state() returns GoalState with the expected unit names."""
    task = juju.run(any_unit, 'test-goal-state')
    assert task.success
    r = task.results
    unit_count = int(r['unit-count'])
    assert unit_count >= 1
    unit_names = r['unit-names'].split(',')
    assert any(u.startswith('test-hookcmds/') for u in unit_names)
    # Every unit should be in an 'alive' or 'waiting' goal state.
    statuses = r['unit-statuses'].split(',')
    for status in statuses:
        assert status in ('alive', 'waiting', 'dying', 'active'), (
            f'Unexpected goal status: {status}'
        )


# Relations (relation_ids / relation_list / relation_set / relation_get)


def test_relation_data_roundtrip(juju: jubilant.Juju, leader: str):
    """Full relation data cycle: relation_ids, set data, get by key, get all."""
    task = juju.run(leader, 'test-relation-data')
    assert task.success
    r = task.results

    # The relation ID string should have the format "peer:N".
    assert r['relation-id-str'].startswith('peer:')
    assert r['relation-id-int'].isdigit()

    # With 2 units, the leader should see 1 member in the peer relation.
    assert int(r['member-count']) == 1

    # Data we wrote should be readable back.
    assert r['set-value'] == 'verified-by-integration-test'
    assert r['retrieved-value'] == 'verified-by-integration-test'
    assert r['values-match'] == 'true'
    assert r['key-in-all-data'] == 'true'


# Storage (storage_list / storage_get)


def test_storage_list_and_get(juju: jubilant.Juju, any_unit: str):
    """storage_list returns the attached data storage; storage_get has a path."""
    task = juju.run(any_unit, 'test-storage')
    assert task.success
    r = task.results
    data_count = int(r['data-storage-count'])
    assert data_count >= 1, 'Expected at least one data storage instance'
    # The storage ID should follow the name/N pattern.
    storage_id = r['storage-id']
    assert storage_id.startswith('data/')
    assert r['has-location'] == 'true'
    assert r['storage-location']  # non-empty path
    assert r['storage-kind'] in ('filesystem', 'block')


# Action commands (action_get / action_log / action_set)


def test_action_get_and_set_via_hookcmds(juju: jubilant.Juju, any_unit: str):
    """hookcmds.action_get reads params and action_set writes results."""
    task = juju.run(
        any_unit,
        'test-action-params',
        params={'message': 'hello-from-hookcmds'},
    )
    assert task.success
    r = task.results
    assert r['received'] == 'hello-from-hookcmds'
    # The action has exactly one declared param, 'message'.
    assert int(r['param-count']) == 1


def test_action_fail_via_hookcmds(juju: jubilant.Juju, any_unit: str):
    """hookcmds.action_fail marks the action as failed."""
    # jubilant.run() raises TaskError on action failure; catch it to verify failure
    with pytest.raises(jubilant.TaskError) as exc_info:
        juju.run(
            any_unit,
            'fail-action',
            params={'message': 'intentional hookcmds failure'},
        )
    assert not exc_info.value.task.success


# Error path (hookcmds.Error)


def test_error_on_invalid_relation_id(juju: jubilant.Juju, any_unit: str):
    """relation_list on a nonexistent relation id raises hookcmds.Error."""
    task = juju.run(any_unit, 'trigger-relation-error', params={'relation-id': 9999})
    assert task.success
    assert task.results['raised'] == 'Error'


# Fixtures


@pytest.fixture
def leader(juju: jubilant.Juju) -> str:
    """Return the name of the leader unit."""
    status = juju.status()
    for name, unit in status.apps['test-hookcmds'].units.items():
        if unit.leader:
            return name
    raise RuntimeError(f'No leader found in {status}')


@pytest.fixture
def nonleader(juju: jubilant.Juju) -> str:
    """Return the name of a non-leader unit."""
    status = juju.status()
    for name, unit in status.apps['test-hookcmds'].units.items():
        if not unit.leader:
            return name
    raise RuntimeError(f'No non-leader found in {status}')


@pytest.fixture
def any_unit(leader: str) -> str:
    """Return any unit (the leader, for simplicity)."""
    return leader
