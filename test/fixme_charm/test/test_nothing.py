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
"""FIXME docstring."""

from __future__ import annotations

import json
from unittest.mock import Mock

import pytest

import ops._tracing
import ops.testing

_pydantic = pytest.importorskip('pydantic')
from test.fixme_charm.src.charm import Charm  # noqa: E402

pytestmark = pytest.mark.filterwarnings('ignore::pydantic.PydanticDeprecatedSince20')


HTTP_RELATION = ops.testing.Relation(
    'charm-tracing',
    remote_app_data={
        'receivers': json.dumps([
            {
                'protocol': {'name': 'otlp_http', 'type': 'http'},
                'url': 'http://tracing.example:4318/v1/traces',
            }
        ]),
    },
)

HTTPS_RELATION = ops.testing.Relation(
    'charm-tracing',
    remote_app_data={
        'receivers': json.dumps([
            {
                'protocol': {'name': 'otlp_http', 'type': 'http'},
                'url': 'https://tls.example/v1/traces',
            }
        ]),
    },
)

CA_RELATION = ops.testing.Relation(
    'send-ca-cert',
    remote_app_data={
        'certificates': json.dumps(['FIRST', 'SECOND']),
    },
)


def test_charm_runs():
    ctx = ops.testing.Context(Charm)
    state_in = ops.testing.State()
    state_out = ctx.run(ctx.on.start(), state_in)
    assert isinstance(state_out.unit_status, ops.ActiveStatus)


@pytest.fixture
def mock_destination(monkeypatch: pytest.MonkeyPatch) -> Mock:
    rv = Mock()
    monkeypatch.setattr(ops._tracing, 'set_tracing_destination', rv)
    return rv


def test_no_tracing_destination(mock_destination: Mock):
    ctx = ops.testing.Context(Charm)
    state = ops.testing.State()
    ctx.run(ctx.on.start(), state)
    mock_destination.assert_called_with(url=None, ca=None)


def test_http_tracing_destination(mock_destination: Mock):
    ctx = ops.testing.Context(Charm)
    state = ops.testing.State(relations={HTTP_RELATION})
    ctx.run(ctx.on.relation_changed(HTTP_RELATION), state)
    mock_destination.assert_called_with(url='http://tracing.example:4318/v1/traces', ca=None)


@pytest.mark.parametrize('relation', [HTTPS_RELATION, CA_RELATION])
def test_https_tracing_destination(mock_destination: Mock, relation: ops.testing.Relation):
    ctx = ops.testing.Context(Charm)
    state = ops.testing.State(relations={HTTPS_RELATION, CA_RELATION})
    ctx.run(ctx.on.relation_changed(relation), state)
    mock_destination.assert_called_with(url='https://tls.example/v1/traces', ca='FIRST\nSECOND')
