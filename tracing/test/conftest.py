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
"""FIXME docstring."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

if '' not in sys.path:
    # FIXME: figure out if this is needed long term and why.
    # I think it's because some ancestor is not a package.
    sys.path.insert(0, '')


import ops
import ops.testing
from ops.jujucontext import _JujuContext


@pytest.fixture
def http_relation():
    return ops.testing.Relation(
        'charm-tracing',
        remote_app_data={
            'receivers': json.dumps([
                {
                    'protocol': {'name': 'otlp_http', 'type': 'http'},
                    'url': 'http://tracing.example:4318/v1/traces',
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
                    'url': 'https://tls.example/v1/traces',
                }
            ]),
        },
    )


@pytest.fixture
def ca_relation():
    return ops.testing.Relation(
        'send-ca-cert',
        remote_app_data={
            'certificates': json.dumps(['FIRST', 'SECOND']),
        },
    )


@pytest.fixture
def juju_context(tmp_path: Path):
    return _JujuContext.from_dict({
        'JUJU_VERSION': '3.6.0',
        'JUJU_UNIT_NAME': 'app/0',
        'JUJU_CHARM_DIR': str(tmp_path),
    })


@pytest.fixture
def setup_tracing(monkeypatch: pytest.MonkeyPatch, juju_context: _JujuContext):
    with ops.tracing.setup(juju_context, 'charm'):
        yield
    # TODO: this would be the place to clean up
    # - tracing db content doesn't matter as the db file is located in unique file per test
    # - forcibly reset the opentelemetry global state
    #   - tracing provider span processor, as that holds the helper thread
    #   - the tracing provider, perhaps?


@pytest.fixture
def sample_charm():
    extra = str(Path(__file__).parent / 'sample_charm/src')
    sys.path.append(extra)
    from charm import SampleCharm

    yield SampleCharm
    sys.path.remove(extra)
