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

"""Conformance tests for the ``tracing`` v2 interface.

These tests pin our requirer-side behaviour (the ``Tracing`` class and its
helpers in ``ops_tracing/_api.py``) against the behaviour the upstream charm
relation interface documents at:

    https://canonical.com/juju/docs/charmlibs/reference/interfaces/tracing/v2/

Each test names the verbatim "Is expected to..." clause it covers. If the
upstream doc changes the contract, the relevant test should be the place that
forces a deliberate decision about whether to follow.
"""

from __future__ import annotations

import json
from unittest.mock import Mock

import ops
import ops.testing
import pytest

# ---------------------------------------------------------------------------
# Per the upstream doc:
#
#   "Tracing is done in a push-based fashion."
#
# We are the *requirer* (we push traces to the provider). The expectations
# below are the requirer-side clauses on the v2 doc page, exactly as written.
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_destination(monkeypatch: pytest.MonkeyPatch) -> Mock:
    rv = Mock()
    monkeypatch.setattr(ops.tracing, 'set_destination', rv)
    return rv


# "Is expected to publish a list of one or more protocols it wishes to use to
# send traces."
def test_requirer_publishes_requested_protocols(
    sample_charm: type[ops.CharmBase], mock_destination: Mock
):
    """The leader unit writes the ``receivers`` list to its app databag."""
    empty_relation = ops.testing.Relation('charm-tracing')
    ctx = ops.testing.Context(sample_charm)
    state_in = ops.testing.State(leader=True, relations={empty_relation})
    state_out = ctx.run(ctx.on.relation_changed(empty_relation), state_in)

    rel_out = state_out.get_relation(empty_relation.id)
    raw = rel_out.local_app_data.get('receivers')
    assert raw is not None, 'requirer did not publish a `receivers` key'
    receivers = json.loads(raw)
    # "a list of one or more protocols"
    assert isinstance(receivers, list)
    assert len(receivers) >= 1
    # Our concrete request is `otlp_http`; if this ever changes we want a
    # conscious update here, not silent drift.
    assert receivers == ['otlp_http']


# "Is expected to publish a list of one or more protocols it wishes to use to
# send traces."  (non-leader half: only the leader may write app data, so a
# follower must NOT attempt to write — it would crash the hook.)
def test_requirer_only_leader_publishes(sample_charm: type[ops.CharmBase], mock_destination: Mock):
    empty_relation = ops.testing.Relation('charm-tracing')
    ctx = ops.testing.Context(sample_charm)
    state_in = ops.testing.State(leader=False, relations={empty_relation})
    state_out = ctx.run(ctx.on.relation_changed(empty_relation), state_in)

    rel_out = state_out.get_relation(empty_relation.id)
    assert 'receivers' not in rel_out.local_app_data


# "Is expected to await receiving from the provider a list of endpoints."
def test_requirer_awaits_provider_endpoints(
    sample_charm: type[ops.CharmBase], mock_destination: Mock
):
    """Until the provider publishes a usable receiver, the destination is unset."""
    empty_relation = ops.testing.Relation('charm-tracing')
    ctx = ops.testing.Context(sample_charm)
    state = ops.testing.State(leader=True, relations={empty_relation})
    ctx.run(ctx.on.relation_changed(empty_relation), state)
    mock_destination.assert_called_with(url=None, ca=None)


# "Is expected to push traces to one or more of the provided endpoints using
# the corresponding encoding/protocol."
def test_requirer_uses_provided_endpoint(
    sample_charm: type[ops.CharmBase],
    mock_destination: Mock,
    http_relation: ops.testing.Relation,
):
    """When the provider advertises our requested protocol, we point at it."""
    ctx = ops.testing.Context(sample_charm)
    state = ops.testing.State(leader=True, relations={http_relation})
    ctx.run(ctx.on.relation_changed(http_relation), state)
    # `otlp_http`'s OTLP/HTTP path is /v1/traces (per the OTLP spec); our
    # _get_destination appends it to the base URL the provider advertises.
    mock_destination.assert_called_with(url='http://tracing.example:4318/v1/traces', ca=None)


# "Is expected to handle cases where none of the requested protocols is
# supported."
def test_requirer_handles_no_supported_protocol(
    sample_charm: type[ops.CharmBase], mock_destination: Mock
):
    """Provider only offers protocols we did NOT request: degrade quietly."""
    # We request otlp_http; provider only advertises otlp_grpc.
    relation = ops.testing.Relation(
        'charm-tracing',
        remote_app_data={
            'receivers': json.dumps([
                {
                    'protocol': {'name': 'otlp_grpc', 'type': 'grpc'},
                    'url': 'tracing.example:4317',
                }
            ]),
        },
    )
    ctx = ops.testing.Context(sample_charm)
    state = ops.testing.State(leader=True, relations={relation})
    # Must not raise; we're "expected to handle" this case.
    ctx.run(ctx.on.relation_changed(relation), state)
    mock_destination.assert_called_with(url=None, ca=None)


# ---------------------------------------------------------------------------
# Provider-side clauses on the v2 doc page (we do NOT implement these — we are
# the requirer only). We assert the converse: that our requirer behaviour is
# correctly *driven by* what the spec promises a conforming provider will
# publish.
#
# Provider clauses, verbatim:
#   "Is expected to publish the url at which the server is reachable. (This
#    will happen in any case and doubles down as an acknowledgement of
#    receipt)"
#   "Is expected to comply as good as possible with the requested protocols,
#    activating the corresponding receivers."
#   "Is expected to run a server accepting trace submissions on **all** the
#    supported **and** requested tracing protocols."
#   "Is expected to publish, for each protocol it accepts, the port at which
#    the server is listening along with the name of the supported protocol."
# ---------------------------------------------------------------------------


def test_requirer_picks_matching_protocol_when_multiple_offered(
    sample_charm: type[ops.CharmBase], mock_destination: Mock
):
    """A conforming provider may publish many receivers; we pick `otlp_http`."""
    relation = ops.testing.Relation(
        'charm-tracing',
        remote_app_data={
            'receivers': json.dumps([
                {
                    'protocol': {'name': 'zipkin', 'type': 'http'},
                    'url': 'http://tracing.example:9411/',
                },
                {
                    'protocol': {'name': 'otlp_grpc', 'type': 'grpc'},
                    'url': 'tracing.example:4317',
                },
                {
                    'protocol': {'name': 'otlp_http', 'type': 'http'},
                    'url': 'http://tracing.example:4318/',
                },
            ]),
        },
    )
    ctx = ops.testing.Context(sample_charm)
    state = ops.testing.State(leader=True, relations={relation})
    ctx.run(ctx.on.relation_changed(relation), state)
    mock_destination.assert_called_with(url='http://tracing.example:4318/v1/traces', ca=None)
