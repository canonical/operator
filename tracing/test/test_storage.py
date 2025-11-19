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

import ops
import ops.testing
import pytest

from ops_tracing import _backend
from ops_tracing._buffer import Destination

_pydantic = pytest.importorskip('pydantic')
_export = pytest.importorskip('ops._tracing.export')


@pytest.mark.parametrize('relation_to_poke', [0, 1])
def test_https_tracing_destination(
    sample_charm: type[ops.CharmBase],
    setup_tracing: None,
    https_relation: ops.testing.Relation,
    ca_relation: ops.testing.Relation,
    relation_to_poke: int,
):
    ctx = ops.testing.Context(sample_charm)
    state = ops.testing.State(relations={https_relation, ca_relation})
    ctx.run(ctx.on.relation_changed([https_relation, ca_relation][relation_to_poke]), state)

    assert _backend._exporter
    assert _backend._exporter.buffer.load_destination() == Destination(
        'https://tls.example/v1/traces',
        'FIRST\nSECOND',
    )
