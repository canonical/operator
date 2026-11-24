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
catches output that a protobuf receiver would reject. The parsed request is
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
from opentelemetry.exporter.otlp.proto.common import trace_encoder
from opentelemetry.proto.collector.trace.v1 import trace_service_pb2
from opentelemetry.sdk import resources
from opentelemetry.sdk import trace as sdk_trace
from opentelemetry.sdk.trace import id_generator
from ops_tracing import _otlp_json

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
    st.just(trace.Status(trace.StatusCode.UNSET)),
    st.just(trace.Status(trace.StatusCode.OK)),
    st.builds(trace.Status, st.just(trace.StatusCode.ERROR), st.text(max_size=20)),
)
# A remote parent, as from an incoming request. Trace state is a known
# difference (test_trace_state), so there is none here.
_remote_parents = st.builds(
    trace.SpanContext,
    trace_id=_trace_ids,
    span_id=_span_ids,
    is_remote=st.just(True),
    trace_flags=st.just(trace.TraceFlags(1)),
)


class _DrawnIds(id_generator.IdGenerator):
    """Trace and span IDs drawn by Hypothesis, rather than with ``random``."""

    def __init__(self, draw: st.DrawFn):
        self._draw = draw

    def generate_span_id(self) -> int:
        return self._draw(_span_ids)

    def generate_trace_id(self) -> int:
        return self._draw(_trace_ids)


@st.composite
def _spans(draw: st.DrawFn) -> list[sdk_trace.ReadableSpan]:
    """Spans from one or two providers and a few tracers, some of them children of earlier ones.

    The spans have no links, which are a known difference (test_links).
    """
    tracers: list[trace.Tracer] = []
    for _ in range(draw(st.integers(1, 2))):
        provider = sdk_trace.TracerProvider(
            resource=resources.Resource(draw(_attributes)), id_generator=_DrawnIds(draw)
        )
        for _ in range(draw(st.integers(1, 2))):
            tracers.append(provider.get_tracer(draw(_names), draw(st.none() | _names)))
    spans: list[Any] = []
    for _ in range(draw(st.integers(1, 4))):
        tracer = draw(st.sampled_from(tracers))
        parent = draw(st.none() | st.sampled_from(spans)) if spans else None
        if parent is None and draw(st.booleans()):
            parent = trace.NonRecordingSpan(draw(_remote_parents))
        start = draw(_times)
        span = tracer.start_span(
            draw(_names),
            context=trace.set_span_in_context(parent) if parent is not None else None,
            kind=draw(st.sampled_from(trace.SpanKind)),
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
# The low byte of a span's flags holds the W3C trace flags, which OTLP specifies
# (SPAN_FLAGS_TRACE_FLAGS_MASK) and the official Python encoder leaves out.
_TRACE_FLAGS_MASK = 0xFF


def _hex_ids_to_base64(value: Any) -> Any:
    """Turn OTLP/JSON's hex IDs into the base64 that protobuf's JSON mapping uses.

    OTLP/JSON differs from the standard protobuf JSON mapping here: trace and
    span IDs are hex strings, not base64, so a receiver converts them before
    parsing (https://opentelemetry.io/docs/specs/otlp/#json-protobuf-encoding).
    ``json_format.Parse`` decodes bytes fields as URL-safe base64.
    """
    if isinstance(value, list):
        return [_hex_ids_to_base64(item) for item in cast('list[Any]', value)]
    if isinstance(value, dict):
        converted: dict[str, Any] = {}
        for key, item in cast('dict[str, Any]', value).items():
            if key in _ID_FIELDS and isinstance(item, str) and item:
                converted[key] = base64.urlsafe_b64encode(bytes.fromhex(item)).decode()
            else:
                converted[key] = _hex_ids_to_base64(item)
        return converted
    return value


def _parse(payload: bytes) -> trace_service_pb2.ExportTraceServiceRequest:
    """Parse an OTLP/JSON payload as a protobuf receiver would."""
    return json_format.Parse(
        json.dumps(_hex_ids_to_base64(json.loads(payload))),
        trace_service_pb2.ExportTraceServiceRequest(),
    )


def _comparable(request: trace_service_pb2.ExportTraceServiceRequest) -> dict[str, Any]:
    """The request as a dict, in an order and with flags that both encoders agree on.

    Our encoder sorts resources and scopes, and the official one keeps them in
    the order it meets them, so both are sorted here. The trace flags in the low
    byte of ``flags`` are masked out (see ``_TRACE_FLAGS_MASK``).
    """
    data = json_format.MessageToDict(request)
    resource_spans = cast('list[dict[str, Any]]', data.get('resourceSpans', []))
    for resource_span in resource_spans:
        scope_spans = cast('list[dict[str, Any]]', resource_span.get('scopeSpans', []))
        for scope_span in scope_spans:
            for span in cast('list[dict[str, Any]]', scope_span.get('spans', [])):
                if 'flags' in span:
                    span['flags'] = int(span['flags']) & ~_TRACE_FLAGS_MASK
                    if not span['flags']:
                        del span['flags']
        scope_spans.sort(key=lambda item: json.dumps(item.get('scope', {}), sort_keys=True))
    resource_spans.sort(key=lambda item: json.dumps(item.get('resource', {}), sort_keys=True))
    return data


def _assert_same_as_official(spans: list[Any]):
    ours = _parse(_otlp_json.encode_spans(spans))
    official = trace_encoder.encode_spans(spans)
    # Compared as dicts so that a failure shows which field differs.
    assert _comparable(ours) == _comparable(official)


def _span(tracer: trace.Tracer, **kwargs: Any) -> Any:
    span = tracer.start_span('span', **kwargs)
    span.end()
    return span


# ── properties ──────────────────────────────────────────────────────────────


@given(_spans())
def test_encoding_matches_the_official_encoder(spans: list[sdk_trace.ReadableSpan]):
    _assert_same_as_official(spans)


# ── known differences ───────────────────────────────────────────────────────


@pytest.mark.xfail(strict=True, raises=AssertionError, reason='traceState is never sent')
def test_trace_state():
    tracer = sdk_trace.TracerProvider().get_tracer('test')
    parent = trace.SpanContext(
        trace_id=1,
        span_id=2,
        is_remote=True,
        trace_flags=trace.TraceFlags(1),
        trace_state=trace.TraceState([('vendor', 'value')]),
    )
    context = trace.set_span_in_context(trace.NonRecordingSpan(parent))
    _assert_same_as_official([_span(tracer, context=context)])


@pytest.mark.xfail(
    strict=True, raises=AssertionError, reason='the resource schemaUrl is never sent'
)
def test_resource_schema_url():
    resource = resources.Resource({'a': 'b'}, schema_url='https://opentelemetry.io/schemas/1.21.0')
    tracer = sdk_trace.TracerProvider(resource=resource).get_tracer('test')
    _assert_same_as_official([_span(tracer)])


@pytest.mark.xfail(strict=True, raises=AssertionError, reason='the scope schemaUrl is never sent')
def test_scope_schema_url():
    tracer = sdk_trace.TracerProvider().get_tracer(
        'test', schema_url='https://opentelemetry.io/schemas/1.21.0'
    )
    _assert_same_as_official([_span(tracer)])


@pytest.mark.xfail(strict=True, raises=AssertionError, reason='scope attributes are never sent')
def test_scope_attributes():
    tracer = sdk_trace.TracerProvider().get_tracer('test', attributes={'a': 'b'})
    _assert_same_as_official([_span(tracer)])


@pytest.mark.xfail(
    strict=True,
    raises=json_format.ParseError,
    reason='an integer outside int64 makes the whole payload fail to parse, '
    'where the official encoder drops only that attribute',
)
@pytest.mark.parametrize('value', [_INT64_MAX + 1, _INT64_MIN - 1])
def test_out_of_range_int_attribute(value: int):
    tracer = sdk_trace.TracerProvider().get_tracer('test')
    span = _span(tracer, attributes={'big': value, 'small': 1})
    # Not compared with the official encoder: we count an attribute we can't
    # encode in droppedAttributesCount, and the official encoder doesn't.
    request = _parse(_otlp_json.encode_spans([span]))
    (encoded,) = request.resource_spans[0].scope_spans[0].spans
    assert [attribute.key for attribute in encoded.attributes] == ['small']


@pytest.mark.xfail(
    strict=True,
    raises=json_format.ParseError,
    reason='a float that is not finite is written as a bare Infinity, -Infinity or NaN, '
    'which is not JSON, so the whole payload fails to parse',
)
@pytest.mark.parametrize('value', [float('inf'), float('-inf'), float('nan')])
def test_non_finite_float_attribute(value: float):
    tracer = sdk_trace.TracerProvider().get_tracer('test')
    # MessageToDict writes these as the strings 'NaN' and 'Infinity', so the
    # comparison works even for NaN.
    _assert_same_as_official([_span(tracer, attributes={'x': value})])


@pytest.mark.xfail(strict=True, raises=AssertionError, reason='span links are never sent')
def test_links():
    tracer = sdk_trace.TracerProvider().get_tracer('test')
    link = trace.Link(trace.SpanContext(trace_id=1, span_id=2, is_remote=True), {'a': 'b'})
    _assert_same_as_official([_span(tracer, links=[link])])
