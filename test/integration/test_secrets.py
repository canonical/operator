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

import json
from typing import Callable

import jubilant
import pytest


@pytest.mark.parametrize('action', ['add-secret'])
def test_foo(build_secrets_charm: Callable[[], str], juju: jubilant.Juju, action: str):
    charm_path = build_secrets_charm()
    juju.deploy(charm_path)
    status = juju.wait(jubilant.all_active)

    unit, unit_obj = next(iter(status.apps['test-secrets'].units.items()))
    assert unit_obj.leader

    rv = juju.run(unit, action)
    result = json.loads(rv.results['rv'])
    assert not result.get('_exception')

    secrets = juju.secrets()
    secret = juju.show_secret(secrets[0].uri, reveal=True) if secrets else None

    if secret:
        assert secret.owner == 'test-secrets'
        assert secret.uri == result['secretid'] == result['after']['info']['id']
        assert secret.content == result['after']['latest']

    assert secret
    assert secret.revision == 1
    assert secret.content == {'foo': 'bar'}
