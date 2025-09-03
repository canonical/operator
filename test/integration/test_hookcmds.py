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
    juju.wait(jubilant.all_active)
    assert not task.success
    assert task.message == 'Oh no, I failed!'
    assert task.log == ['Asked to backup 7 days of data to loc']
    assert task.results == {'backup-location': 'loc', 'days+1': 8}


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
    assert "New config: {'log-level': 'DEBUG', 'another-option': 42'}" in log
