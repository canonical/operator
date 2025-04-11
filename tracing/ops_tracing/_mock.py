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


@contextlib.contextmanager
def patch_tracing() -> Generator[None, None, None]:
    """Patch ops[tracing] for unit tests.

    Replaces the real buffer and exporter with an in-memory store.
    This effectively removes the requirement for unique directories for each unit test.
    """
    # OTEL tries hard to prevent tracing provider from being set twice
    real_otel_provider = opentelemetry.trace._TRACER_PROVIDER
    real_otel_once_done = opentelemetry.trace._TRACER_PROVIDER_SET_ONCE._done
    real_create_provider = _backend._create_provider
    _backend._create_provider = _create_provider
    try:
        yield
    finally:
        _backend._create_provider = real_create_provider
        opentelemetry.trace._TRACER_PROVIDER = real_otel_provider
        opentelemetry.trace._TRACER_PROVIDER_SET_ONCE._done = real_otel_once_done


def _create_provider(resource: Resource, charm_dir: pathlib.Path) -> TracerProvider:
    """Create an OpenTelemetry tracing provider suitable for testing."""
    return TracerProvider(
        resource=resource,
        active_span_processor=SimpleSpanProcessor(InMemorySpanExporter()),  # type: ignore
    )
