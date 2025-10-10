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

from typing import Callable, cast

import jubilant
import pytest

from test.charms.test_secrets.src.charm import Result


def test_setup(build_secrets_charm: Callable[[], str], juju: jubilant.Juju):
    charm_path = build_secrets_charm()
    juju.deploy(charm_path, num_units=2)
    juju.wait(jubilant.all_active)


def test_add_secret(juju: jubilant.Juju, cleanup: None, leader: str):
    rv = juju.run(leader, 'add-secret')
    result = cast(Result, rv.results)
    assert not result.get('exception')

    secrets = juju.secrets()
    secret = juju.show_secret(secrets[0].uri, reveal=True) if secrets else None

    # These assertions keep type checker happy.
    # I'm not sure if the typed dicts are worth it.
    assert 'secretid' in result
    assert 'after' in result
    assert result['after']
    assert result['after']['info']

    if secret:
        assert secret.owner == 'test-secrets'
        short_juju_id = short_id(secret.uri)
        assert result['secretid']
        short_ops_id = short_id(result['secretid'])
        short_ops_info_id = short_id(result['after']['info']['id'])
        assert short_juju_id == short_ops_id == short_ops_info_id
        assert secret.content == result['after']['latest']

    assert secret
    assert secret.revision == 1
    assert secret.content == {'foo': 'bar'}


@pytest.fixture
def cleanup(juju: jubilant.Juju) -> None:
    secrets = juju.secrets()
    for secret in secrets:
        juju.remove_secret(secret.uri)


@pytest.fixture
def leader(juju: jubilant.Juju) -> str:
    status = juju.status()
    for name, unit in status.apps['test-secrets'].units.items():
        if unit.leader:
            return name
    raise Exception(f'no leader in {status}')


@pytest.fixture
def follower(juju: jubilant.Juju) -> str:
    status = juju.status()
    for name, unit in status.apps['test-secrets'].units.items():
        if not unit.leader:
            return name
    raise Exception(f'no follower in {status}')


def short_id(secret_uri: str):
    return secret_uri.split(':')[-1].split('/')[-1]
