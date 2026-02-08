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
import pathlib
import sys
from typing import Generator

import ops
import ops.testing
import pytest

import ops_tracing


@pytest.fixture
def http_relation():
    return ops.testing.Relation(
        'charm-tracing',
        remote_app_data={
            'receivers': json.dumps([
                {
                    'protocol': {'name': 'otlp_http', 'type': 'http'},
                    'url': 'http://tracing.example:4318/',
                }
            ]),
        },
    )


@pytest.fixture
def https_relation():
    return ops.testing.Relation(
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


@pytest.fixture
def ca_relation():
    return ops.testing.Relation(
        'receive-ca-cert',
        remote_app_data={
            'certificates': json.dumps(['FIRST', 'SECOND']),
        },
    )


@pytest.fixture
def juju_context(tmp_path: pathlib.Path):
    (tmp_path / 'metadata.yaml').write_text('name: testcharm')
    return ops.JujuContext._from_dict({
        'JUJU_VERSION': '3.6.0',
        'JUJU_MODEL_NAME': 'test-model',
        'JUJU_MODEL_UUID': '4242',
        'JUJU_UNIT_NAME': 'testapp/42',
        'JUJU_CHARM_DIR': str(tmp_path),
    })


@pytest.fixture
def setup_tracing(juju_context: ops.JujuContext):
    ops_tracing._setup(juju_context, 'DummyCharm')
    yield
    ops_tracing._shutdown()
    # Note that OpenTelemetry disallows setting the tracer provider twice,
    # a warning is issued and new provider is ignored.
    # For example, we could reset the resource instead:
    # get_tracer_provider()._resource = resource
    #
    # This would be the place to clean up
    # - tracing db content doesn't matter as the db file is located in unique file per test
    # - forcibly reset the OpenTelemetry global state
    #   - tracing provider span processor, as that holds the helper thread
    #   - the tracing provider, perhaps?


@pytest.fixture
def sample_charm() -> Generator[type[ops.CharmBase]]:
    extra = str(pathlib.Path(__file__).parent / 'sample_charm/src')
    sys.path.append(extra)
    from charm import SampleCharm  # type: ignore

    yield SampleCharm
    sys.path.remove(extra)
