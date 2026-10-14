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
from typing import Any

import pytest
from opentelemetry.sdk.trace import SpanLimits, TracerProvider
from opentelemetry.trace import SpanKind

from ops_tracing._otlp_json import encode_spans  # type: ignore


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


def _encode_span(attributes: dict[str, Any], limits: SpanLimits | None = None) -> dict[str, Any]:
    tracer = TracerProvider(span_limits=limits).get_tracer('test')
    span = tracer.start_span('span', attributes=attributes)
    span.end()
    payload = json.loads(encode_spans([span]))  # type: ignore
    return payload['resourceSpans'][0]['scopeSpans'][0]['spans'][0]


def test_bytes_attribute_is_base64():
    encoded_span = _encode_span({'b': b'hi'})

    assert encoded_span['attributes'] == [{'key': 'b', 'value': {'bytesValue': 'aGk='}}]


def test_mapping_attribute_is_key_value_list():
    encoded_span = _encode_span({'m': {'x': 1, 'y': 'z'}})

    assert encoded_span['attributes'] == [
        {
            'key': 'm',
            'value': {
                'kvlistValue': {
                    'values': [
                        {'key': 'x', 'value': {'intValue': '1'}},
                        {'key': 'y', 'value': {'stringValue': 'z'}},
                    ]
                }
            },
        }
    ]


def test_dropped_attributes_count_includes_sdk_limits():
    encoded_span = _encode_span({'a': 1, 'b': 2, 'c': 3}, SpanLimits(max_span_attributes=1))

    assert encoded_span['droppedAttributesCount'] == 2
    assert 'dropped_attributes_count' not in encoded_span


def test_dropped_attributes_count_includes_unencodable_values():
    encoded_span = _encode_span({'a': 1, 'mixed': [1, 'x']})

    assert encoded_span['attributes'] == [{'key': 'a', 'value': {'intValue': '1'}}]
    assert encoded_span['droppedAttributesCount'] == 1


def test_no_dropped_attributes_count_when_nothing_dropped():
    encoded_span = _encode_span({'a': 1})

    assert 'droppedAttributesCount' not in encoded_span
