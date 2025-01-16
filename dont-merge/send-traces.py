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
from __future__ import annotations

import opentelemetry.trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

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
opentelemetry.trace.get_tracer_provider().add_span_processor(span_processor)

# 4. Acquire a tracer
tracer = opentelemetry.trace.get_tracer(__name__)


def main():
    # 5. Start a span, do something, then end the span
    with tracer.start_as_current_span('example_span') as span:
        span.set_attribute('foo', 'bar')
        span.add_event('sample_event', {'event_attr': 123})
        print('Span created and exported to the collector!')


if __name__ == '__main__':
    main()
