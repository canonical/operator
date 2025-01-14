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
"""OTLP exporter for the ops-tracing extension."""

from __future__ import annotations

import contextlib
import logging
import ssl
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Sequence

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

import ops.log

from .buffer import Buffer
from .const import EXPORT_TIMEOUT, SENDOUT_FACTOR
from .vendor import otlp_json

logger = logging.getLogger(__name__)


# NOTE: OTEL SDK suppresses errors while exporting data
# FIXME: decide if we need to remove this before going to prod
logger.addHandler(logging.StreamHandler())


class BufferingSpanExporter(SpanExporter):
    """Buffers and sends out tracing data."""

    cache: dict[str | None, ssl.SSLContext]

    def __init__(self, buffer_path: Path | str):
        self.buffer = Buffer(buffer_path)
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
        """Create an SSL context with our CA list and settings."""
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
        config = self.buffer.get_destination()
        if not config.url:
            return

        assert config.url.startswith(('http://', 'https://'))
        context = self.ssl_context(config.ca) if config.url.startswith('https://') else None

        try:
            with urllib.request.urlopen(  # noqa: S310
                urllib.request.Request(  # noqa: S310
                    config.url,
                    data=data,
                    headers={'Content-Type': mime},
                    method='POST',
                ),
                context=context,
                timeout=EXPORT_TIMEOUT,
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
    """Disable the Juju log handler."""
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
