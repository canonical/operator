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
"""The global implementation of the ops-tracing extension."""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING, Generator

from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import get_current_span, get_tracer_provider, set_tracer_provider

if TYPE_CHECKING:
    from ops.jujucontext import _JujuContext

from ._const import BUFFER_FILE, Config
from ._export import BufferingSpanExporter

_exporter: BufferingSpanExporter | None = None


class LogsToEvents(logging.Handler):
    """An adaptor that convert log records to OTEL events."""

    def emit(self, record: logging.LogRecord) -> None:
        """Emit this log record as OTEL event."""
        span = get_current_span()
        if span and span.is_recording():
            try:
                message = record.getMessage()
                level = record.levelname
            except Exception as e:
                # This should never happen, except if the charm includes custom logging
                # library like structlog that enriches both the format and record attributes,
                # or if the record format doesn't match the arguments.
                message = f'log {record=} error {e}'
                level = 'UNKNOWN'
            span.add_event(message, {'level': level})


@contextlib.contextmanager
def _setup(juju_context: _JujuContext, charm_class_name: str) -> Generator[None, None, None]:
    """Control tracing lifespan of tracing.

    Args:
        juju_context: the context for this dispatch, for annotation
        charm_class_name: the name of the charm class, for annotation
    """
    global _exporter
    app_name, unit_number = juju_context.unit_name.split('/', 1)
    # NOTE: Resource is immutable, and we want to start tracing early.
    # This means that charmhub charm name (self.meta.name) is not available yet.
    resource = Resource.create(
        attributes={
            'service.namespace': juju_context.model_uuid,
            'service.namespace.name': juju_context.model_name,
            'service.name': app_name,
            'service.instance.id': unit_number,
            'service.charm': charm_class_name,
        }
    )
    provider = TracerProvider(resource=resource)
    _exporter = BufferingSpanExporter(juju_context.charm_dir / BUFFER_FILE)
    span_processor = BatchSpanProcessor(_exporter)
    provider.add_span_processor(span_processor)
    set_tracer_provider(provider)
    if not any(isinstance(h, LogsToEvents) for h in logging.root.handlers):
        logging.root.addHandler(LogsToEvents())
    try:
        yield
    finally:
        shutdown_tracing()


def set_destination(url: str | None, ca: str | None) -> None:
    """Configure the destination service for tracing data.

    Args:
        url: the URL of the telemetry service to send tracing data to
        ca: the CA list (PEM bundle, a multi-line string), only used for HTTPS URLs.

    """
    if url and not url.startswith(('http://', 'https://')):
        raise ValueError('Only HTTP and HTTPS tracing destinations are supported.')

    config = Config(url, ca)

    if not _exporter:
        return

    if config == _exporter.buffer.get_destination():
        return
    _exporter.buffer.set_destination(config)


def _mark_observed() -> None:
    """Mark the tracing data collected in this dispatch as higher priority."""
    if not _exporter:
        return
    _exporter.buffer.mark_observed()


def shutdown_tracing() -> None:
    """Shutdown tracing, which is expected to flush the buffered data out."""
    get_tracer_provider().shutdown()  # type: ignore
