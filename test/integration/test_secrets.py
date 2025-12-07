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

import collections
from collections.abc import Callable
from typing import Literal, cast

import jubilant
import pytest

from test.charms.test_secrets.src.charm import Result


def test_setup(build_secrets_charm: Callable[[], str], juju: jubilant.Juju):
    charm_path = build_secrets_charm()
    juju.deploy(charm_path, num_units=2)
    juju.wait(jubilant.all_active)


def test_add_secret(juju: jubilant.Juju, cleanup: None, leader: str):
    rv = juju.run(leader, 'add-secret')
    result = cast('Result', rv.results)

    secrets = juju.secrets()
    secret = juju.show_secret(secrets[0].uri, reveal=True)
    common_checks(secret, result)

    assert secret.revision == 1
    assert secret.content == {'foo': 'bar'}


@pytest.mark.parametrize(
    'fields',
    [
        '',
        'label',
        'description',
        'expire',
        'rotate',
        'label,description',
        'description,expire,rotate',
        'label,description,expire,rotate',
    ],
)
def test_add_with_meta(juju: jubilant.Juju, cleanup: None, leader: str, fields: str):
    rv = juju.run(leader, 'add-with-meta', params={'fields': fields})
    result = cast('Result', rv.results)

    assert 'secretid' in result
    assert 'after' in result
    assert result['after']
    assert result['after']['info']
    info = result['after']['info']

    secrets = juju.secrets()
    secret = juju.show_secret(secrets[0].uri, reveal=True)
    common_checks(secret, result)

    assert secret.revision == 1
    assert secret.content == {'foo': 'bar'}

    if 'label' in fields:
        assert secret.label == 'label1'
        assert info['label'] == 'label1'
    if 'description' in fields:
        assert secret.description == 'description1'
        assert info['description'] == 'description1'
    if 'expire' in fields:
        assert secret.expires == '2020-01-01T00:00:00Z'
        assert info['expires'] == '2020-01-01 00:00:00+00:00'
    if 'rotate' in fields:
        assert secret.rotation == 'daily'
        assert info['rotation'] == 'SecretRotate.DAILY'
        assert secret.rotates  # approx 24h from now
        # Freshly minted secret will only gain `rotates` time stamp in
        # the next dispatch call. See #2104.
        assert info['rotates'] == 'None'


@pytest.mark.parametrize('lookup_by', ['id', 'label'])
@pytest.mark.parametrize(
    'flow',
    [
        'content,description,content,description',
        'rotate,content,rotate,content,rotate',
        'label,content,label,content',
    ],
)
def test_set_secret(
    juju: jubilant.Juju,
    fresh_secret: str,
    leader: str,
    flow: str,
    lookup_by: Literal['id', 'label'],
):
    counts = collections.Counter(flow.split(','))
    if counts['label'] >= 2 and juju.status().model.version.startswith('3.2.'):
        pytest.skip('Label is sticky on Juju 3.2 in this case')

    if lookup_by == 'id':
        params = {'flow': flow, 'secretid': fresh_secret}
    else:
        params = {'flow': flow, 'secretlabel': 'thelabel'}

    rv = juju.run(leader, 'set-secret-flow', params=params)
    result = cast('Result', rv.results)

    assert 'secretid' in result
    assert 'after' in result
    assert result['after']
    assert result['after']['info']
    info = result['after']['info']

    secrets = juju.secrets()
    secret = juju.show_secret(secrets[0].uri, reveal=True)
    common_checks(secret, result)

    if counts['content']:
        assert result['after']['latest'] == {'val': str(counts['content'])}
    if counts['label']:
        assert info['label'] == f'label{counts["label"]}'
    if counts['description']:
        assert info['description'] == f'description{counts["description"]}'
    if counts['expire']:
        assert secret.expires == f'{2010 + counts["expire"]}-01-01T00:00:00Z'
    if counts['rotate']:
        rotation_values = [
            'sentinel',
            'never',
            'hourly',
            'daily',
            'weekly',
            'monthly',
            'quarterly',
            'yearly',
        ]
        assert secret.rotation == rotation_values[counts['rotate']]


@pytest.fixture
def cleanup(juju: jubilant.Juju, leader: str) -> None:
    """Remove all secrets from the test app."""
    secrets = juju.secrets()
    for secret in secrets:
        if secret.owner == 'test-secrets':
            juju.exec(f'secret-remove {secret.uri}', unit=leader)
        else:
            # Later, there could be user secrets too.
            juju.remove_secret(secret.uri)


@pytest.fixture
def fresh_secret(juju: jubilant.Juju, leader: str, cleanup: None) -> str:
    """Remove all old secrets (via cleanup) and add a new secret owned by the test app."""
    juju.exec('secret-add --label thelabel some=content', unit=leader)
    secrets = juju.secrets()
    assert secrets
    assert secrets[0].owner == 'test-secrets'
    # https://github.com/canonical/jubilant/issues/211
    return secrets[0].uri.unique_identifier


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


def common_checks(secret: jubilant.RevealedSecret | None, result: Result):
    if secret:
        assert secret.owner == 'test-secrets'

        assert 'secretid' in result
        assert result['secretid']

        assert 'after' in result
        assert (after := result['after'])
        assert 'info' in after
        assert (info := after['info'])

        short_juju_id = short_id(secret.uri)
        short_ops_id = short_id(result['secretid'])
        assert short_juju_id == short_ops_id == short_id(info['id'])

        assert secret.content == after['latest']
