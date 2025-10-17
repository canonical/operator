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
from ops._private import yaml

if TYPE_CHECKING:
    from ops import JujuContext

from ._buffer import Destination
from ._export import BufferingSpanExporter

BUFFER_FILENAME: str = '.tracing-data.db'
"""Name of the buffer file where the trace data is stored, next to .unit-state.db."""

_exporter: BufferingSpanExporter | None = None
"""A reference to the exporter that we passed to OpenTelemetry SDK at setup."""


def setup(juju_context: JujuContext, charm_class_name: str) -> None:
    """Set up the tracing subsystem and configure OpenTelemetry.

    Args:
        juju_context: the context for this dispatch, for annotation
        charm_class_name: the name of the charm class, for annotation
    """
    app_name, unit_number = juju_context.unit_name.split('/', 1)
    try:
        meta = yaml.safe_load((juju_context.charm_dir / 'metadata.yaml').read_text())
        charmhub_charm_name = meta['name']
    except FileNotFoundError:
        charmhub_charm_name = '[unknown]'

    resource = Resource.create(
        attributes={
            'service.namespace': juju_context.model_uuid,
            'service.namespace.name': juju_context.model_name,
            'service.name': app_name,
            'service.instance.id': unit_number,
            'charm': charmhub_charm_name,
            'charm_type': charm_class_name,
            'juju_model': juju_context.model_name,
            'juju_model_uuid': juju_context.model_uuid,
            'juju_application': app_name,
            'juju_unit': juju_context.unit_name,
        }
    )
    set_tracer_provider(_create_provider(resource, juju_context.charm_dir))


def _create_provider(resource: Resource, charm_dir: pathlib.Path) -> TracerProvider:
    """Create the OpenTelemetry tracer provider."""
    # Separate function so that it's easy to override in tests
    global _exporter
    _exporter = BufferingSpanExporter(charm_dir / BUFFER_FILENAME)
    span_processor = BatchSpanProcessor(_exporter)
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(span_processor)
    return provider


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

    if not _exporter:
        # Perhaps our tracer provider was never set up.
        return

    if config == _exporter.buffer.load_destination():
        return
    _exporter.buffer.save_destination(config)


def mark_observed() -> None:
    """Mark the trace data collected in this dispatch as higher priority."""
    if not _exporter:
        return
    _exporter.buffer.mark_observed()


def shutdown() -> None:
    """Shutdown tracing, which is expected to flush the buffered data out."""
    provider = get_tracer_provider()
    if isinstance(provider, TracerProvider):
        provider.shutdown()
