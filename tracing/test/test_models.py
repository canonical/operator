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

"""Round-trip and validation tests for the de-pydantic'd databag models.

These exercise the load/dump validation paths that the dataclass replacements
now own (previously provided by pydantic). They must pass without pydantic
installed.
"""

from __future__ import annotations

import json

import pytest

from ops_tracing._cert_transfer_models import (
    DataValidationError as CertDataValidationError,
)
from ops_tracing._cert_transfer_models import (
    ProviderApplicationData,
)
from ops_tracing._tracing_models import (
    DataValidationError as TracingDataValidationError,
)
from ops_tracing._tracing_models import (
    TracingProviderAppData,
    TracingRequirerAppData,
    TransportProtocolType,
)


def test_tracing_requirer_app_data_load():
    databag = {'receivers': json.dumps(['otlp_http'])}
    assert TracingRequirerAppData.load(databag) == TracingRequirerAppData(receivers=['otlp_http'])


def test_tracing_provider_app_data_from_wire_format():
    # The exact shape conftest's http_relation publishes.
    databag = {
        'receivers': json.dumps([
            {
                'protocol': {'name': 'otlp_http', 'type': 'http'},
                'url': 'http://tracing.example:4318/',
            }
        ])
    }
    loaded = TracingProviderAppData.load(databag)
    assert loaded.receivers[0].url == 'http://tracing.example:4318/'
    assert loaded.receivers[0].protocol.name == 'otlp_http'
    assert loaded.receivers[0].protocol.type is TransportProtocolType.http


def test_tracing_provider_app_data_missing_required_field():
    with pytest.raises(TracingDataValidationError):
        TracingProviderAppData.load({})


def test_tracing_load_invalid_json():
    with pytest.raises(TracingDataValidationError):
        TracingProviderAppData.load({'receivers': 'not-json'})


def test_tracing_load_ignores_extra_keys():
    databag = {
        'receivers': json.dumps([]),
        'ingress-address': json.dumps('10.0.0.1'),
        'private-address': json.dumps('10.0.0.1'),
    }
    loaded = TracingProviderAppData.load(databag)
    assert loaded == TracingProviderAppData(receivers=[])


def test_provider_application_data_default_is_empty_set():
    # The no-arg construction must produce a fresh empty set (default_factory,
    # not a shared mutable default).
    first = ProviderApplicationData()
    second = ProviderApplicationData()
    assert first.certificates == set()
    first.certificates.add('x')
    assert second.certificates == set()


def test_provider_application_data_empty_load():
    # Loading an empty databag yields the default empty set, and is "ready".
    assert ProviderApplicationData.load({}) == ProviderApplicationData()
    assert ProviderApplicationData.load({}).certificates == set()


def test_provider_application_data_load_invalid_json():
    with pytest.raises(CertDataValidationError):
        ProviderApplicationData.load({'certificates': 'not-json'})


def test_provider_application_data_load_ignores_extra_keys():
    databag = {
        'certificates': json.dumps(['FIRST']),
        'egress-subnets': json.dumps('10.0.0.0/24'),
    }
    loaded = ProviderApplicationData.load(databag)
    assert loaded == ProviderApplicationData(certificates={'FIRST'})
