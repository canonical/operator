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

"""Conformance tests for the ``certificate_transfer`` v1 interface.

These tests pin our requirer-side behaviour (the CA branch of the ``Tracing``
class and ``_read_certificates`` in ``ops_tracing/_api.py``) against the
behaviour the upstream charm relation interface documents at:

    https://canonical.com/juju/docs/charmlibs/reference/interfaces/certificate_transfer/v1/

We act as a requirer of ``certificate_transfer``: we consume the provider's
``certificates`` app-databag key and feed those PEMs into the tracing TLS
config. Each test names the verbatim clause from the v1 doc page it covers.
"""

from __future__ import annotations

import json
from unittest.mock import Mock

import ops
import ops.testing
import pytest


@pytest.fixture
def mock_destination(monkeypatch: pytest.MonkeyPatch) -> Mock:
    rv = Mock()
    monkeypatch.setattr(ops.tracing, 'set_destination', rv)
    return rv


# ---------------------------------------------------------------------------
# Provider-side clauses (we are NOT the provider; these document what a
# conforming counterpart will publish, which our requirer-side reader depends
# on):
#
#   "Is expected to provide a list of public certificates and/or CA
#    certificates"
#   "Is expected to provide the used version of the interface."
#
# The provider publishes them under the ``certificates`` app-databag key as a
# JSON array of PEM strings (per the upstream v1 schema example).
# ---------------------------------------------------------------------------


# Requirer clause, verbatim:
#   "Is expected to provide 1 as a version number and to use the provided
#    certificates and/or CA certificates to authenticate communications."
#
# Our impl honours the "use the provided certificates" half: a https://
# tracing URL combined with a populated ``certificates`` databag results in
# the CA bundle being threaded through to ``ops.tracing.set_destination``.
def test_requirer_uses_provided_certificates(
    sample_charm: type[ops.CharmBase],
    mock_destination: Mock,
    https_relation: ops.testing.Relation,
    ca_relation: ops.testing.Relation,
):
    ctx = ops.testing.Context(sample_charm)
    state = ops.testing.State(leader=True, relations={https_relation, ca_relation})
    ctx.run(ctx.on.relation_changed(ca_relation), state)
    # ca_relation publishes {'FIRST', 'SECOND'} as PEMs; we sort and join to
    # build a deterministic CA bundle.
    mock_destination.assert_called_with(url='https://tls.example/v1/traces', ca='FIRST\nSECOND')


def test_requirer_handles_empty_certificate_set(
    sample_charm: type[ops.CharmBase], mock_destination: Mock
):
    """Provider hasn't published certificates yet: an https destination is unusable."""
    https_relation = ops.testing.Relation(
        'charm-tracing',
        remote_app_data={
            'receivers': json.dumps([
                {
                    'protocol': {'name': 'otlp_http', 'type': 'http'},
                    'url': 'https://tls.example/',
                }
            ]),
        },
    )
    empty_ca = ops.testing.Relation('receive-ca-cert', remote_app_data={})
    ctx = ops.testing.Context(sample_charm)
    state = ops.testing.State(leader=True, relations={https_relation, empty_ca})
    ctx.run(ctx.on.relation_changed(empty_ca), state)
    mock_destination.assert_called_with(url=None, ca=None)


def test_requirer_handles_malformed_certificates_databag(
    sample_charm: type[ops.CharmBase], mock_destination: Mock
):
    """A provider that publishes a non-JSON ``certificates`` value must not crash us."""
    https_relation = ops.testing.Relation(
        'charm-tracing',
        remote_app_data={
            'receivers': json.dumps([
                {
                    'protocol': {'name': 'otlp_http', 'type': 'http'},
                    'url': 'https://tls.example/',
                }
            ]),
        },
    )
    bad_ca = ops.testing.Relation(
        'receive-ca-cert',
        remote_app_data={'certificates': 'not-json'},
    )
    ctx = ops.testing.Context(sample_charm)
    state = ops.testing.State(leader=True, relations={https_relation, bad_ca})
    # Must not raise; _read_certificates returns None on parse failure.
    ctx.run(ctx.on.relation_changed(bad_ca), state)
    mock_destination.assert_called_with(url=None, ca=None)


def test_requirer_reads_provider_certificates_key(
    sample_charm: type[ops.CharmBase],
    mock_destination: Mock,
    https_relation: ops.testing.Relation,
):
    """The provider publishes PEMs under the app-databag key named ``certificates``."""
    # If the upstream key ever renames, `_read_certificates` returns the
    # empty-set default and TLS would silently break. This test pins the key.
    ca_relation = ops.testing.Relation(
        'receive-ca-cert',
        remote_app_data={'certificates': json.dumps(['PEM-A', 'PEM-B', 'PEM-C'])},
    )
    ctx = ops.testing.Context(sample_charm)
    state = ops.testing.State(leader=True, relations={https_relation, ca_relation})
    ctx.run(ctx.on.relation_changed(ca_relation), state)
    # Sorted-and-joined PEMs are what reaches set_destination.
    mock_destination.assert_called_with(
        url='https://tls.example/v1/traces', ca='PEM-A\nPEM-B\nPEM-C'
    )


def test_requirer_ignores_unknown_provider_keys(
    sample_charm: type[ops.CharmBase],
    mock_destination: Mock,
    https_relation: ops.testing.Relation,
):
    """A conforming provider may add a ``version`` field; we must ignore it."""
    ca_relation = ops.testing.Relation(
        'receive-ca-cert',
        remote_app_data={
            'certificates': json.dumps(['ONLY']),
            'version': json.dumps(1),
        },
    )
    ctx = ops.testing.Context(sample_charm)
    state = ops.testing.State(leader=True, relations={https_relation, ca_relation})
    ctx.run(ctx.on.relation_changed(ca_relation), state)
    mock_destination.assert_called_with(url='https://tls.example/v1/traces', ca='ONLY')


# Requirer clause, verbatim (version half):
#   "Is expected to provide 1 as a version number ..."
#
# A dual v0/v1 provider (LIBPATCH 15+ of the vendored library) uses this to
# decide whether to publish v1 (app databag ``certificates``) or fall back to
# v0 (unit databag ``ca``/``certificate``/``chain``). We write it on
# ``-created`` on the leader only.
def test_requirer_writes_version_on_relation_created(
    sample_charm: type[ops.CharmBase],
    mock_destination: Mock,
):
    ca_relation = ops.testing.Relation('receive-ca-cert')
    ctx = ops.testing.Context(sample_charm)
    state_in = ops.testing.State(leader=True, relations={ca_relation})
    state_out = ctx.run(ctx.on.relation_created(ca_relation), state_in)
    rel_out = state_out.get_relation(ca_relation.id)
    assert rel_out.local_app_data == {'version': json.dumps(1)}


def test_requirer_follower_does_not_write_version(
    sample_charm: type[ops.CharmBase],
    mock_destination: Mock,
):
    """A follower unit must not attempt to write the app databag (Juju forbids it)."""
    ca_relation = ops.testing.Relation('receive-ca-cert')
    ctx = ops.testing.Context(sample_charm)
    state_in = ops.testing.State(leader=False, relations={ca_relation})
    state_out = ctx.run(ctx.on.relation_created(ca_relation), state_in)
    rel_out = state_out.get_relation(ca_relation.id)
    assert dict(rel_out.local_app_data) == {}


def test_requirer_reads_v0_fallback_from_unit_databag(
    sample_charm: type[ops.CharmBase],
    mock_destination: Mock,
    https_relation: ops.testing.Relation,
):
    """A v0 provider publishes ca/certificate/chain on the unit databag; we honour it."""
    ca_relation = ops.testing.Relation(
        'receive-ca-cert',
        remote_app_data={},
        remote_units_data={
            0: {
                'ca': json.dumps('CA-PEM'),
                'certificate': json.dumps('CERT-PEM'),
                'chain': json.dumps(['LEAF', 'INTER', 'ROOT']),
            },
        },
    )
    ctx = ops.testing.Context(sample_charm)
    state = ops.testing.State(leader=True, relations={https_relation, ca_relation})
    ctx.run(ctx.on.relation_changed(ca_relation), state)
    mock_destination.assert_called_with(
        url='https://tls.example/v1/traces', ca='INTER\nLEAF\nROOT'
    )
