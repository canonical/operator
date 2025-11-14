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

from unittest.mock import Mock

import ops
import ops.testing
import pytest

_pydantic = pytest.importorskip('pydantic')

pytestmark = pytest.mark.filterwarnings('ignore::pydantic.PydanticDeprecatedSince20')


def test_charm_runs(sample_charm: type[ops.CharmBase]):
    ctx = ops.testing.Context(sample_charm)
    state_in = ops.testing.State()
    state_out = ctx.run(ctx.on.start(), state_in)
    assert isinstance(state_out.unit_status, ops.ActiveStatus)
    assert 'ops.main' in [span.name for span in ctx.trace_data]
    assert 'my collect status' in [span.name for span in ctx.trace_data]


@pytest.fixture
def mock_destination(monkeypatch: pytest.MonkeyPatch) -> Mock:
    rv = Mock()
    monkeypatch.setattr(ops.tracing, 'set_destination', rv)
    return rv


def test_no_tracing_destination(sample_charm: type[ops.CharmBase], mock_destination: Mock):
    ctx = ops.testing.Context(sample_charm)
    state = ops.testing.State()
    ctx.run(ctx.on.start(), state)
    mock_destination.assert_called_with(url=None, ca=None)


def test_http_tracing_destination(
    sample_charm: type[ops.CharmBase], mock_destination: Mock, http_relation: ops.testing.Relation
):
    ctx = ops.testing.Context(sample_charm)
    state = ops.testing.State(relations={http_relation})
    ctx.run(ctx.on.relation_changed(http_relation), state)
    mock_destination.assert_called_with(url='http://tracing.example:4318/v1/traces', ca=None)


@pytest.mark.parametrize('relation_to_poke', [0, 1])
def test_https_tracing_destination(
    sample_charm: type[ops.CharmBase],
    mock_destination: Mock,
    https_relation: ops.testing.Relation,
    ca_relation: ops.testing.Relation,
    relation_to_poke: int,
):
    ctx = ops.testing.Context(sample_charm)
    state = ops.testing.State(relations={https_relation, ca_relation})
    ctx.run(ctx.on.relation_changed([https_relation, ca_relation][relation_to_poke]), state)
    mock_destination.assert_called_with(url='https://tls.example/v1/traces', ca='FIRST\nSECOND')
