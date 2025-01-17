# Copyright 2022 Canonical Ltd.
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
"""FIXME Docstring."""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Callable, Sequence, Type

from opentelemetry.exporter.otlp.proto.common._internal.trace_encoder import (
    encode_spans,
)
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.trace import get_tracer_provider, set_tracer_provider

import ops
import ops.jujucontext
import ops.tracing._buffer

logger = logging.getLogger(__name__)

_OTLP_SPAN_EXPORTER_TIMEOUT = 1  # seconds
"""How much to give OTLP span exporter has to push traces to the backend."""


class ProxySpanExporter(SpanExporter):
    real_exporter: SpanExporter | None
    buffer: ops.tracing._buffer.Buffer

    def __init__(self):
        self.real_exporter = None
        self.buffer = ops.tracing._buffer.Buffer()

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        """Export a batch of telemetry data."""
        # Note:
        # this is called in a helper thread, which is daemonic,
        # the MainThread will wait at most 10s for this thread.
        # Margins:
        # - 1s safety margin
        # - 1s for buffered data time overhang
        # - 2s for live data
        deadline = time.monotonic() + 6

        # __import__("pdb").set_trace()
        import threading

        print('Ex' * 20 + str(threading.current_thread()))

        if self.real_exporter:
            buffered = self.buffer.load()
            print(f'{len(buffered)=}')
            for chunk in buffered:
                if time.monotonic() > deadline:
                    break
                if not self.real_exporter._export(chunk).ok:  # type: ignore
                    break
            else:
                self.buffer.drop()

        # Note: [] --> b''
        data: bytes = encode_spans(spans).SerializePartialToString()
        print(f'{len(data)=} {len(spans)=}')

        sent = False
        if self.real_exporter and time.monotonic() < deadline:
            sent = self.real_exporter.export(spans) == SpanExportResult.SUCCESS
            print(f'{sent=}')

        # FIXME a couple of strategies are possible, but all thave downsides:
        #
        # Send buffered first, then send live data or buffer it
        # - what if there's too much live data, and we're killed?
        #
        # Send some buffered data, then send live data or buffer it
        # - what to do with remaining buffered data?
        #
        # Buffer new data first, then send as much as possible
        # - what to do with remaining buffered data?
        #
        # What to do with remaining buffered data?
        # - on partial send, rewriting the file:
        #   it's expensive...
        #
        # - leave data in the buffer on partial send:
        #   erase is cheap
        #   re-sending traces is allowed in OTEL
        #   However..
        #   if there's a lot of data / receiver is slow,
        #   we'll end up with a grwoing buffer
        #   until such time that buffer is full and is reset
        if not sent:
            self.buffer.append(data)

        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        """Shut down the exporter."""
        if self.real_exporter:
            self.real_exporter.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        """No-op, as the real exporter doesn't buffer."""
        return True

    def set_real_exporter(self, exporter: SpanExporter) -> None:
        self.real_exporter = exporter


def get_server_cert(
    server_cert_attr: str,
    charm_instance: ops.CharmBase,
    charm_type: Type[ops.CharmBase],
) -> str | Path | None:
    _server_cert: str | Path | None | Callable[[], str | Path | None] = getattr(
        charm_instance, server_cert_attr
    )
    server_cert = _server_cert() if callable(_server_cert) else _server_cert

    if server_cert is None:
        logger.warning(
            f'{charm_type}.{server_cert_attr} is None; sending traces over INSECURE connection.'
        )
        return
    elif not Path(server_cert).is_absolute():
        raise ValueError(
            f'{charm_type}.{server_cert_attr} should resolve to a valid '
            f'tls cert absolute path (string | Path)); '
            f'got {server_cert} instead.'
        )
    return server_cert


def setup_tracing(charm_class_name: str) -> None:
    # FIXME would it be better to pass Juju context explicitly?
    juju_context = ops.jujucontext._JujuContext.from_dict(os.environ)
    app_name = '' if juju_context.unit_name is None else juju_context.unit_name.split('/')[0]
    service_name = f'{app_name}-charm'  # only one COS charm sets custom value

    resource = Resource.create(
        attributes={
            'service.name': service_name,
            'compose_service': service_name,  # FIXME why is this copy needed?
            'charm_type': charm_class_name,
            # juju topology
            'juju_unit': juju_context.unit_name,
            'juju_application': app_name,
            'juju_model': juju_context.model_name,
            'juju_model_uuid': juju_context.model_uuid,
        }
    )
    provider = TracerProvider(resource=resource)

    exporter = ProxySpanExporter()

    # real exporter, hardcoded for now
    real_exporter = OTLPSpanExporter(endpoint='http://localhost:4318/v1/traces', timeout=1)
    # This is actually the max delay value in the sequence 1, 2, ..., MAX
    # Set to 1 to disable sending live data (buffered data is still eventually sent)
    # Set to 2 (or more) to enable sending live data (after buffered)
    #
    # _MAX_RETRY_TIMEOUT = 2 with timeout=1 means:
    # - 1 attempt to send live, 1s sleep in the worst case
    # _MAX_RETRY_TIMEOUT = 3 or 4 with timeout=1 means:
    # - 1st attempt, 1s sleep, 2nd attempt, 1s sleep in the worst case
    real_exporter._MAX_RETRY_TIMEOUT = 2  # type: ignore
    exporter.set_real_exporter(real_exporter)

    # How

    span_processor = BatchSpanProcessor(exporter)
    provider.add_span_processor(span_processor)
    print('St' * 50)
    set_tracer_provider(provider)


def shutdown_tracing() -> None:
    """Shutdown tracing, which typically flushes data out."""
    print('Sh' * 50)
    get_tracer_provider().shutdown()  # type: ignore
