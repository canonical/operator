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

import contextlib
import logging
import os
import pathlib
import time
from typing import Callable, Sequence, Type

from opentelemetry.exporter.otlp.proto.common._internal import trace_encoder
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.sqlite3 import SQLite3Instrumentor  # type: ignore
from opentelemetry.instrumentation.urllib import URLLibInstrumentor  # type: ignore
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.trace import get_tracer_provider, set_tracer_provider

import ops
import ops.jujucontext
import ops.log
from ops.tracing import _buffer

logger = logging.getLogger(__name__)
# Trace `sqlite3` usage by ops storage component
SQLite3Instrumentor().instrument()
# Trace `urllib` usage when talking to Pebble
URLLibInstrumentor().instrument()

_OTLP_SPAN_EXPORTER_TIMEOUT = 1  # seconds
"""How much to give OTLP span exporter has to push traces to the backend."""

SENDOUT_FACTOR = 2
"""How much buffered chunks to send out for each incoming chunk."""

# FIXME: this creates a separate file next to the CHARM_STATE_FILE
# We could stuff both kinds of data into the same file, I guess?
BUFFER_FILE = '.tracing-buffer.db'


_exporter: ProxySpanExporter | None = None


class ProxySpanExporter(SpanExporter):
    real_exporter: SpanExporter | None
    buffer: _buffer.Buffer

    def __init__(self, buffer_path: str):
        self.real_exporter = None
        # FIXME side-by-side with deferred events db
        # or in the same file as deferred events db?
        self.buffer = _buffer.Buffer(buffer_path)

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        """Export a batch of telemetry data.

        Note: to avoid data loops or recursion, this function cannot be instrumented.
        """
        print(f'export {len(spans)=}')
        with suppress_juju_log_handler():
            # Note:
            # this is called in a helper thread, which is daemonic,
            # the MainThread will wait at most 10s for this thread.
            # Margins:
            # - 1s safety margin
            # - 1s for buffered data time overhang
            # - 2s for live data
            deadline = time.monotonic() + 6

            # TODO check if we're ever called with no spans.
            assert spans
            # Note: [] --> b''
            data: bytes = trace_encoder.encode_spans(spans).SerializePartialToString()
            rv = self.buffer.pump(data)
            print('saved')
            assert rv
            self.do_export(*rv)

            for _ in range(SENDOUT_FACTOR - 1):
                if time.monotonic() > deadline:
                    break
                rv = self.buffer.pump()
                if rv:
                    self.do_export(*rv)

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

            return SpanExportResult.SUCCESS

    def do_export(self, buffered_id: int, data: bytes) -> None:
        """Export buffered data and remove it from the buffer on success."""
        print(f'asked {buffered_id=} {len(data)=}')
        if self.real_exporter and self.real_exporter._export(data).ok:  # type: ignore
            print('removing')
            self.buffer.remove(buffered_id)

    def shutdown(self) -> None:
        """Shut down the exporter."""
        if self.real_exporter:
            self.real_exporter.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        """No-op, as the real exporter doesn't buffer."""
        return True

    def set_real_exporter(self, exporter: SpanExporter) -> None:
        self.real_exporter = exporter


@contextlib.contextmanager
def suppress_juju_log_handler():
    handlers = [h for h in logging.root.handlers if isinstance(h, ops.log.JujuLogHandler)]
    if not handlers:
        yield
        return

    juju_log_handler = handlers[0]
    token = juju_log_handler.drop.set(True)
    try:
        yield
    finally:
        juju_log_handler.drop.reset(token)


# FIXME move to configure_tracing_destination
def get_server_cert(
    server_cert_attr: str,
    charm_instance: ops.CharmBase,
    charm_type: Type[ops.CharmBase],
) -> str | pathlib.Path | None:
    _server_cert: str | pathlib.Path | None | Callable[[], str | pathlib.Path | None] = getattr(
        charm_instance, server_cert_attr
    )
    server_cert = _server_cert() if callable(_server_cert) else _server_cert

    if server_cert is None:
        logger.warning(
            f'{charm_type}.{server_cert_attr} is None; sending traces over INSECURE connection.'
        )
        return
    elif not pathlib.Path(server_cert).is_absolute():
        raise ValueError(
            f'{charm_type}.{server_cert_attr} should resolve to a valid '
            f'tls cert absolute path (string | pathlib.Path)); '
            f'got {server_cert} instead.'
        )
    return server_cert


def setup_tracing(charm_class_name: str) -> None:
    global _exporter
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

    # How

    buffer_path = str(juju_context.charm_dir / BUFFER_FILE)
    _exporter = ProxySpanExporter(buffer_path)
    span_processor = BatchSpanProcessor(_exporter)
    provider.add_span_processor(span_processor)
    print('St' * 50)
    set_tracer_provider(provider)


# FIXME make it very cheap to call this method a second time with same arguments
def configure_tracing_buffer(buffer_path: str) -> None:
    # FIXME needs a threading.Lock
    # - check _exporter.buffer.path vs new path, do nothing if they are same
    # - create the new buffer (may be empty or may have data on disk)
    # - read out chunks from the current buffer (this data is typically newer)
    # - append to the new buffer (possibly flushing out some older records)
    if not _exporter:
        return
    _exporter.buffer.pivot(buffer_path)  # FIXME


# FIXME make it very cheap to call this method a second time with same arguments
def configure_tracing_destination(url: str) -> None:
    # FIXME needs a threading.Lock
    # or access to underlying BatchXXX lock
    #
    # - check if settings are exactly same, do nothing in that case
    # - replace current exported with a new exporter
    if not _exporter:
        return

    # real exporter, hardcoded for now
    real_exporter = OTLPSpanExporter(url, timeout=1)
    # This is actually the max delay value in the sequence 1, 2, ..., MAX
    # Set to 1 to disable sending live data (buffered data is still eventually sent)
    # Set to 2 (or more) to enable sending live data (after buffered)
    #
    # _MAX_RETRY_TIMEOUT = 2 with timeout=1 means:
    # - 1 attempt to send live, 1s sleep in the worst case
    # _MAX_RETRY_TIMEOUT = 3 or 4 with timeout=1 means:
    # - 1st attempt, 1s sleep, 2nd attempt, 1s sleep in the worst case
    real_exporter._MAX_RETRY_TIMEOUT = 2  # type: ignore
    _exporter.set_real_exporter(real_exporter)


def shutdown_tracing() -> None:
    """Shutdown tracing, which typically flushes data out."""
    print('Sh' * 50)
    get_tracer_provider().shutdown()  # type: ignore
