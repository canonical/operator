# Copyright 2025 Canonical Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this
# file except in compliance with the License. You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software distributed under
# the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF
# ANY KIND, either express or implied. See the License for the specific language
# governing permissions and limitations under the License.

"""Mock implementations for testing."""

from __future__ import annotations

import contextlib
import pathlib
from typing import Generator

import opentelemetry.trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from . import _backend

# A global SPAN_PROCESSOR that will be captured by every tracer object
# (ops._private.tracer, charm.tracer, lib.charms.foo.tracer) on first use.
# The dummy argument is mandatory and will be overridden in patch_tracing().
SPAN_PROCESSOR = SimpleSpanProcessor(InMemorySpanExporter())


@contextlib.contextmanager
def patch_tracing() -> Generator[InMemorySpanExporter, None, None]:
    """Patch ops[tracing] for unit tests.

    Replaces the real buffer and exporter with an in-memory store.
    This effectively removes the requirement for unique directories for each unit test.
    """
    # Work around OpenTelemetry tracer provider singleton enforcement.
    real_otel_provider = opentelemetry.trace._TRACER_PROVIDER
    real_otel_once_done = opentelemetry.trace._TRACER_PROVIDER_SET_ONCE._done
    real_create_provider = _backend._create_provider
    real_exporter = _backend._exporter
    dummy_exporter = SPAN_PROCESSOR.span_exporter

    # An exporter that accumulates trace data from one Scenario context.run().
    exporter = InMemorySpanExporter()
    SPAN_PROCESSOR.span_exporter = exporter

    _backend._create_provider = _create_provider
    _backend._exporter = None
    try:
        yield exporter
    finally:
        SPAN_PROCESSOR.span_exporter = dummy_exporter
        _backend._exporter = real_exporter
        _backend._create_provider = real_create_provider
        opentelemetry.trace._TRACER_PROVIDER = real_otel_provider
        opentelemetry.trace._TRACER_PROVIDER_SET_ONCE._done = real_otel_once_done


def _create_provider(resource: Resource, charm_dir: pathlib.Path) -> TracerProvider:
    """Create an OpenTelemetry tracing provider suitable for testing."""
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(SPAN_PROCESSOR)
    return provider
