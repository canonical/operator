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
import logging
import pathlib
from typing import Generator

from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from . import _backend


@contextlib.contextmanager
def patch_tracing() -> Generator[None, None, None]:
    real_create_provider = _backend._create_provider
    real_log_to_events = _backend.LogsToEvents
    _backend._create_provider = _create_provider
    _backend.LogsToEvents = LogsToEvents
    try:
        yield
    finally:
        _backend._create_provider = real_create_provider
        _backend.LogsToEvents = real_log_to_events


def _create_provider(resource: Resource, charm_dir: pathlib.Path) -> TracerProvider:
    """Create an OpenTelemetry tracing provider suitable for testing."""
    return TracerProvider(
        resource=resource,
        active_span_processor=SimpleSpanProcessor(InMemorySpanExporter()),  # type: ignore
    )


class LogsToEvents(_backend.LogsToEvents):
    """An mock adaptor that doesn't convert log records to OTEL events."""

    def emit(self, record: logging.LogRecord) -> None:
        pass


__all__ = ['_create_provider']
