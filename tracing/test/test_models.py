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

"""Load-path tests for the de-pydantic'd tracing dataclasses.

Drives ``ops.Relation.load`` end-to-end via ``ops.testing`` so the recursive
dataclass/enum coercion in ops is what gets exercised.
"""

from __future__ import annotations

import json

import pytest

from ops_tracing._tracing_models import TracingProviderAppData, TransportProtocolType


def test_tracing_provider_app_data_from_wire_format(load_provider_app_data):
    databag = {
        'receivers': json.dumps([
            {
                'protocol': {'name': 'otlp_http', 'type': 'http'},
                'url': 'http://tracing.example:4318/',
            }
        ])
    }
    loaded = load_provider_app_data(databag)
    assert loaded.receivers[0].url == 'http://tracing.example:4318/'
    assert loaded.receivers[0].protocol.name == 'otlp_http'
    assert loaded.receivers[0].protocol.type is TransportProtocolType.http


def test_tracing_provider_app_data_missing_required_field(load_provider_app_data):
    with pytest.raises(TypeError):
        load_provider_app_data({})


def test_tracing_load_invalid_json(load_provider_app_data):
    with pytest.raises(json.JSONDecodeError):
        load_provider_app_data({'receivers': 'not-json'})


def test_tracing_load_ignores_extra_keys(load_provider_app_data):
    databag = {
        'receivers': json.dumps([]),
        'ingress-address': json.dumps('10.0.0.1'),
        'private-address': json.dumps('10.0.0.1'),
    }
    loaded = load_provider_app_data(databag)
    assert loaded == TracingProviderAppData(receivers=[])
