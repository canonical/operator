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

import logging
import pathlib
import ssl
import threading
import time
import urllib.error
import urllib.request
from typing import Sequence

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

from ._buffer import Buffer
from .vendor import otlp_json

EXPORT_TIMEOUT: int | float = 1  # seconds
"""How much time to give OTLP span exporter to push traces to the backend."""

SENDOUT_FACTOR: int = 10
"""How many buffered chunks to send out for each incoming chunk."""

logger = logging.getLogger(__name__)

# We should really be using TLSv1_3.
# However at least this deployment option doesn't support 1.3 yet
# https://github.com/canonical/tempo-coordinator-k8s-operator/issues/146
#
# Integration provider                   Requirer                           Interface
# s3-integrator:s3-credentials           tempo:s3                           s3
# s3-integrator:s3-integrator-peers      s3-integrator:s3-integrator-peers  s3-integrator-peers
# self-signed-certificates:certificates  tempo:certificates                 tls-certificates
# self-signed-certificates:send-ca-cert  tracing-tester:receive-ca-cert     certificate_transfer
# tempo:peers                            tempo:peers                        tempo_peers
# tempo:tempo-cluster                    tempo-worker:tempo-cluster         tempo_cluster
# tempo:tracing                          tracing-tester:charm-tracing       tracing


class BufferingSpanExporter(SpanExporter):
    """Buffers and sends out trace data."""

    cache: dict[str | None, ssl.SSLContext]

    def __init__(self, buffer_path: pathlib.Path):
        self.buffer = Buffer(buffer_path)
        self.lock = threading.Lock()
        self.cache = {}

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        """Export a batch of telemetry data.

        Note that this function cannot be instrumented to avoid data loops or recursion.
        """
        try:
            # Notes:
            # This function is called in a helper thread, which is daemonic.
            # When the dispatch is done, telemetry is shut down, causing the main thread to wait.
            # We don't want the main thread to wait for longer than 10s.
            # Margins:
            # - 1s safety margin
            # - 1s for buffered data time overhang
            # - 2s for live data
            # We don't distinguish between an export in background or due to shutdown.
            # We'll limit the running time of each export to (10 - 4) seconds.
            deadline = time.monotonic() + 6

            assert spans  # noqa: S101  # The BatchSpanProcessor won't call us if there's no data.
            rv = self.buffer.pushpop((otlp_json.encode_spans(spans), otlp_json.CONTENT_TYPE))
            assert rv  # noqa: S101  # We've just pushed something in.
            self.do_export(*rv)

            for _ in range(SENDOUT_FACTOR - 1):
                if time.monotonic() > deadline:
                    break
                if not (rv := self.buffer.pushpop()):
                    break
                self.do_export(*rv)

            return SpanExportResult.SUCCESS
        except Exception:
            logger.exception('Exporting trace data')
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
        # Note that ssl.create_default_context() doesn't allow setting the context.protocol in a
        # way that's the same across Python 3.8 and 3.10 onwards. Whip the context up by hand.
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.minimum_version = ssl.TLSVersion.TLSv1_2  # See comment at the top of module
        context.set_alpn_protocols(['http/1.1'])
        # Can't use strict certificate chain validation until our self-signed ca is fixed
        # https://github.com/canonical/self-signed-certificates-operator/issues/330
        # https://github.com/canonical/tls-certificates-interface/pull/333
        # context.verify_flags |= ssl.VERIFY_X509_STRICT
        if partial_chain := getattr(ssl, 'VERIFY_X509_PARTIAL_CHAIN', None):
            # Available starting from Python 3.10. The partial chain flag allows trusting an
            # intermediate CAs in the CA list without the matching root CA.
            context.verify_flags |= partial_chain

        if ca is not None:
            context.load_verify_locations(cadata=ca)
        else:
            context.load_default_certs()

        return context

    def do_export(self, buffered_id: int, data: bytes, mime: str) -> None:
        """Export buffered data and remove it from the buffer on success."""
        config = self.buffer.load_destination()
        if not config.url:
            return

        if not config.url.startswith(('http://', 'https://')):
            raise ValueError(f'{config.url=} must be an HTTP or HTTPS URL')
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
            resp = e.fp.read()[:1000]
            logger.exception(f'Tracing collector rejected our data, {e.code=} {resp=}')
        except OSError:
            # URLError, TimeoutError, SSLError, socket.error
            # We silence these errors, as a misconfigured system would produce too many.
            pass
        except Exception:
            logger.exception('Failed to send trace data out')
        else:
            self.buffer.remove(buffered_id)

    def shutdown(self) -> None:
        """Shut down the exporter."""
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        """No-op, as the real exporter doesn't buffer."""
        return True
