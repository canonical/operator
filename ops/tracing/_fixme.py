# Copyright 2022 Canonical Ltd.
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
"""FIXME docstring"""

"""Old doc string.

```python
# import the necessary charm libs
from charms.tempo_coordinator_k8s.v0.tracing import TracingEndpointRequirer, charm_tracing_config
from charms.tempo_coordinator_k8s.v0.charm_tracing import charm_tracing

# decorate your charm class with charm_tracing:
@charm_tracing(
    # forward-declare the instance attributes that the instrumentor will look up to obtain the
    # tempo endpoint and server certificate
    tracing_endpoint="tracing_endpoint",
    server_cert="server_cert"
)
class MyCharm(CharmBase):
    _path_to_cert = "/path/to/cert.crt"
    # path to cert file **in the charm container**. Its presence will be used to determine whether
    # the charm is ready to use tls for encrypting charm traces. If your charm does not support tls,
    # you can ignore this and pass None to charm_tracing_config.
    # If you do support TLS, you'll need to make sure that the server cert is copied to this location
    # and kept up to date so the instrumentor can use it.

    def __init__(self, ...):
        ...
        self.tracing = TracingEndpointRequirer(self, ...)
        self.tracing_endpoint, self.server_cert = charm_tracing_config(self.tracing, self._path_to_cert)
```

# Detailed usage
To use this library, you need to do two things:
1) decorate your charm class with

`@trace_charm(tracing_endpoint="my_tracing_endpoint")`

2) add to your charm a "my_tracing_endpoint" (you can name this attribute whatever you like)
**property**, **method** or **instance attribute** that returns an otlp http/https endpoint url.
If you are using the ``charms.tempo_coordinator_k8s.v0.tracing.TracingEndpointRequirer`` as
``self.tracing = TracingEndpointRequirer(self)``, the implementation could be:

```
    @property
    def my_tracing_endpoint(self) -> Optional[str]:
        '''Tempo endpoint for charm tracing'''
        if self.tracing.is_ready():
            return self.tracing.get_endpoint("otlp_http")
        else:
            return None
```

At this point your charm will be automatically instrumented so that:
- charm execution starts a trace, containing
    - every event as a span (including custom events)
    - every charm method call (except dunders) as a span

We recommend that you scale up your tracing provider and relate it to an ingress so that your tracing requests
go through the ingress and get load balanced across all units. Otherwise, if the provider's leader goes down, your tracing goes down.


## TLS support
If your charm integrates with a TLS provider which is also trusted by the tracing provider (the Tempo charm),
you can configure ``charm_tracing`` to use TLS by passing a ``server_cert`` parameter to the decorator.

If your charm is not trusting the same CA as the Tempo endpoint it is sending traces to,
you'll need to implement a cert-transfer relation to obtain the CA certificate from the same
CA that Tempo is using.

For example:
```
from charms.tempo_coordinator_k8s.v0.charm_tracing import trace_charm
@trace_charm(
    tracing_endpoint="my_tracing_endpoint",
    server_cert="_server_cert"
)
class MyCharm(CharmBase):
    self._server_cert = "/path/to/server.crt"
    ...

    def on_tls_changed(self, e) -> Optional[str]:
        # update the server cert on the charm container for charm tracing
        Path(self._server_cert).write_text(self.get_server_cert())

    def on_tls_broken(self, e) -> Optional[str]:
        # remove the server cert so charm_tracing won't try to use tls anymore
        Path(self._server_cert).unlink()
```


## More fine-grained manual instrumentation
if you wish to add more spans to the trace, you can do so by getting a hold of the tracer like so:
```
import opentelemetry
...
def get_tracer(self) -> opentelemetry.trace.Tracer:
    return opentelemetry.trace.get_tracer(type(self).__name__)
```

By default, the tracer is named after the charm type. If you wish to override that, you can pass
a different ``service_name`` argument to ``trace_charm``.

See the official opentelemetry Python SDK documentation for usage:
https://opentelemetry-python.readthedocs.io/en/latest/


## Caching traces
The `trace_charm` machinery will buffer any traces collected during charm execution and store them
to a file on the charm container until a tracing backend becomes available. At that point, it will
flush them to the tracing receiver.

By default, the buffer is configured to start dropping old traces if any of these conditions apply:

- the storage size exceeds 10 MiB
- the number of buffered events exceeds 100

You can configure this by, for example:

```python
@trace_charm(
    tracing_endpoint="my_tracing_endpoint",
    server_cert="_server_cert",
    # only cache up to 42 events
    buffer_max_events=42,
    # only cache up to 42 MiB
    buffer_max_size_mib=42,  # minimum 10!
)
class MyCharm(CharmBase):
    ...
```

Note that setting `buffer_max_events` to 0 will effectively disable the buffer.

The path of the buffer file is by default in the charm's execution root, which for k8s charms means
that in case of pod churn, the cache will be lost. The recommended solution is to use an existing storage
(or add a new one) such as:

```yaml
storage:
  data:
    type: filesystem
    location: /charm-traces
```

and then configure the `@trace_charm` decorator to use it as path for storing the buffer:
```python
@trace_charm(
    tracing_endpoint="my_tracing_endpoint",
    server_cert="_server_cert",
    # store traces to a PVC so they're not lost on pod restart.
    buffer_path="/charm-traces/buffer.file",
)
class MyCharm(CharmBase):
    ...
```

## Upgrading from `v0`

If you are upgrading from `charm_tracing` v0, you need to take the following steps (assuming you already
have the newest version of the library in your charm):
1) If you need the dependency for your tests, add the following dependency to your charm project
(or, if your project had a dependency on `opentelemetry-exporter-otlp-proto-grpc` only because
of `charm_tracing` v0, you can replace it with):

`opentelemetry-exporter-otlp-proto-http>=1.21.0`.

2) Update the charm method referenced to from ``@trace`` and ``@trace_charm``,
to return from ``TracingEndpointRequirer.get_endpoint("otlp_http")`` instead of ``grpc_http``.
For example:

```
    from charms.tempo_coordinator_k8s.v0.charm_tracing import trace_charm

    @trace_charm(
        tracing_endpoint="my_tracing_endpoint",
    )
    class MyCharm(CharmBase):

    ...

        @property
        def my_tracing_endpoint(self) -> Optional[str]:
            '''Tempo endpoint for charm tracing'''
            if self.tracing.is_ready():
                return self.tracing.otlp_grpc_endpoint() #  OLD API, DEPRECATED.
            else:
                return None
```

needs to be replaced with:

```
    from charms.tempo_coordinator_k8s.v0.charm_tracing import trace_charm

    @trace_charm(
        tracing_endpoint="my_tracing_endpoint",
    )
    class MyCharm(CharmBase):

    ...

        @property
        def my_tracing_endpoint(self) -> Optional[str]:
            '''Tempo endpoint for charm tracing'''
            if self.tracing.is_ready():
                return self.tracing.get_endpoint("otlp_http")  # NEW API, use this.
            else:
                return None
```

3) If you were passing a certificate (str) using `server_cert`, you need to change it to
provide an *absolute* path to the certificate file instead.
"""
import typing

from opentelemetry.exporter.otlp.proto.common._internal.trace_encoder import (
    encode_spans,
)
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


def _remove_stale_otel_sdk_packages():
    """Hack to remove stale opentelemetry sdk packages from the charm's python venv.

    See https://github.com/canonical/grafana-agent-operator/issues/146 and
    https://bugs.launchpad.net/juju/+bug/2058335 for more context. This patch can be removed after
    this juju issue is resolved and sufficient time has passed to expect most users of this library
    have migrated to the patched version of juju.  When this patch is removed, un-ignore rule E402 for this file in the pyproject.toml (see setting
    [tool.ruff.lint.per-file-ignores] in pyproject.toml).

    This only has an effect if executed on an upgrade-charm event.
    """
    # all imports are local to keep this function standalone, side-effect-free, and easy to revert later
    import os

    if os.getenv("JUJU_DISPATCH_PATH") != "hooks/upgrade-charm":
        return

    import logging
    import shutil
    from collections import defaultdict

    from importlib_metadata import distributions

    otel_logger = logging.getLogger("charm_tracing_otel_patcher")
    otel_logger.debug("Applying _remove_stale_otel_sdk_packages patch on charm upgrade")
    # group by name all distributions starting with "opentelemetry_"
    otel_distributions = defaultdict(list)
    for distribution in distributions():
        name = distribution._normalized_name  # type: ignore
        if name.startswith("opentelemetry_"):
            otel_distributions[name].append(distribution)

    otel_logger.debug(f"Found {len(otel_distributions)} opentelemetry distributions")

    # If we have multiple distributions with the same name, remove any that have 0 associated files
    for name, distributions_ in otel_distributions.items():
        if len(distributions_) <= 1:
            continue

        otel_logger.debug(f"Package {name} has multiple ({len(distributions_)}) distributions.")
        for distribution in distributions_:
            if not distribution.files:  # Not None or empty list
                path = distribution._path  # type: ignore
                otel_logger.info(f"Removing empty distribution of {name} at {path}.")
                shutil.rmtree(path)

    otel_logger.debug("Successfully applied _remove_stale_otel_sdk_packages patch. ")


# apply hacky patch to remove stale opentelemetry sdk packages on upgrade-charm.
# it could be trouble if someone ever decides to implement their own tracer parallel to
# ours and before the charm has inited. We assume they won't.
_remove_stale_otel_sdk_packages()

import functools
import inspect
import logging
import os
from contextlib import contextmanager
from contextvars import Context, ContextVar, copy_context
from pathlib import Path
from typing import (
    Any,
    Callable,
    Generator,
    List,
    Optional,
    Sequence,
    Type,
    TypeVar,
    Union,
    cast,
)

import opentelemetry
import ops
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, Span, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SpanExporter,
    SpanExportResult,
)
from opentelemetry.trace import INVALID_SPAN, Tracer
from opentelemetry.trace import get_current_span as otlp_get_current_span
from opentelemetry.trace import (
    get_tracer,
    get_tracer_provider,
    set_span_in_context,
    set_tracer_provider,
)
from ops.charm import CharmBase
from ops.framework import Framework

# The unique Charmhub library identifier, never change it
LIBID = "01780f1e588c42c3976d26780fdf9b89"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version

LIBPATCH = 4

PYDEPS = ["opentelemetry-exporter-otlp-proto-http==1.21.0"]

logger = logging.getLogger("tracing")
dev_logger = logging.getLogger("tracing-dev")

# set this to 0 if you are debugging/developing this library source
dev_logger.setLevel(logging.ERROR)

_CharmType = Type[CharmBase]  # the type CharmBase and any subclass thereof
_C = TypeVar("_C", bound=_CharmType)
_T = TypeVar("_T", bound=type)
_F = TypeVar("_F", bound=Type[Callable])
tracer: ContextVar[Tracer] = ContextVar("tracer")
_GetterType = Union[Callable[[_CharmType], Optional[str]], property]

CHARM_TRACING_ENABLED = "CHARM_TRACING_ENABLED"
BUFFER_DEFAULT_CACHE_FILE_NAME = ".charm_tracing_buffer.raw"
# we store the buffer as raw otlp-native protobuf (bytes) since it's hard to serialize/deserialize it in
# any portable format. Json dumping is supported, but loading isn't.
# cfr: https://github.com/open-telemetry/opentelemetry-python/issues/1003

BUFFER_DEFAULT_CACHE_FILE_SIZE_LIMIT_MiB = 10
_BUFFER_CACHE_FILE_SIZE_LIMIT_MiB_MIN = 10
BUFFER_DEFAULT_MAX_EVENT_HISTORY_LENGTH = 100
_MiB_TO_B = 2**20  # megabyte to byte conversion rate
_OTLP_SPAN_EXPORTER_TIMEOUT = 1
"""Timeout in seconds that the OTLP span exporter has to push traces to the backend."""


class _Buffer:
    """Handles buffering for spans emitted while no tracing backend is configured or available.

    Use the max_event_history_length_buffering param of @trace_charm to tune
    the amount of memory that this will hog on your units.

    The buffer is formatted as a bespoke byte dump (protobuf limitation).
    We cannot store them as json because that is not well-supported by the sdk
    (see https://github.com/open-telemetry/opentelemetry-python/issues/3364).
    """

    _SPANSEP = b"__CHARM_TRACING_BUFFER_SPAN_SEP__"

    def __init__(self, db_file: Path, max_event_history_length: int, max_buffer_size_mib: int):
        self._db_file = db_file
        self._max_event_history_length = max_event_history_length
        self._max_buffer_size_mib = max(max_buffer_size_mib, _BUFFER_CACHE_FILE_SIZE_LIMIT_MiB_MIN)

        # set by caller
        self.exporter: Optional[OTLPSpanExporter] = None

    def save(self, spans: typing.Sequence[ReadableSpan]):
        """Save the spans collected by this exporter to the cache file.

        This method should be as fail-safe as possible.
        """
        if self._max_event_history_length < 1:
            dev_logger.debug("buffer disabled: max history length < 1")
            return

        current_history_length = len(self.load())
        new_history_length = current_history_length + len(spans)
        if (diff := self._max_event_history_length - new_history_length) < 0:
            self.drop(diff)
        self._save(spans)

    def _serialize(self, spans: Sequence[ReadableSpan]) -> bytes:
        # encode because otherwise we can't json-dump them
        return encode_spans(spans).SerializeToString()

    def _save(self, spans: Sequence[ReadableSpan], replace: bool = False):
        dev_logger.debug(f"saving {len(spans)} new spans to buffer")
        old = [] if replace else self.load()
        new = self._serialize(spans)

        try:
            # if the buffer exceeds the size limit, we start dropping old spans until it does

            while len((new + self._SPANSEP.join(old))) > (self._max_buffer_size_mib * _MiB_TO_B):
                if not old:
                    # if we've already dropped all spans and still we can't get under the
                    # size limit, we can't save this span
                    logger.error(
                        f"span exceeds total buffer size limit ({self._max_buffer_size_mib}MiB); "
                        f"buffering FAILED"
                    )
                    return

                old = old[1:]
                logger.warning(
                    f"buffer size exceeds {self._max_buffer_size_mib}MiB; dropping older spans... "
                    f"Please increase the buffer size, disable buffering, or ensure the spans can be flushed."
                )

            self._db_file.write_bytes(new + self._SPANSEP.join(old))
        except Exception:
            logger.exception("error buffering spans")

    def load(self) -> List[bytes]:
        """Load currently buffered spans from the cache file.

        This method should be as fail-safe as possible.
        """
        if not self._db_file.exists():
            dev_logger.debug("buffer file not found. buffer empty.")
            return []
        try:
            spans = self._db_file.read_bytes().split(self._SPANSEP)
        except Exception:
            logger.exception(f"error parsing {self._db_file}")
            return []
        return spans

    def drop(self, n_spans: Optional[int] = None):
        """Drop some currently buffered spans from the cache file."""
        current = self.load()
        if n_spans:
            dev_logger.debug(f"dropping {n_spans} spans from buffer")
            new = current[n_spans:]
        else:
            dev_logger.debug("emptying buffer")
            new = []

        self._db_file.write_bytes(self._SPANSEP.join(new))

    def flush(self) -> Optional[bool]:
        """Export all buffered spans to the given exporter, then clear the buffer.

        Returns whether the flush was successful, and None if there was nothing to flush.
        """
        if not self.exporter:
            dev_logger.debug("no exporter set; skipping buffer flush")
            return False

        buffered_spans = self.load()
        if not buffered_spans:
            dev_logger.debug("nothing to flush; buffer empty")
            return None

        errors = False
        for span in buffered_spans:
            try:
                out = self.exporter._export(span)  # type: ignore
                if not (200 <= out.status_code < 300):
                    # take any 2xx status code as a success
                    errors = True
            except ConnectionError:
                dev_logger.debug(
                    "failed exporting buffered span; backend might be down or still starting"
                )
                errors = True
            except Exception:
                logger.exception("unexpected error while flushing span batch from buffer")
                errors = True

        if not errors:
            self.drop()
        else:
            logger.error("failed flushing spans; buffer preserved")
        return not errors

    @property
    def is_empty(self):
        """Utility to check whether the buffer has any stored spans.

        This is more efficient than attempting a load() given how large the buffer might be.
        """
        return (not self._db_file.exists()) or (self._db_file.stat().st_size == 0)


class _OTLPSpanExporter(OTLPSpanExporter):
    """Subclass of OTLPSpanExporter to configure the max retry timeout, so that it fails a bit faster."""

    # The issue we're trying to solve is that the model takes AGES to settle if e.g. tls is misconfigured,
    # as every hook of a charm_tracing-instrumented charm takes about a minute to exit, as the charm can't
    # flush the traces and keeps retrying for 'too long'

    _MAX_RETRY_TIMEOUT = 4
    # we give the exporter 4 seconds in total to succeed pushing the traces to tempo
    # if it fails, we'll be caching the data in the buffer and flush it the next time, so there's no data loss risk.
    # this means 2/3 retries (hard to guess from the implementation) and up to ~7 seconds total wait


class _BufferedExporter(InMemorySpanExporter):
    def __init__(self, buffer: _Buffer) -> None:
        super().__init__()
        self._buffer = buffer

    def export(self, spans: typing.Sequence[ReadableSpan]) -> SpanExportResult:
        self._buffer.save(spans)
        return super().export(spans)

    def force_flush(self, timeout_millis: int = 0) -> bool:
        # parent implementation is fake, so the timeout_millis arg is not doing anything.
        result = super().force_flush(timeout_millis)
        self._buffer.save(self.get_finished_spans())
        return result


def is_enabled() -> bool:
    """Whether charm tracing is enabled."""
    return os.getenv(CHARM_TRACING_ENABLED, "1") == "1"


@contextmanager
def charm_tracing_disabled():
    """Contextmanager to temporarily disable charm tracing.

    For usage in tests.
    """
    previous = os.getenv(CHARM_TRACING_ENABLED, "1")
    os.environ[CHARM_TRACING_ENABLED] = "0"
    yield
    os.environ[CHARM_TRACING_ENABLED] = previous


def get_current_span() -> Union[Span, None]:
    """Return the currently active Span, if there is one, else None.

    If you'd rather keep your logic unconditional, you can use opentelemetry.trace.get_current_span,
    which will return an object that behaves like a span but records no data.
    """
    span = otlp_get_current_span()
    if span is INVALID_SPAN:
        return None
    return cast(Span, span)


def _get_tracer_from_context(ctx: Context) -> Optional[ContextVar]:
    tracers = [v for v in ctx if v is not None and v.name == "tracer"]
    if tracers:
        return tracers[0]
    return None


def _get_tracer() -> Optional[Tracer]:
    """Find tracer in context variable and as a fallback locate it in the full context."""
    try:
        return tracer.get()
    except LookupError:
        # fallback: this course-corrects for a user error where charm_tracing symbols are imported
        # from different paths (typically charms.tempo_coordinator_k8s... and lib.charms.tempo_coordinator_k8s...)
        try:
            ctx: Context = copy_context()
            if context_tracer := _get_tracer_from_context(ctx):
                logger.warning(
                    "Tracer not found in `tracer` context var. "
                    "Verify that you're importing all `charm_tracing` symbols from the same module path. \n"
                    "For example, DO"
                    ": `from charms.lib...charm_tracing import foo, bar`. \n"
                    "DONT: \n"
                    " \t - `from charms.lib...charm_tracing import foo` \n"
                    " \t - `from lib...charm_tracing import bar` \n"
                    "For more info: https://python-notes.curiousefficiency.org/en/latest/python"
                    "_concepts/import_traps.html#the-double-import-trap"
                )
                return context_tracer.get()
            else:
                return None
        except LookupError:
            return None


@contextmanager
def _span(name: str) -> Generator[Optional[Span], Any, Any]:
    """Context to create a span if there is a tracer, otherwise do nothing."""
    if tracer := _get_tracer():
        with tracer.start_as_current_span(name) as span:
            yield cast(Span, span)
    else:
        yield None


class TracingError(RuntimeError):
    """Base class for errors raised by this module."""


class UntraceableObjectError(TracingError):
    """Raised when an object you're attempting to instrument cannot be autoinstrumented."""


def _get_tracing_endpoint(
    tracing_endpoint_attr: str,
    charm_instance: object,
    charm_type: type,
):
    _tracing_endpoint = getattr(charm_instance, tracing_endpoint_attr)
    if callable(_tracing_endpoint):
        tracing_endpoint = _tracing_endpoint()
    else:
        tracing_endpoint = _tracing_endpoint

    if tracing_endpoint is None:
        return

    elif not isinstance(tracing_endpoint, str):
        raise TypeError(
            f"{charm_type.__name__}.{tracing_endpoint_attr} should resolve to a tempo endpoint (string); "
            f"got {tracing_endpoint} instead."
        )

    dev_logger.debug(f"Setting up span exporter to endpoint: {tracing_endpoint}/v1/traces")
    return f"{tracing_endpoint}/v1/traces"


def _get_server_cert(
    server_cert_attr: str,
    charm_instance: ops.CharmBase,
    charm_type: Type[ops.CharmBase],
):
    _server_cert = getattr(charm_instance, server_cert_attr)
    if callable(_server_cert):
        server_cert = _server_cert()
    else:
        server_cert = _server_cert

    if server_cert is None:
        logger.warning(
            f"{charm_type}.{server_cert_attr} is None; sending traces over INSECURE connection."
        )
        return
    elif not Path(server_cert).is_absolute():
        raise ValueError(
            f"{charm_type}.{server_cert_attr} should resolve to a valid tls cert absolute path (string | Path)); "
            f"got {server_cert} instead."
        )
    return server_cert


def _setup_root_span_initializer(
    charm_type: _CharmType,
    tracing_endpoint_attr: str,
    server_cert_attr: Optional[str],
    service_name: Optional[str],
    buffer_path: Optional[Path],
    buffer_max_events: int,
    buffer_max_size_mib: int,
):
    """Patch the charm's initializer."""
    original_init = charm_type.__init__

    @functools.wraps(original_init)
    def wrap_init(self: CharmBase, framework: Framework, *args, **kwargs):
        # we're using 'self' here because this is charm init code, makes sense to read what's below
        # from the perspective of the charm. Self.unit.name...

        original_init(self, framework, *args, **kwargs)
        # we call this from inside the init context instead of, say, _autoinstrument, because we want it to
        # be checked on a per-charm-instantiation basis, not on a per-type-declaration one.
        if not is_enabled():
            # this will only happen during unittesting, hopefully, so it's fine to log a
            # bit more verbosely
            logger.info("Tracing DISABLED: skipping root span initialization")
            return

        original_event_context = framework._event_context
        # default service name isn't just app name because it could conflict with the workload service name
        _service_name = service_name or f"{self.app.name}-charm"

        unit_name = self.unit.name
        resource = Resource.create(
            attributes={
                "service.name": _service_name,
                "compose_service": _service_name,
                "charm_type": type(self).__name__,
                # juju topology
                "juju_unit": unit_name,
                "juju_application": self.app.name,
                "juju_model": self.model.name,
                "juju_model_uuid": self.model.uuid,
            }
        )
        provider = TracerProvider(resource=resource)

        # if anything goes wrong with retrieving the endpoint, we let the exception bubble up.
        tracing_endpoint = _get_tracing_endpoint(tracing_endpoint_attr, self, charm_type)

        buffer_only = False
        # whether we're only exporting to buffer, or also to the otlp exporter.

        if not tracing_endpoint:
            # tracing is off if tracing_endpoint is None
            # however we can buffer things until tracing comes online
            buffer_only = True

        server_cert: Optional[Union[str, Path]] = (
            _get_server_cert(server_cert_attr, self, charm_type) if server_cert_attr else None
        )

        if (tracing_endpoint and tracing_endpoint.startswith("https://")) and not server_cert:
            logger.error(
                "Tracing endpoint is https, but no server_cert has been passed."
                "Please point @trace_charm to a `server_cert` attr. "
                "This might also mean that the tracing provider is related to a "
                "certificates provider, but this application is not (yet). "
                "In that case, you might just have to wait a bit for the certificates "
                "integration to settle. This span will be buffered."
            )
            buffer_only = True

        buffer = _Buffer(
            db_file=buffer_path or Path() / BUFFER_DEFAULT_CACHE_FILE_NAME,
            max_event_history_length=buffer_max_events,
            max_buffer_size_mib=buffer_max_size_mib,
        )
        previous_spans_buffered = not buffer.is_empty

        exporters: List[SpanExporter] = []
        if buffer_only:
            # we have to buffer because we're missing necessary backend configuration
            dev_logger.debug("buffering mode: ON")
            exporters.append(_BufferedExporter(buffer))

        else:
            dev_logger.debug("buffering mode: FALLBACK")
            # in principle, we have the right configuration to be pushing traces,
            # but if we fail for whatever reason, we will put everything in the buffer
            # and retry the next time
            otlp_exporter = _OTLPSpanExporter(
                endpoint=tracing_endpoint,
                certificate_file=str(Path(server_cert).absolute()) if server_cert else None,
                timeout=_OTLP_SPAN_EXPORTER_TIMEOUT,  # give individual requests 1 second to succeed
            )
            exporters.append(otlp_exporter)
            exporters.append(_BufferedExporter(buffer))
            buffer.exporter = otlp_exporter

        for exporter in exporters:
            processor = BatchSpanProcessor(exporter)
            provider.add_span_processor(processor)

        set_tracer_provider(provider)
        _tracer = get_tracer(_service_name)  # type: ignore
        _tracer_token = tracer.set(_tracer)

        dispatch_path = os.getenv("JUJU_DISPATCH_PATH", "")  # something like hooks/install
        event_name = dispatch_path.split("/")[1] if "/" in dispatch_path else dispatch_path
        root_span_name = f"{unit_name}: {event_name} event"
        span = _tracer.start_span(root_span_name, attributes={"juju.dispatch_path": dispatch_path})

        # all these shenanigans are to work around the fact that the opentelemetry tracing API is built
        # on the assumption that spans will be used as contextmanagers.
        # Since we don't (as we need to close the span on framework.commit),
        # we need to manually set the root span as current.
        ctx = set_span_in_context(span)

        # log a trace id, so we can pick it up from the logs (and jhack) to look it up in tempo.
        root_trace_id = hex(span.get_span_context().trace_id)[2:]  # strip 0x prefix
        logger.debug(f"Starting root trace with id={root_trace_id!r}.")

        span_token = opentelemetry.context.attach(ctx)  # type: ignore

        @contextmanager
        def wrap_event_context(event_name: str):
            dev_logger.debug(f"entering event context: {event_name}")
            # when the framework enters an event context, we create a span.
            with _span("event: " + event_name) as event_context_span:
                if event_context_span:
                    # todo: figure out how to inject event attrs in here
                    event_context_span.add_event(event_name)
                yield original_event_context(event_name)

        framework._event_context = wrap_event_context  # type: ignore

        original_close = framework.close

        @functools.wraps(original_close)
        def wrap_close():
            dev_logger.debug("tearing down tracer and flushing traces")
            span.end()
            opentelemetry.context.detach(span_token)  # type: ignore
            tracer.reset(_tracer_token)
            tp = cast(TracerProvider, get_tracer_provider())
            flush_successful = tp.force_flush(timeout_millis=1000)  # don't block for too long

            if buffer_only:
                # if we're in buffer_only mode, it means we couldn't even set up the exporter for
                # tempo as we're missing some data.
                # so attempting to flush the buffer doesn't make sense
                dev_logger.debug("tracing backend unavailable: all spans pushed to buffer")

            else:
                dev_logger.debug("tracing backend found: attempting to flush buffer...")

                # if we do have an exporter for tempo, and we could send traces to it,
                # we can attempt to flush the buffer as well.
                if not flush_successful:
                    logger.error("flushing FAILED: unable to push traces to backend.")
                else:
                    dev_logger.debug("flush succeeded.")

                    # the backend has accepted the spans generated during this event,
                    if not previous_spans_buffered:
                        # if the buffer was empty to begin with, any spans we collected now can be discarded
                        buffer.drop()
                        dev_logger.debug("buffer dropped: this trace has been sent already")
                    else:
                        # if the buffer was nonempty, we can attempt to flush it
                        dev_logger.debug("attempting buffer flush...")
                        buffer_flush_successful = buffer.flush()
                        if buffer_flush_successful:
                            dev_logger.debug("buffer flush OK")
                        elif buffer_flush_successful is None:
                            # TODO is this even possible?
                            dev_logger.debug("buffer flush OK; empty: nothing to flush")
                        else:
                            # this situation is pretty weird, I'm not even sure it can happen,
                            # because it would mean that we did manage
                            # to push traces directly to the tempo exporter (flush_successful),
                            # but the buffer flush failed to push to the same exporter!
                            logger.error("buffer flush FAILED")

            tp.shutdown()
            original_close()

        framework.close = wrap_close
        return

    charm_type.__init__ = wrap_init  # type: ignore


def trace_charm(
    tracing_endpoint: str,
    server_cert: Optional[str] = None,
    service_name: Optional[str] = None,
    extra_types: Sequence[type] = (),
    buffer_max_events: int = BUFFER_DEFAULT_MAX_EVENT_HISTORY_LENGTH,
    buffer_max_size_mib: int = BUFFER_DEFAULT_CACHE_FILE_SIZE_LIMIT_MiB,
    buffer_path: Optional[Union[str, Path]] = None,
) -> Callable[[_T], _T]:
    """Autoinstrument the decorated charm with tracing telemetry.

    Use this function to get out-of-the-box traces for all events emitted on this charm and all
    method calls on instances of this class.

    Usage:
    >>> from charms.tempo_coordinator_k8s.v0.charm_tracing import trace_charm
    >>> from charms.tempo_coordinator_k8s.v0.tracing import TracingEndpointRequirer
    >>> from ops import CharmBase
    >>>
    >>> @trace_charm(
    >>>         tracing_endpoint="tempo_otlp_http_endpoint",
    >>> )
    >>> class MyCharm(CharmBase):
    >>>
    >>>     def __init__(self, framework: Framework):
    >>>         ...
    >>>         self.tracing = TracingEndpointRequirer(self)
    >>>
    >>>     @property
    >>>     def tempo_otlp_http_endpoint(self) -> Optional[str]:
    >>>         if self.tracing.is_ready():
    >>>             return self.tracing.otlp_http_endpoint()
    >>>         else:
    >>>             return None
    >>>

    :param tracing_endpoint: name of a method, property or attribute  on the charm type that returns an
        optional (fully resolvable) tempo url to which the charm traces will be pushed.
        If None, tracing will be effectively disabled.
    :param server_cert: name of a method, property or attribute on the charm type that returns an
        optional absolute path to a CA certificate file to be used when sending traces to a remote server.
        If it returns None, an _insecure_ connection will be used. To avoid errors in transient
        situations where the endpoint is already https but there is no certificate on disk yet, it
        is recommended to disable tracing (by returning None from the tracing_endpoint) altogether
        until the cert has been written to disk.
    :param service_name: service name tag to attach to all traces generated by this charm.
        Defaults to the juju application name this charm is deployed under.
    :param extra_types: pass any number of types that you also wish to autoinstrument.
        For example, charm libs, relation endpoint wrappers, workload abstractions, ...
    :param buffer_max_events: max number of events to save in the buffer. Set to 0 to disable buffering.
    :param buffer_max_size_mib: max size of the buffer file. When exceeded, spans will be dropped.
        Minimum 10MiB.
    :param buffer_path: path to buffer file to use for saving buffered spans.
    """

    def _decorator(charm_type: _T) -> _T:
        """Autoinstrument the wrapped charmbase type."""
        _autoinstrument(
            charm_type,
            tracing_endpoint_attr=tracing_endpoint,
            server_cert_attr=server_cert,
            service_name=service_name,
            extra_types=extra_types,
            buffer_path=Path(buffer_path) if buffer_path else None,
            buffer_max_size_mib=buffer_max_size_mib,
            buffer_max_events=buffer_max_events,
        )
        return charm_type

    return _decorator


def _autoinstrument(
    charm_type: _T,
    tracing_endpoint_attr: str,
    server_cert_attr: Optional[str] = None,
    service_name: Optional[str] = None,
    extra_types: Sequence[type] = (),
    buffer_max_events: int = BUFFER_DEFAULT_MAX_EVENT_HISTORY_LENGTH,
    buffer_max_size_mib: int = BUFFER_DEFAULT_CACHE_FILE_SIZE_LIMIT_MiB,
    buffer_path: Optional[Path] = None,
) -> _T:
    """Set up tracing on this charm class.

    Use this function to get out-of-the-box traces for all events emitted on this charm and all
    method calls on instances of this class.

    Usage:

    >>> from charms.tempo_coordinator_k8s.v0.charm_tracing import _autoinstrument
    >>> from ops.main import main
    >>> _autoinstrument(
    >>>         MyCharm,
    >>>         tracing_endpoint_attr="tempo_otlp_http_endpoint",
    >>>         service_name="MyCharm",
    >>>         extra_types=(Foo, Bar)
    >>> )
    >>> main(MyCharm)

    :param charm_type: the CharmBase subclass to autoinstrument.
    :param tracing_endpoint_attr: name of a method, property or attribute  on the charm type that returns an
        optional (fully resolvable) tempo url to which the charm traces will be pushed.
        If None, tracing will be effectively disabled.
    :param server_cert_attr: name of a method, property or attribute on the charm type that returns an
        optional absolute path to a CA certificate file to be used when sending traces to a remote server.
        If it returns None, an _insecure_ connection will be used. To avoid errors in transient
        situations where the endpoint is already https but there is no certificate on disk yet, it
        is recommended to disable tracing (by returning None from the tracing_endpoint) altogether
        until the cert has been written to disk.
    :param service_name: service name tag to attach to all traces generated by this charm.
        Defaults to the juju application name this charm is deployed under.
    :param extra_types: pass any number of types that you also wish to autoinstrument.
        For example, charm libs, relation endpoint wrappers, workload abstractions, ...
    :param buffer_max_events: max number of events to save in the buffer. Set to 0 to disable buffering.
    :param buffer_max_size_mib: max size of the buffer file. When exceeded, spans will be dropped.
        Minimum 10MiB.
    :param buffer_path: path to buffer file to use for saving buffered spans.
    """
    dev_logger.debug(f"instrumenting {charm_type}")
    _setup_root_span_initializer(
        charm_type,
        tracing_endpoint_attr,
        server_cert_attr=server_cert_attr,
        service_name=service_name,
        buffer_path=buffer_path,
        buffer_max_events=buffer_max_events,
        buffer_max_size_mib=buffer_max_size_mib,
    )
    trace_type(charm_type)
    for type_ in extra_types:
        trace_type(type_)

    return charm_type


def trace_type(cls: _T) -> _T:
    """Set up tracing on this class.

    Use this decorator to get out-of-the-box traces for all method calls on instances of this class.
    It assumes that this class is only instantiated after a charm type decorated with `@trace_charm`
    has been instantiated.
    """
    dev_logger.debug(f"instrumenting {cls}")
    for name, method in inspect.getmembers(cls, predicate=inspect.isfunction):
        dev_logger.debug(f"discovered {method}")

        if method.__name__.startswith("__"):
            dev_logger.debug(f"skipping {method} (dunder)")
            continue

        # the span title in the general case should be:
        #   method call: MyCharmWrappedMethods.b
        # if the method has a name (functools.wrapped or regular method), let
        # _trace_callable use its default algorithm to determine what name to give the span.
        trace_method_name = None
        try:
            qualname_c0 = method.__qualname__.split(".")[0]
            if not hasattr(cls, method.__name__):
                # if the callable doesn't have a __name__ (probably a decorated method),
                # it probably has a bad qualname too (such as my_decorator.<locals>.wrapper) which is not
                # great for finding out what the trace is about. So we use the method name instead and
                # add a reference to the decorator name. Result:
                #   method call: @my_decorator(MyCharmWrappedMethods.b)
                trace_method_name = f"@{qualname_c0}({cls.__name__}.{name})"
        except Exception:  # noqa: failsafe
            pass

        new_method = trace_method(method, name=trace_method_name)

        if isinstance(inspect.getattr_static(cls, name), staticmethod):
            new_method = staticmethod(new_method)
        setattr(cls, name, new_method)

    return cls


def trace_method(method: _F, name: Optional[str] = None) -> _F:
    """Trace this method.

    A span will be opened when this method is called and closed when it returns.
    """
    return _trace_callable(method, "method", name=name)


def trace_function(function: _F, name: Optional[str] = None) -> _F:
    """Trace this function.

    A span will be opened when this function is called and closed when it returns.
    """
    return _trace_callable(function, "function", name=name)


def _trace_callable(callable: _F, qualifier: str, name: Optional[str] = None) -> _F:
    dev_logger.debug(f"instrumenting {callable}")

    # sig = inspect.signature(callable)
    @functools.wraps(callable)
    def wrapped_function(*args, **kwargs):  # type: ignore
        name_ = name or getattr(
            callable, "__qualname__", getattr(callable, "__name__", str(callable))
        )
        with _span(f"{qualifier} call: {name_}"):  # type: ignore
            return callable(*args, **kwargs)  # type: ignore

    # wrapped_function.__signature__ = sig
    return wrapped_function  # type: ignore


def trace(obj: Union[Type, Callable]):
    """Trace this object and send the resulting spans to Tempo.

    It will dispatch to ``trace_type`` if the decorated object is a class, otherwise
    ``trace_function``.
    """
    if isinstance(obj, type):
        if issubclass(obj, CharmBase):
            raise ValueError(
                "cannot use @trace on CharmBase subclasses: use @trace_charm instead "
                "(we need some arguments!)"
            )
        return trace_type(obj)
    else:
        try:
            return trace_function(obj)
        except Exception:
            raise UntraceableObjectError(
                f"cannot create span from {type(obj)}; instrument {obj} manually."
            )
