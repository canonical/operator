# Copyright 2025 Canonical Ltd.
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
"""FIXME dummy docstring."""

from __future__ import annotations

import logging

import opentelemetry.trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

# The default ProxyTracer allows tracers to be declared ahead of time like loggers
logger = logging.getLogger(__name__)
tracer = opentelemetry.trace.get_tracer(__name__)

# 1. Create a tracer provider with a "service.name" resource attribute
opentelemetry.trace.set_tracer_provider(
    TracerProvider(resource=Resource.create({'service.name': 'example-service'}))
)

# 2. Configure the OTLP HTTP exporter (defaults to protobuf format)
otlp_exporter = OTLPSpanExporter(
    endpoint='http://localhost:4318/v1/traces'
    # If you needed headers or auth, you could add them like:
    # headers={"Authorization": "Bearer <TOKEN>"},
)

# 3. Create a span processor (BatchSpanProcessor recommended for production)
span_processor = BatchSpanProcessor(otlp_exporter)
opentelemetry.trace.get_tracer_provider().add_span_processor(span_processor)  # type: ignore


@tracer.start_as_current_span('some label')  # type: ignore
def main(foo: int = 42):
    """Do something."""
    # can't add attributes to a decorator, if needed use the below instead
    #
    # with tracer.start_as_current_span("some label") as span:
    #     span.set_attribute('foo', 'bar')
    #     span.add_event('sample_event', {'event_attr': 123})

    logger.info('Span created and will be exported to the collector soon!')


if __name__ == '__main__':
    logging.basicConfig(level='INFO')
    main()
    # from typing_extensions import reveal_type
    # reveal_type(main)
