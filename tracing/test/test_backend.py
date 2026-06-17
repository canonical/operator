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

import io
import logging
import pathlib
import ssl
import urllib.error
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


def test_exporter_http_error_log_format(tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture):
    """HTTPError responses log the URL, status, and truncated body without a traceback."""
    exporter = BufferingSpanExporter(tmp_path / 'buffer')
    url = 'http://collector.example/v1/traces'
    exporter.buffer.save_destination(Destination(url, None))

    long_body = b'x' * 5000
    http_error = urllib.error.HTTPError(
        url,
        503,
        'Service Unavailable',
        {},
        io.BytesIO(long_body),  # type: ignore[arg-type]
    )

    with patch('urllib.request.urlopen', side_effect=http_error), caplog.at_level(
        logging.ERROR, logger='ops_tracing._export'
    ):
        exporter.do_export(buffered_id=0, data=b'\x00', mime='application/x-protobuf')

    rejected = [r for r in caplog.records if 'rejected our data' in r.getMessage()]
    assert len(rejected) == 1
    record = rejected[0]
    assert record.levelno == logging.ERROR
    # `logger.error(...)` should not attach exception info -- we have the status code.
    assert record.exc_info is None
    message = record.getMessage()
    assert url in message
    assert 'e.code=503' in message
    # The body must be capped at 1000 bytes to bound log size.
    assert repr(b'x' * 1000) in message
    assert repr(b'x' * 1001) not in message
