# Copyright 2025 Canonical Ltd.
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

from __future__ import annotations

from typing import Callable

import jubilant
import pytest


@pytest.fixture
def pack_and_deploy(build_relation_charm: Callable[[], str], juju: jubilant.Juju):
    """Fixture for testing hook commands."""
    charm_path = build_relation_charm()
    juju.deploy(charm_path)
    juju.wait(jubilant.all_active)
    yield


def test_hookcmds_action(pack_and_deploy: None, juju: jubilant.Juju):
    task = juju.run('test-hookcmds/0', 'backup', params={'backup-location': 'loc', 'days': 7})
    assert not task.success
    assert task.message == 'Oh no, I failed!'
    assert task.log == ['Asked to backup 7 days of data to loc']
    assert task.results == {'backup-location': 'loc', 'days-plus-one': 8}


def test_hookcmds_application_version(pack_and_deploy: None, juju: jubilant.Juju):
    status = juju.status()
    assert status.apps['test-hookcmds'].version == '1.25.79'


def test_hookcmds_ports(pack_and_deploy: None, juju: jubilant.Juju):
    status = juju.status()
    assert status.get_units('test-hookcmds')['test-hookcmds/0'].open_ports == []
    juju.run('test-hookcmds/0', 'open-port', params={'protocol': 'tcp', 'port': 80})
    status = juju.status()
    assert status.get_units('test-hookcmds')['test-hookcmds/0'].open_ports == ['80/tcp']
    task = juju.run('test-hookcmds/0', 'opened-ports')
    assert task.results == {'opened_ports': ['80/tcp']}
    juju.run('test-hookcmds/0', 'close-port', params={'protocol': 'tcp', 'port': 80})
    status = juju.status()
    assert status.get_units('test-hookcmds')['test-hookcmds/0'].open_ports == []


def test_hookcmds_config(pack_and_deploy: None, juju: jubilant.Juju):
    juju.config('test-hookcmds', {'log-level': 'DEBUG', 'another-option': 42})
    log = juju.debug_log(limit=10)
    assert "New config: [('another-option', 42), ('crash', False), ('log-level', 'DEBUG')]" in log


def test_hookcmds_status_commands(pack_and_deploy: None, juju: jubilant.Juju):
    # Put the unit into error state.
    juju.config('test-hookcmds', {'crash': True})
    juju.wait(jubilant.all_error)
    task = juju.run('test-hookcmds/0', 'test-status')
    assert task.success
    results = task.results
    assert results.get('original_status') == 'error'
    assert results.get('new_status') == 'active'


def test_hookcmds_state_commands(pack_and_deploy: None, juju: jubilant.Juju):
    # First set a value.
    juju.run('test-hookcmds/0', 'test-state', params={'value': 'bar'})
    task = juju.run('test-hookcmds/0', 'test-state', params={'value': ''})
    assert task.success
    results = task.results
    assert results.get('value') == 'bar'
    juju.run('test-hookcmds/0', 'test-state', params={'value': 'bar-again'})
    juju.run('test-hookcmds/0', 'test-state', params={'value': 'delete'})
    task = juju.exec('state-get value', unit='test-hookcmds/0')
    assert task.success
    assert task.stdout.strip() == '""'


def test_hookcmds_secret_commands(pack_and_deploy: None, juju: jubilant.Juju):
    # TODO: Consider testing secret-set, secret-grant, secret-revoke, secret-grant.
    task = juju.run('test-hookcmds/0', 'test-secrets')
    assert task.success
    results = task.results
    assert results['secrets'] == [({'label': 'test-secret'}, {'foo': 'bar'})]


def test_hookcmds_storage_commands(pack_and_deploy: None, juju: jubilant.Juju):
    task = juju.run('test-hookcmds/0', 'get-storage')
    assert task.success
    results = task.results
    assert len(results['storages']) == 1
    storage = results['storages'][0]
    assert storage['kind'] == 'filesystem'
    assert storage['location'].startswith('/var/lib/juju/storage/cache/')
    juju.run('test/hookcmds/0', 'add-storage', params={'count': 2})
    task = juju.run('test-hookcmds/0', 'get-storage')
    assert task.success
    results = task.results
    assert len(results['storages']) == 3


def test_hookcmds_relation_commands(pack_and_deploy: None, juju: jubilant.Juju):
    juju.run('test-hookcmds/0', 'set-peer-data', params={'data': 'value1'})
    task = juju.run('test-hookcmds/0', 'get-peer-data')
    assert task.success
    # The above will have triggered a relation-changed event, so wait for that to settle.
    juju.wait(jubilant.all_agents_idle)
    for line in juju.debug_log(limit=100):
        if not line.startswith('Peer data:'):
            continue
        assert "data': 'value1'" in line
        assert "list: ['test-hookcmds/0']" in line
        assert 'model: ' in line
