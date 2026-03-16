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

import pathlib
import ssl
from unittest.mock import ANY, patch

import pytest
from opentelemetry.trace import get_tracer_provider

import ops_tracing
from ops_tracing import _backend
from ops_tracing._buffer import Destination
from ops_tracing._export import BufferingSpanExporter


def test_unset_destination(setup_tracing: None):
    assert _backend._exporter
    ops_tracing.set_destination(None, None)
    assert _backend._exporter.buffer.load_destination() == Destination(None, None)


def test_set_destination(setup_tracing: None):
    assert _backend._exporter
    ops_tracing.set_destination('http://example.com', None)
    assert _backend._exporter.buffer.load_destination() == Destination('http://example.com', None)


def test_set_destination_again(setup_tracing: None):
    assert _backend._exporter

    with patch.object(
        _backend._exporter.buffer,
        'save_destination',
        wraps=_backend._exporter.buffer.save_destination,
    ) as mock_dst:
        ops_tracing.set_destination('http://example.com/foo', None)
        ops_tracing.set_destination('http://example.com/foo', None)

    assert mock_dst.call_count == 1


@pytest.mark.parametrize('url', ['file:///etc/passwd', 'gopher://aaa'])
def test_set_destination_invalid_url(setup_tracing: None, url: str):
    assert _backend._exporter
    with pytest.raises(ValueError):
        ops_tracing.set_destination(url, None)


def test_juju_topology_labels(setup_tracing: None):
    get_tracer_provider()
    assert {**get_tracer_provider()._resource._attributes} == {  # type: ignore
        'telemetry.sdk.language': 'python',
        'telemetry.sdk.name': 'opentelemetry',
        'telemetry.sdk.version': ANY,
        'service.namespace': '4242',
        'service.namespace.name': 'test-model',
        'service.name': 'testapp',
        'service.instance.id': '42',
        'charm': 'testcharm',
        'charm_type': 'DummyCharm',
        'juju_model': 'test-model',
        'juju_model_uuid': '4242',
        'juju_application': 'testapp',
        'juju_unit': 'testapp/42',
    }


def test_exporter_ssl_context(tmp_path: pathlib.Path):
    exporter = BufferingSpanExporter(tmp_path / 'buffer')
    context = exporter.ssl_context(None)
    assert context.minimum_version == ssl.TLSVersion.TLSv1_2
    assert context.verify_flags & ssl.VERIFY_X509_PARTIAL_CHAIN
    assert not (context.verify_flags & ssl.VERIFY_X509_STRICT)


_CA = """-----BEGIN CERTIFICATE-----
MIIDBTCCAe2gAwIBAgIUAtOwYFrnTnzjwWnvkaOG024ZzKMwDQYJKoZIhvcNAQEL
BQAwEjEQMA4GA1UEAwwHdGVzdC1jYTAeFw0yNjAzMDUwNzEwNDZaFw0yNjAzMDYw
NzEwNDZaMBIxEDAOBgNVBAMMB3Rlc3QtY2EwggEiMA0GCSqGSIb3DQEBAQUAA4IB
DwAwggEKAoIBAQCo8O88eaOKdPYujv1YVUR8C/UOKBO+DppWNPVDwZV8ErEBiw7X
IA4ewsQ/XkUAPokg6eFoZEnd413nzxneuQWQZTWPYEdIHznKZmkAKwnXmy/EoDPN
ttS2KbNr8gkd57THG2zhEQlHzWNaSZjxjjRY4rJ2WeipTfFKdaVF3teCsrVJNWow
WLxgAi3Mx8T/G9LoySKPSLMRjxegpqo1rRpHImdP3WFm8up2GZtii51k/8r7Q7gi
J++ZL88dV5aaEPbOSSZOsHFbpA0T5yFiCgfjZ74FR3mMswp7lkgNai96yBLfKdts
1LZuv0KOxzpVjm1jwDDJi0sq8kRqc8GuiQiHAgMBAAGjUzBRMB0GA1UdDgQWBBQK
fnJOLUs1gFEG0TaD1vi2AmeEzTAfBgNVHSMEGDAWgBQKfnJOLUs1gFEG0TaD1vi2
AmeEzTAPBgNVHRMBAf8EBTADAQH/MA0GCSqGSIb3DQEBCwUAA4IBAQClhDJwMYUm
QaVPiST2rVMwFsTo348beIfvRckQZtVc8xrDg7cvD01S1eywpnuao+S48XMujFxe
j8DsSNNft0TH+gzddZNkeZ6bNp+xkJEy4yN/kyX7XnqRGuKN1AjHj6+se7kKZODq
pQGtEwxIhUjsokgBrVhdFxuHGOtqulf75zBaIO7CTW5VlH+vnLMvUnGQYP8mut43
SDhC0F2DURDTvg8QmqIEBCVGiQPLxkzbwWNLbeqmbkTEC+Ye61Sqieol7+aYRXIy
A+VnjPtpPgXnBLuM9tdhHY5PekgEtg0xOoShviNFQbIUNrfHWyn1hA3+52pMqbwJ
My7rmyf1ByrI
-----END CERTIFICATE-----"""


@pytest.mark.parametrize('use_ca', [True, False])
def test_exporter_ssl_context_original_implementation_matches(
    tmp_path: pathlib.Path, use_ca: bool
):
    def _ssl_context_original(ca: str | None) -> ssl.SSLContext:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.minimum_version = ssl.TLSVersion.TLSv1_2  # See comment at the top of module
        context.set_alpn_protocols(['http/1.1'])
        if partial_chain := getattr(ssl, 'VERIFY_X509_PARTIAL_CHAIN', None):
            context.verify_flags |= partial_chain
        if ca is not None:
            context.load_verify_locations(cadata=ca)
        else:
            context.load_default_certs()
        return context

    ca = _CA if use_ca else None
    new = BufferingSpanExporter(tmp_path / 'buffer').ssl_context(ca)
    original = _ssl_context_original(ca)
    assert type(new) is type(original)
    assert dir(new) == dir(original)
    for attr in dir(new):
        new_attr = getattr(new, attr)
        if callable(new_attr):
            continue
        assert new_attr == getattr(original, attr)
