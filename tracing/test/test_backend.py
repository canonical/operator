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

from unittest.mock import ANY, patch

import pytest
from opentelemetry.trace import get_tracer_provider

import ops_tracing
from ops_tracing import _backend
from ops_tracing._buffer import Destination


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
