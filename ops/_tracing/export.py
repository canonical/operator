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
import ssl
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Sequence

import otlp_json
from opentelemetry.instrumentation.urllib import URLLibInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.trace import get_tracer_provider, set_tracer_provider

import ops
import ops._tracing.buffer
import ops.jujucontext
import ops.log

# Trace `urllib` usage when talking to Pebble
URLLibInstrumentor().instrument()

# NOTE: nominally int, although float would work just as well in practice
EXPORTER_TIMEOUT: int = 1  # seconds
"""How much to give OTLP span exporter has to push traces to the backend."""

SENDOUT_FACTOR: int = 2
"""How many buffered chunks to send out for each incoming chunk."""

BUFFER_FILE: str = '.tracing-data.db'
"""Name of the file whither data is buffered, located next to .unit-state.db."""


logger = logging.getLogger(__name__)
_exporter: ProxySpanExporter | None = None


# NOTE: OTEL SDK suppresses errors while exporting data
# FIXME: decide if we need to remove this before going to prod
logger.addHandler(logging.StreamHandler())


class ProxySpanExporter(SpanExporter):
    settings: tuple[str | None, str | None] = (None, None)
    cache: dict[str | None, ssl.SSLContext]

    def __init__(self, buffer_path: Path | str):
        self.buffer = ops._tracing.buffer.Buffer(buffer_path)
        self.lock = threading.Lock()
        self.cache = {}

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        """Export a batch of telemetry data.

        Note: to avoid data loops or recursion, this function cannot be instrumented.
        """
        try:
            with suppress_juju_log_handler():
                # Note:
                # this is called in a helper thread, which is daemonic,
                # the MainThread will wait at most 10s for this thread.
                # Margins:
                # - 1s safety margin
                # - 1s for buffered data time overhang
                # - 2s for live data
                deadline = time.monotonic() + 6

                assert spans  # the BatchSpanProcessor won't call us if there's no data
                # TODO:  this will change in the JSON experiment
                # __import__("pdb").set_trace()
                # FIXME can't use stock exporter, must DIY

                rv = self.buffer.pump((otlp_json.encode_spans(spans), otlp_json.CONTENT_TYPE))
                assert rv
                self.do_export(*rv)

                for _ in range(SENDOUT_FACTOR - 1):
                    if time.monotonic() > deadline:
                        break
                    if not (rv := self.buffer.pump()):
                        break
                    self.do_export(*rv)

                return SpanExportResult.SUCCESS
        except Exception:
            # FIXME: I'm using this to catch bug during development.
            # OTEL must disable logging capture during export to avoid data loops.
            # At least during development, we want to catch and report pure bugs.
            # Perhaps this part needs to be removed before merge/release.
            # Leaving here for now to decide how to test this code path.
            logger.exception('export')
            raise

    def ssl_context(self, ca: str | None) -> ssl.SSLContext:
        if context := self.cache.get(ca):
            return context
        context = self._ssl_context(ca)
        self.cache.clear()
        self.cache[ca] = context
        return context

    def _ssl_context(self, ca: str | None) -> ssl.SSLContext:
        # NOTE: ssl.create_default_context() doesn't allow setting the context.protocol in a way
        # that's the same across Python 3.8 and 3.10 onwards. Whip the context up by hand.
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        context.set_alpn_protocols(['http/1.1'])
        context.verify_flags |= ssl.VERIFY_X509_STRICT
        if partial_chain := getattr(ssl, 'VERIFY_X509_PARTIAL_CHAIN', None):
            # Available starting from Python 3.10. The partial chain flag allows trusting the
            # intermediate CAs in the CA list without the matching root CA
            context.verify_flags |= partial_chain

        if ca is not None:
            context.load_verify_locations(cadata=ca)
        else:
            context.load_default_certs()

        return context

    def do_export(self, buffered_id: int, data: bytes, mime: str) -> None:
        """Export buffered data and remove it from the buffer on success."""
        url, ca = self.settings
        if not url:
            return

        # FIXME cache

        # FIXME: is this custom code worth it?
        # or would it be easier and safer to use `requests`?
        assert url.startswith(('http://', 'https://'))
        context = self.ssl_context(ca) if url.startswith('https://') else None

        try:
            with urllib.request.urlopen(  # noqa: S310
                urllib.request.Request(  # noqa: S310
                    url,
                    data=data,
                    headers={'Content-Type': mime},
                    method='POST',
                ),
                context=context,
            ):
                pass
        except urllib.error.HTTPError as e:
            # FIXME drop this later
            # - perhaps the collector is shot
            # - or there's a bug converting spans to JSON
            # if it's the latter, the response test/JSON is helpful
            resp = e.fp.read()
            print('FIXME', e.code, str(resp)[:1000])
        except OSError:
            # URLError, TimeoutError, SSLError, socket.error
            pass
        except Exception:
            logger.exception('Failed to send telemetry out')
        else:
            self.buffer.remove(buffered_id)

    def shutdown(self) -> None:
        """Shut down the exporter."""
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        """No-op, as the real exporter doesn't buffer."""
        return True


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


def setup_tracing(charm_class_name: str) -> None:
    global _exporter
    # FIXME would it be better to pass Juju context explicitly?
    juju_context = ops.jujucontext._JujuContext.from_dict(os.environ)
    # FIXME is it ever possible for unit_name to be unset (empty)?
    app_name, unit_number = juju_context.unit_name.split('/', 1)
    # FIXME we could get charmhub charm name from self.meta.name, but only later
    # when metadata.yaml file is parsed. I think that Resource is immutable,
    # so where can we smuggle that bit of info later? An Event perhaps?

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
    _exporter = ProxySpanExporter(juju_context.charm_dir / BUFFER_FILE)
    span_processor = BatchSpanProcessor(_exporter)
    provider.add_span_processor(span_processor)
    set_tracer_provider(provider)
    # FIXME: in testing with tracing, we need a hack.
    # OpenTelemetry disallows setting the tracer provider twice,
    # a warning is issued and new provider is ignored.
    #
    # For example, we could reset the resource instead:
    # get_tracer_provider()._resource = resource


def set_tracing_destination(
    *,
    url: str | None,
    ca: str | None = None,
) -> None:
    """Configure the destination service for tracing data.

    Args:
        url: The URL of the telemetry service to send tracing data to.
        ca: The PEM formatted CA list.
            Only in use if the URL is an HTTPS URL.
    """
    if not _exporter:
        return
    _exporter.settings = (url, ca)


def mark_observed() -> None:
    if not _exporter:
        return
    _exporter.buffer.mark_observed()


def shutdown_tracing() -> None:
    """Shutdown tracing, which is expected to flush the buffered data out."""
    get_tracer_provider().shutdown()  # type: ignore
