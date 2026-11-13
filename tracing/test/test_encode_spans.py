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
from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan, SpanLimits, TracerProvider
from opentelemetry.trace import Link, NonRecordingSpan, SpanContext, TraceFlags

from ops_tracing._otlp_json import encode_spans


def _encode_one(span: trace.Span) -> dict[str, Any]:
    assert isinstance(span, ReadableSpan)  # The SDK's Span is one; the API type is not.
    payload = encode_spans([span])
    # Reject NaN and Infinity, which Python's json module accepts but JSON does not allow.
    decoded = json.loads(payload, parse_constant=lambda c: pytest.fail(f'invalid JSON: {c}'))
    return decoded['resourceSpans'][0]['scopeSpans'][0]['spans'][0]


def _attributes(encoded: dict[str, Any]) -> dict[str, Any]:
    return {a['key']: a['value'] for a in encoded.get('attributes', [])}


def test_non_finite_floats():
    tracer = TracerProvider().get_tracer('t')
    span = tracer.start_span(
        's',
        attributes={
            'nan': float('nan'),
            'inf': float('inf'),
            'ninf': float('-inf'),
            'num': 1.5,
        },
    )
    span.end()

    assert _attributes(_encode_one(span)) == {
        'nan': {'doubleValue': 'NaN'},
        'inf': {'doubleValue': 'Infinity'},
        'ninf': {'doubleValue': '-Infinity'},
        'num': {'doubleValue': 1.5},
    }


def test_none_in_array():
    tracer = TracerProvider().get_tracer('t')
    span = tracer.start_span('s', attributes={'seq': ['a', None, 'b']})
    span.end()

    encoded = _encode_one(span)
    assert _attributes(encoded) == {
        'seq': {'arrayValue': {'values': [{'stringValue': 'a'}, {}, {'stringValue': 'b'}]}},
    }
    assert 'dropped_attributes_count' not in encoded
    assert 'droppedAttributesCount' not in encoded


def test_flags_local_parent():
    tracer = TracerProvider().get_tracer('t')
    span = tracer.start_span('s')
    span.end()

    flags = _encode_one(span)['flags']
    assert flags & TraceFlags.SAMPLED
    assert flags & 0x100
    assert not flags & 0x200


def test_flags_remote_parent():
    tracer = TracerProvider().get_tracer('t')
    parent = NonRecordingSpan(SpanContext(0x1234, 0x56, is_remote=True, trace_flags=TraceFlags(1)))
    span = tracer.start_span('s', context=trace.set_span_in_context(parent))
    span.end()

    flags = _encode_one(span)['flags']
    assert flags & TraceFlags.SAMPLED
    assert flags & 0x300 == 0x300


def test_links():
    tracer = TracerProvider().get_tracer('t')
    link = Link(SpanContext(0x1234, 0x56, is_remote=True, trace_flags=TraceFlags(1)), {'k': 'v'})
    span = tracer.start_span('s', links=[link])
    span.end()

    encoded = _encode_one(span)
    assert encoded['links'] == [
        {
            'traceId': '00000000000000000000000000001234',
            'spanId': '0000000000000056',
            'flags': 0x301,
            'attributes': [{'key': 'k', 'value': {'stringValue': 'v'}}],
        }
    ]
    assert 'droppedLinksCount' not in encoded


def test_dropped_events_and_links():
    provider = TracerProvider(span_limits=SpanLimits(max_events=1, max_links=1))
    tracer = provider.get_tracer('t')
    context = SpanContext(0x1234, 0x56, is_remote=False)
    span = tracer.start_span('s', links=[Link(context), Link(context)])
    span.add_event('one')
    span.add_event('two')
    span.end()

    encoded = _encode_one(span)
    assert len(encoded['events']) == 1
    assert encoded['droppedEventsCount'] == 1
    assert len(encoded['links']) == 1
    assert encoded['droppedLinksCount'] == 1
