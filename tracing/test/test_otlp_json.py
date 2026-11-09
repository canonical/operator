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

from __future__ import annotations

import json

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import SpanKind

from ops_tracing._otlp_json import encode_spans


# The OTLP span kind values, from opentelemetry/proto/trace/v1/trace.proto.
@pytest.mark.parametrize(
    'kind,otlp_kind',
    [
        (SpanKind.INTERNAL, 1),
        (SpanKind.SERVER, 2),
        (SpanKind.CLIENT, 3),
        (SpanKind.PRODUCER, 4),
        (SpanKind.CONSUMER, 5),
    ],
)
def test_span_kind(kind: SpanKind, otlp_kind: int):
    tracer = TracerProvider().get_tracer('test')
    span = tracer.start_span('span', kind=kind)
    span.end()

    payload = json.loads(encode_spans([span]))  # type: ignore

    encoded_span = payload['resourceSpans'][0]['scopeSpans'][0]['spans'][0]
    assert encoded_span['kind'] == otlp_kind
