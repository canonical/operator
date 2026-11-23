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

"""Hypothesis property-based tests for ops_tracing's OTLP/JSON encoder.

``ops_tracing._otlp_json`` is our own encoder. The tests build spans with the
OpenTelemetry SDK, encode them with it, and parse the result into the real
``ExportTraceServiceRequest`` with ``google.protobuf.json_format``. The parse
catches output that a strict collector would reject. The parsed request is
then compared with what the official encoder,
``opentelemetry-exporter-otlp-proto-common``, builds for the same spans, which
catches fields that are dropped or encoded differently.

The tests marked ``xfail`` are the differences known when this was written.
Each one should start passing when its fix lands, and then the ``xfail``
comes off.
"""

from __future__ import annotations

import base64
import json
from typing import Any, cast

import pytest
from google.protobuf import json_format
from hypothesis import given
from hypothesis import strategies as st
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.common.trace_encoder import (
    encode_spans as official_encode_spans,
)
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.id_generator import IdGenerator
from opentelemetry.trace import Link, SpanContext, SpanKind, Status, StatusCode, TraceFlags
from opentelemetry.trace.span import TraceState
from ops_tracing._otlp_json import encode_spans

_INT64_MIN = -(2**63)
_INT64_MAX = 2**63 - 1

# ── strategies ──────────────────────────────────────────────────────────────

_names = st.text(min_size=1, max_size=20)
_keys = st.text(min_size=1, max_size=10)
# Integers outside int64 (test_out_of_range_int_attribute) and floats that
# aren't finite (test_non_finite_float_attribute) are known differences.
_scalars = st.one_of(
    st.text(max_size=20),
    st.booleans(),
    st.integers(_INT64_MIN, _INT64_MAX),
    st.floats(allow_nan=False, allow_infinity=False),
)
# The SDK only keeps sequences whose items all have the same type.
_sequences = st.one_of(
    st.lists(st.text(max_size=10), max_size=4),
    st.lists(st.booleans(), max_size=4),
    st.lists(st.integers(_INT64_MIN, _INT64_MAX), max_size=4),
    st.lists(st.floats(allow_nan=False, allow_infinity=False), max_size=4),
).map(tuple)
_attributes = st.dictionaries(_keys, st.one_of(_scalars, _sequences), max_size=5)
# Nanoseconds since the epoch, from 1970 to about 2262.
_times = st.integers(1, _INT64_MAX // 2)
_trace_ids = st.integers(1, 2**128 - 1)
_span_ids = st.integers(1, 2**64 - 1)
_statuses = st.one_of(
    st.just(Status(StatusCode.UNSET)),
    st.just(Status(StatusCode.OK)),
    st.builds(Status, st.just(StatusCode.ERROR), st.text(max_size=20)),
)


class _DrawnIds(IdGenerator):
    """Trace and span IDs drawn by Hypothesis, rather than with ``random``."""

    def __init__(self, draw: st.DrawFn):
        self._draw = draw

    def generate_span_id(self) -> int:
        return self._draw(_span_ids)

    def generate_trace_id(self) -> int:
        return self._draw(_trace_ids)


@st.composite
def _spans(draw: st.DrawFn) -> list[ReadableSpan]:
    """Spans from one tracer, some of them children of earlier ones.

    The spans have no links, which are a known difference (test_links).
    """
    provider = TracerProvider(resource=Resource(draw(_attributes)), id_generator=_DrawnIds(draw))
    tracer = provider.get_tracer(draw(_names), draw(st.none() | _names))
    spans: list[Any] = []
    for _ in range(draw(st.integers(1, 4))):
        parent = draw(st.none() | st.sampled_from(spans)) if spans else None
        start = draw(_times)
        span = tracer.start_span(
            draw(_names),
            context=trace.set_span_in_context(parent) if parent is not None else None,
            kind=draw(st.sampled_from(SpanKind)),
            attributes=draw(_attributes),
            start_time=start,
        )
        for _ in range(draw(st.integers(0, 2))):
            span.add_event(
                draw(_names), draw(_attributes), timestamp=draw(st.integers(start, _INT64_MAX))
            )
        span.set_status(draw(_statuses))
        span.end(end_time=draw(st.integers(start, _INT64_MAX)))
        spans.append(span)
    return spans


# ── helpers ─────────────────────────────────────────────────────────────────


_ID_FIELDS = ('traceId', 'spanId', 'parentSpanId')


def _hex_ids_to_base64(value: Any) -> Any:
    """Turn OTLP/JSON's hex IDs into the base64 that protobuf's JSON mapping uses.

    OTLP/JSON differs from the standard protobuf JSON mapping here: trace and
    span IDs are hex strings, not base64, so a receiver converts them before
    parsing (https://opentelemetry.io/docs/specs/otlp/#json-protobuf-encoding).
    """
    if isinstance(value, list):
        return [_hex_ids_to_base64(item) for item in cast('list[Any]', value)]
    if isinstance(value, dict):
        converted: dict[str, Any] = {}
        for key, item in cast('dict[str, Any]', value).items():
            if key in _ID_FIELDS and isinstance(item, str) and item:
                converted[key] = base64.b64encode(bytes.fromhex(item)).decode()
            else:
                converted[key] = _hex_ids_to_base64(item)
        return converted
    return value


def _parse(payload: bytes) -> ExportTraceServiceRequest:
    """Parse an OTLP/JSON payload as a strict receiver would."""
    return json_format.Parse(
        json.dumps(_hex_ids_to_base64(json.loads(payload))), ExportTraceServiceRequest()
    )


def _assert_same_as_official(spans: list[Any]):
    ours = _parse(encode_spans(spans))
    official = official_encode_spans(spans)
    # Compared as dicts so that a failure shows which field differs.
    assert json_format.MessageToDict(ours) == json_format.MessageToDict(official)


def _span(tracer: trace.Tracer, **kwargs: Any) -> Any:
    span = tracer.start_span('span', **kwargs)
    span.end()
    return span


# ── properties ──────────────────────────────────────────────────────────────


@given(_spans())
def test_encoding_matches_the_official_encoder(spans: list[ReadableSpan]):
    _assert_same_as_official(spans)


# ── known differences ───────────────────────────────────────────────────────


@pytest.mark.xfail(strict=True, reason='traceState is never sent')
def test_trace_state():
    tracer = TracerProvider().get_tracer('test')
    parent = SpanContext(
        trace_id=1,
        span_id=2,
        is_remote=True,
        trace_flags=TraceFlags(1),
        trace_state=TraceState([('vendor', 'value')]),
    )
    context = trace.set_span_in_context(trace.NonRecordingSpan(parent))
    _assert_same_as_official([_span(tracer, context=context)])


@pytest.mark.xfail(strict=True, reason='the resource schemaUrl is never sent')
def test_resource_schema_url():
    resource = Resource({'a': 'b'}, schema_url='https://opentelemetry.io/schemas/1.21.0')
    tracer = TracerProvider(resource=resource).get_tracer('test')
    _assert_same_as_official([_span(tracer)])


@pytest.mark.xfail(strict=True, reason='the scope schemaUrl is never sent')
def test_scope_schema_url():
    tracer = TracerProvider().get_tracer(
        'test', schema_url='https://opentelemetry.io/schemas/1.21.0'
    )
    _assert_same_as_official([_span(tracer)])


@pytest.mark.xfail(strict=True, reason='scope attributes are never sent')
def test_scope_attributes():
    tracer = TracerProvider().get_tracer('test', attributes={'a': 'b'})
    _assert_same_as_official([_span(tracer)])


@pytest.mark.xfail(
    strict=True,
    reason='an integer outside int64 makes the whole payload fail to parse, '
    'where the official encoder drops only that attribute',
)
@pytest.mark.parametrize('value', [_INT64_MAX + 1, _INT64_MIN - 1])
def test_out_of_range_int_attribute(value: int):
    tracer = TracerProvider().get_tracer('test')
    _assert_same_as_official([_span(tracer, attributes={'big': value, 'small': 1})])


@pytest.mark.xfail(
    strict=True,
    reason='a float that is not finite is written as a bare Infinity, -Infinity or NaN, '
    'which is not JSON, so the whole payload fails to parse',
)
@pytest.mark.parametrize('value', [float('inf'), float('-inf'), float('nan')])
def test_non_finite_float_attribute(value: float):
    tracer = TracerProvider().get_tracer('test')
    span = _span(tracer, attributes={'x': value})
    # NaN never equals itself, so this checks the parse rather than comparing.
    _parse(encode_spans([span]))


@pytest.mark.xfail(strict=True, reason='span links are never sent')
def test_links():
    tracer = TracerProvider().get_tracer('test')
    link = Link(SpanContext(trace_id=1, span_id=2, is_remote=True), {'a': 'b'})
    _assert_same_as_official([_span(tracer, links=[link])])
