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
from typing import Type, TypeAlias
from unittest.mock import Mock

import ops
import ops.testing
import pytest

_pydantic = pytest.importorskip('pydantic')

pytestmark = pytest.mark.filterwarnings('ignore::pydantic.PydanticDeprecatedSince20')


def test_charm_runs(sample_charm: Type[ops.CharmBase]):
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


RECEIVER: TypeAlias = dict[str, int | str | dict[str, str]]
RECEIVERS: TypeAlias = list[RECEIVER]
GOOD_PROTOCOL: RECEIVER = {'protocol': {'name': 'otlp_http', 'type': 'http'}}
GOOD_HTTP_URL: RECEIVER = {'url': 'http://tracing.example:4318/'}
GOOD_HTTPS_URL: RECEIVER = {'url': 'https://tls.example:4318/'}
GRPC_RECEIVER: RECEIVER = {'protocol': {'name': 'otlp_grpc', 'type': 'grpc'}, 'url': 'grpc://'}


@pytest.mark.parametrize(
    'event',
    [
        'start',
        'upgrade_charm',
        'relation_changed',
        'relation_broken',
    ],
)
@pytest.mark.parametrize(
    'receiver',
    [
        {**GOOD_PROTOCOL, **GOOD_HTTP_URL},
        {**GOOD_PROTOCOL, **GOOD_HTTPS_URL},
    ],
)
@pytest.mark.parametrize(
    'extra_databag_fields', [{}, {'foo': 'not-json'}, {'foo': '"json-str"'}, {'version': '1'}]
)
@pytest.mark.parametrize('extra_receiver', [None, GRPC_RECEIVER])
@pytest.mark.parametrize('extra_receiver_fields', [{}, {'foo': 'bar'}])
def test_foo(
    sample_charm: Type[ops.CharmBase],
    mock_destination: Mock,
    ca_relation: ops.testing.Relation,
    monkeypatch: pytest.MonkeyPatch,
    event: str,
    receiver: RECEIVER,
    extra_databag_fields: dict[str, str],
    extra_receiver: RECEIVER | None,
    extra_receiver_fields: RECEIVER,
):
    url = f'{receiver["url"].strip("/")}/v1/traces'  # type: ignore
    ca = 'FIRST\nSECOND' if url.startswith('https') else None
    receiver = {**receiver, **extra_receiver_fields}
    receivers = [receiver] if extra_receiver is None else [receiver, extra_receiver]
    databag = {'receivers': json.dumps(receivers), **extra_databag_fields}
    charm_tracing_relation = ops.testing.Relation('charm-tracing', id=0, remote_app_data=databag)

    ctx = ops.testing.Context(sample_charm)
    state = ops.testing.State(relations={charm_tracing_relation, ca_relation}, leader=True)

    event_args = [charm_tracing_relation] if event.startswith('relation') else []
    state = ctx.run(getattr(ctx.on, event)(*event_args), state)

    if event == 'relation_broken':
        mock_destination.assert_called_with(url=None, ca=None)
    else:
        assert state.get_relation(0).local_app_data == {'receivers': '["otlp_http"]'}
        mock_destination.assert_called_with(url=url, ca=ca)

    monkeypatch.setattr('ops.tracing.Tracing', ops.tracing.Tracing2)
    ctx = ops.testing.Context(sample_charm)
    state = ops.testing.State(relations={charm_tracing_relation, ca_relation}, leader=True)

    event_args = [charm_tracing_relation] if event.startswith('relation') else []
    state = ctx.run(getattr(ctx.on, event)(*event_args), state)

    if event == 'relation_broken':
        mock_destination.assert_called_with(url=None, ca=None)
    else:
        assert state.get_relation(0).local_app_data == {'receivers': '["otlp_http"]'}
        mock_destination.assert_called_with(url=url, ca=ca)
