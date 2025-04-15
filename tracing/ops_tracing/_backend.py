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

import pathlib
from typing import TYPE_CHECKING

from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import get_tracer_provider, set_tracer_provider

if TYPE_CHECKING:
    from ops.jujucontext import _JujuContext

from ._buffer import Destination
from ._export import BufferingSpanExporter

BUFFER_FILENAME: str = '.tracing-data.db'
"""Name of the buffer file where the trace data is stored, next to .unit-state.db."""


def setup(juju_context: _JujuContext, charm_class_name: str) -> None:
    """Set up the tracing subsystem and configure OpenTelemetry.

    Args:
        juju_context: the context for this dispatch, for annotation
        charm_class_name: the name of the charm class, for annotation
    """
    app_name, unit_number = juju_context.unit_name.split('/', 1)
    # Note that the Resource is immutable, and we want to start tracing early.
    # This means that the Charmhub charm name (self.meta.name) is not available yet.
    resource = Resource.create(
        attributes={
            'service.namespace': juju_context.model_uuid,
            'service.namespace.name': juju_context.model_name,
            'service.name': app_name,
            'service.instance.id': unit_number,
            'service.charm': charm_class_name,
        }
    )
    set_tracer_provider(_create_provider(resource, juju_context.charm_dir))


def _create_provider(resource: Resource, charm_dir: pathlib.Path) -> TracerProvider:
    """Create the OpenTelemetry tracer provider."""
    # Separate function so that it's easy to override in tests
    exporter = BufferingSpanExporter(charm_dir / BUFFER_FILENAME)
    span_processor = BatchSpanProcessor(exporter)
    return TracerProvider(resource=resource, active_span_processor=span_processor)  # type: ignore


def get_exporter() -> BufferingSpanExporter | None:
    """Get our export from OpenTelemetry SDK."""
    try:
        exporter = get_tracer_provider()._active_span_processor.span_exporter  # type: ignore
    except AttributeError:
        # The global tracer provider was not configured by us and has a wrong processor.
        return None
    if not exporter or not isinstance(exporter, BufferingSpanExporter):
        return None
    return exporter


def set_destination(url: str | None, ca: str | None) -> None:
    """Configure the destination service for trace data.

    Args:
        url: the URL of the telemetry service to send trace data to.
            An example could be ``http://localhost/v1/traces``.
            None or empty string disables sending out the data, which is still buffered.
        ca: the CA list (PEM bundle, a multi-line string), only used for HTTPS URLs.
    """
    if url and not url.startswith(('http://', 'https://')):
        raise ValueError('Only HTTP and HTTPS tracing destinations are supported.')

    config = Destination(url, ca)

    if not (exporter := get_exporter()):
        # Perhaps our tracer provider was never set up.
        return

    if config == exporter.buffer.load_destination():
        return
    exporter.buffer.save_destination(config)


def mark_observed() -> None:
    """Mark the trace data collected in this dispatch as higher priority."""
    if not (exporter := get_exporter()):
        return
    exporter.buffer.mark_observed()


def shutdown() -> None:
    """Shutdown tracing, which is expected to flush the buffered data out."""
    provider = get_tracer_provider()
    if isinstance(provider, TracerProvider):
        provider.shutdown()
