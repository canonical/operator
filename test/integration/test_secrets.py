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

from test.charms.test_secrets.src.charm import Result


@pytest.mark.parametrize('action', ['add-secret'])
def test_secrets(build_secrets_charm: Callable[[], str], juju: jubilant.Juju, action: str):
    charm_path = build_secrets_charm()
    juju.deploy(charm_path)
    status = juju.wait(jubilant.all_active)

    unit, unit_obj = next(iter(status.apps['test-secrets'].units.items()))
    assert unit_obj.leader

    rv = juju.run(unit, action)
    result: Result = rv.results  # type: ignore
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
        short_juju_id = simp(secret.uri)
        assert result['secretid']
        short_ops_id = simp(result['secretid'])
        short_ops_info_id = simp(result['after']['info']['id'])
        assert short_juju_id == short_ops_id == short_ops_info_id
        assert secret.content == result['after']['latest']

    assert secret
    assert secret.revision == 1
    assert secret.content == {'foo': 'bar'}


def simp(secret_uri: str):
    return secret_uri.split(':')[-1].split('/')[-1]
