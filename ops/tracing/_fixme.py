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

import functools
import inspect
import logging
import os
import typing
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import (
    Callable,
    Sequence,
    Type,
    TypeVar,
    Union,
    cast,
)

import opentelemetry
import opentelemetry.trace
from opentelemetry.exporter.otlp.proto.common._internal.trace_encoder import (
    encode_spans,
)
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, Span, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SpanExporter,
    SpanExportResult,
)
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import (
    INVALID_SPAN,
    Tracer,
    get_tracer,
    get_tracer_provider,
    set_span_in_context,
    set_tracer_provider,
)
from opentelemetry.trace import get_current_span as otlp_get_current_span

import ops
from ops.charm import CharmBase
from ops.framework import Framework
from ops.jujucontext import _JujuContext
from ops.tracing._buffer import Buffer


logger = logging.getLogger(__name__)
dev_logger = logging.getLogger('tracing-dev')  # FIXME remove before merge
dev_logger.setLevel('DEBUG')

autoinstrument_tracer = opentelemetry.trace.get_tracer('ops.tracing.autoinstrument')
event_tracer = opentelemetry.trace.get_tracer('ops.tracing.FIXME')  # FIXME move usage to ops

_CharmType = Type[CharmBase]  # the type CharmBase and any subclass thereof
_C = TypeVar('_C', bound=_CharmType)
_T = TypeVar('_T', bound=type)
_F = TypeVar('_F', bound=Type[Callable])
tracer: ContextVar[Tracer] = ContextVar('tracer')
_GetterType = Callable[[_CharmType], str | None] | property

CHARM_TRACING_ENABLED = 'CHARM_TRACING_ENABLED'
BUFFER_DEFAULT_CACHE_FILE_NAME = '.charm_tracing_buffer.raw'
# we store the buffer as raw otlp-native protobuf (bytes) since it's hard to
# serialize/deserialize it in any portable format. Json dumping is supported, but
# loading isn't. cfr: https://github.com/open-telemetry/opentelemetry-python/issues/1003

_OTLP_SPAN_EXPORTER_TIMEOUT = 1  # seconds
"""Timeout in seconds that the OTLP span exporter has to push traces to the
backend."""

class SomethingLater:
    def flush(self) -> None:
        """Export all buffered spans to the given exporter.

        Then clear the buffer.
        Returns whether the flush was successful, and None if there was
        nothing to flush.
        """
        if not self.exporter:
            dev_logger.debug('no exporter set; skipping buffer flush')
            return False

        buffered_spans = self.load()
        if not buffered_spans:
            dev_logger.debug('nothing to flush; buffer empty')
            return None

        errors = False
        # FIXME this logic was buggy, intermittent errors were
        # not handled properly
        for span in buffered_spans:
            try:
                out = self.exporter._export(span)  # type: ignore
                if not (200 <= out.status_code < 300):
                    # take any 2xx status code as a success
                    errors = True
                    break
            except ConnectionError:
                dev_logger.debug(
                    'failed exporting buffered span; backend might be down or still starting'
                )
                errors = True
                break
            except Exception:
                logger.exception('unexpected error while flushing span batch from buffer')
                errors = True
                break

        if not errors:
            self.drop()
        else:
            # FIXME this logic is a little fishy
            logger.error('failed flushing spans; buffer preserved')
        return not errors


class ProxySpanExporter(SpanExporter):
    real_exporter: SpanExporter|None
    buffer: Buffer

    def __init__(self):
        self.real_exporter = None
        self.buffer = Buffer()

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        """Export a batch of telemetry data."""
        # FIXME check if ever called with empty sequence
        data: bytes = encode_spans(spans).SerializePartialToString()
        self.buffer.append(data)
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        """Shut down the exporter."""
        if self.real_exporter:
            self.real_exporter.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        """Export any spans received before this call."""
        return True

    def set_real_exporter(self, exporter: SpanExporter) -> None:
        self.real_exporter = exporter
        # FIXME decide on the export timing policy:
        # export everything buffered right away?
        # or export with a timeout?
        # or defer until the end of dispatch?


class _OTLPSpanExporter(OTLPSpanExporter):
    """Subclass of OTLPSpanExporter to configure the max retry timeout.

    Done this way, so that it fails a bit faster.
    """

    # The issue we're trying to solve is that the model takes AGES to settle if e.g. tls
    # is misconfigured, as every hook of a charm_tracing-instrumented charm takes about
    # a minute to exit, as the charm can't flush the traces and keeps retrying for 'too
    # long'

    _MAX_RETRY_TIMEOUT = 4
    # we give the exporter 4 seconds in total to succeed pushing the traces to tempo if
    # it fails, we'll be caching the data in the buffer and flush it the next time, so
    # there's no data loss risk. this means 2/3 retries (hard to guess from the
    # implementation) and up to ~7 seconds total wait


# FIXME not needed
class DeleteMeBufferedExporter(InMemorySpanExporter):
    def __init__(self, buffer: Buffer) -> None:
        super().__init__()
        self._buffer = buffer

    def export(self, spans: typing.Sequence[ReadableSpan]) -> SpanExportResult:
        self._buffer.save(spans)
        return super().export(spans)

    def force_flush(self, timeout_millis: int = 0) -> bool:
        # parent implementation is fake, so the timeout_millis arg is not doing
        # anything.
        result = super().force_flush(timeout_millis)
        self._buffer.save(self.get_finished_spans())
        return result


def is_enabled() -> bool:
    """Whether charm tracing is enabled."""
    return os.getenv(CHARM_TRACING_ENABLED, '1') == '1'


@contextmanager
def charm_tracing_disabled():
    """Contextmanager to temporarily disable charm tracing.

    For usage in tests.
    """
    previous = os.getenv(CHARM_TRACING_ENABLED, '1')
    os.environ[CHARM_TRACING_ENABLED] = '0'
    yield
    os.environ[CHARM_TRACING_ENABLED] = previous


def get_current_span() -> Union[Span, None]:
    """Return the currently active Span, if there is one, else None.

    If you'd rather keep your logic unconditional, you can use
    opentelemetry.trace.get_current_span, which will return an object
    that behaves like a span but records no data.
    """
    span = otlp_get_current_span()
    if span is INVALID_SPAN:
        return None
    return cast(Span, span)


# FIXME remove this deep exception hierarchy
class TracingError(RuntimeError):
    """Base class for errors raised by this module."""


# FIXME remove this deep exception hierarchy
class UntraceableObjectError(TracingError):
    """Raised when an object cannot be autoinstrumented."""


def _get_tracing_endpoint(
    tracing_endpoint_attr: str,
    charm_instance: object,
    charm_type: type,
):
    _tracing_endpoint = getattr(charm_instance, tracing_endpoint_attr)
    tracing_endpoint = _tracing_endpoint() if callable(_tracing_endpoint) else _tracing_endpoint

    if tracing_endpoint is None:
        return

    elif not isinstance(tracing_endpoint, str):
        raise TypeError(
            f'{charm_type.__name__}.{tracing_endpoint_attr} should resolve to '
            f'a tempo endpoint (string); '
            f'got {tracing_endpoint} instead.'
        )

    dev_logger.debug(f'Setting up span exporter to endpoint: {tracing_endpoint}/v1/traces')
    return f'{tracing_endpoint}/v1/traces'


def _get_server_cert(
    server_cert_attr: str,
    charm_instance: ops.CharmBase,
    charm_type: Type[ops.CharmBase],
) -> str|Path|None:
    _server_cert: str|Path|None|Callable[[], str|Path|None] = getattr(charm_instance, server_cert_attr)
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
    juju_context = _JujuContext.from_dict(os.environ)
    app_name = None if juju_context.unit_name is None else juju_context.unit_name.split('/')[0]
    service_name = f'{app_name}-charm'  # only one COS charm sets custom value

    resource = Resource.create(
        attributes={
            'service.name': service_name,
            'compose_service': service_name,  # why is this copy needed?
            'charm_type': charm_class_name,
            # juju topology
            'juju_unit': juju_context.unit_name,
            'juju_application': app_name,
            'juju_model': juju_context.model_name,
            'juju_model_uuid': juju_context.model_uuid,
        }
    )
    provider = TracerProvider(resource=resource)

    buffer = Buffer()
    # exporters = [BufferedExporter(buffer)]

    # real exporter, hardcoded for now
    otlp_exporter = OTLPSpanExporter(endpoint='http://localhost:4318/v1/traces')
    # FIXME figure this out
    # exporters.append(otlp_exporter)
    span_processor = BatchSpanProcessor(otlp_exporter)
    provider.add_span_processor(span_processor)
    set_tracer_provider(provider)


def _setup_root_span_initializer(
    charm_type: _CharmType,
    tracing_endpoint_attr: str,
    server_cert_attr: str | None,
    service_name: str | None,  # Only ever set by grafana operator, call it COS internal
    buffer_path: Path | None,
):
    """Patch the charm's initializer."""
    original_init = charm_type.__init__

    @functools.wraps(original_init)
    def wrap_init(self: CharmBase, framework: Framework, *args, **kwargs):
        # we're using 'self' here because this is charm init code, makes sense to read
        # what's below from the perspective of the charm. Self.unit.name...

        original_init(self, framework, *args, **kwargs)
        # we call this from inside the init context instead of, say, _autoinstrument,
        # because we want it to be checked on a per-charm-instantiation basis, not on a
        # per-type-declaration one.
        if not is_enabled():
            # this will only happen during unittesting, hopefully, so it's fine to log a
            # bit more verbosely
            logger.info('Tracing DISABLED: skipping root span initialization')
            return

        original_event_context = framework._event_context
        # default service name isn't just app name because it could conflict with the
        # workload service name
        _service_name = service_name or f'{self.app.name}-charm'

        unit_name = self.unit.name
        resource = Resource.create(
            attributes={
                # FIXME is it possible to detect these values early? FIXME do we need
                # parity on these very fields?
                'service.name': _service_name,  # ahem?
                'compose_service': _service_name,  # double ahem?
                'charm_type': type(self).__name__,  # Charm class name, available later
                # juju topology
                'juju_unit': unit_name,  # context
                'juju_application': self.app.name,  # from unit name?
                'juju_model': self.model.name,  # context
                'juju_model_uuid': self.model.uuid,  # context
            }
        )
        provider = TracerProvider(resource=resource)

        # if anything goes wrong with retrieving the endpoint, we let the exception
        # bubble up.
        tracing_endpoint = _get_tracing_endpoint(tracing_endpoint_attr, self, charm_type)

        buffer_only = False
        # whether we're only exporting to buffer, or also to the otlp exporter.

        if not tracing_endpoint:
            # tracing is off if tracing_endpoint is None however we can buffer things
            # until tracing comes online
            buffer_only = True

        server_cert: str|Path|None = (
            _get_server_cert(server_cert_attr, self, charm_type) if server_cert_attr else None
        )

        if (tracing_endpoint and tracing_endpoint.startswith('https://')) and not server_cert:
            logger.error(
                'Tracing endpoint is https, but no server_cert has been passed.'
                'Please point @trace_charm to a `server_cert` attr. '
                'This might also mean that the tracing provider is related to a '
                'certificates provider, but this application is not (yet). '
                'In that case, you might just have to wait a bit for the certificates '
                'integration to settle. This span will be buffered.'
            )
            buffer_only = True

        buffer = Buffer()
        buffer.pivot(buffer_path=buffer_path or Path() / BUFFER_DEFAULT_CACHE_FILE_NAME)

        # FIXME rework the exporter configuration
        exporters: list[SpanExporter] = []
        if buffer_only:
            # we have to buffer because we're missing necessary backend configuration
            dev_logger.debug('buffering mode: ON')
            exporters.append(BufferedExporter(buffer))

        else:
            dev_logger.debug('buffering mode: FALLBACK')
            # in principle, we have the right configuration to be pushing traces, but if
            # we fail for whatever reason, we will put everything in the buffer and
            # retry the next time
            otlp_exporter = _OTLPSpanExporter(
                endpoint=tracing_endpoint,
                certificate_file=str(Path(server_cert).absolute()) if server_cert else None,
                timeout=_OTLP_SPAN_EXPORTER_TIMEOUT,  # give individual requests 1 second
            )
            exporters.append(otlp_exporter)
            exporters.append(BufferedExporter(buffer))
            buffer.exporter = otlp_exporter

        for exporter in exporters:
            processor = BatchSpanProcessor(exporter)
            provider.add_span_processor(processor)

        set_tracer_provider(provider)
        _tracer = get_tracer(_service_name)
        _tracer_token = tracer.set(_tracer)

        dispatch_path = os.getenv('JUJU_DISPATCH_PATH', '')  # something like hooks/install
        event_name = dispatch_path.split('/')[1] if '/' in dispatch_path else dispatch_path
        root_span_name = f'{unit_name}: {event_name} event'
        span = _tracer.start_span(root_span_name, attributes={'juju.dispatch_path': dispatch_path})

        # all these shenanigans are to work around the fact that the opentelemetry
        # tracing API is built on the assumption that spans will be used as
        # contextmanagers. Since we don't (as we need to close the span on
        # framework.commit), we need to manually set the root span as current.
        ctx = set_span_in_context(span)

        # log a trace id, so we can pick it up from the logs (and jhack) to look it up
        # in tempo.
        root_trace_id = hex(span.get_span_context().trace_id)[2:]  # strip 0x prefix
        logger.debug(f'Starting root trace with id={root_trace_id!r}.')

        span_token = opentelemetry.context.attach(ctx)  # type: ignore

        @contextmanager
        def wrap_event_context(event_name: str):
            dev_logger.debug(f'entering event context: {event_name}')
            # when the framework enters an event context, we create a span.
            with event_tracer.start_as_current_span('event: ' + event_name) as event_context_span:
                if event_context_span:
                    # todo: figure out how to inject event attrs in here
                    event_context_span.add_event(event_name)
                yield original_event_context(event_name)

        framework._event_context = wrap_event_context  # type: ignore

        original_close = framework.close

        @functools.wraps(original_close)
        def wrap_close():
            dev_logger.debug('tearing down tracer and flushing traces')
            span.end()
            opentelemetry.context.detach(span_token)  # type: ignore
            # FIXME no more context vars
            tracer.reset(_tracer_token)
            tp = cast(TracerProvider, get_tracer_provider())
            flush_successful = tp.force_flush(timeout_millis=1000)  # don't block for too long

            if buffer_only:
                # if we're in buffer_only mode, it means we couldn't even set up the
                # exporter for tempo as we're missing some data. so attempting to flush
                # the buffer doesn't make sense
                dev_logger.debug('tracing backend unavailable: all spans pushed to buffer')

            else:
                dev_logger.debug('tracing backend found: attempting to flush buffer...')

                # if we do have an exporter for tempo, and we could send traces to it,
                # we can attempt to flush the buffer as well.
                if not flush_successful:
                    logger.error('flushing FAILED: unable to push traces to backend.')
                else:
                    dev_logger.debug('flush succeeded.')

                # FIXME why so much micro-management?
                # the backend has accepted the spans generated during this event,
                buffer.flush()

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

    :param tracing_endpoint: name of a method, property or attribute  on the charm type that
        returns an optional (fully resolvable) tempo url to which the charm traces will be pushed.
        If None, tracing will be effectively disabled.
    :param server_cert: name of a method, property or attribute on the charm type that returns an
        optional absolute path to a CA certificate file to be used when sending traces to a remote
        server.
        If it returns None, an _insecure_ connection will be used. To avoid errors in transient
        situations where the endpoint is already https but there is no certificate on disk yet, it
        is recommended to disable tracing (by returning None from the tracing_endpoint) altogether
        until the cert has been written to disk.
    :param service_name: service name tag to attach to all traces generated by this charm.
        Defaults to the juju application name this charm is deployed under.
    :param extra_types: pass any number of types that you also wish to autoinstrument.
        For example, charm libs, relation endpoint wrappers, workload abstractions, ...
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
        )
        return charm_type

    return _decorator


def _autoinstrument(
    charm_type: _T,
    tracing_endpoint_attr: str,
    server_cert_attr: Optional[str] = None,
    service_name: Optional[str] = None,
    extra_types: Sequence[type] = (),
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
    :param tracing_endpoint_attr: name of a method, property or attribute  on the charm type that
        returns an optional (fully resolvable) tempo url to which the charm traces will be pushed.
        If None, tracing will be effectively disabled.
    :param server_cert_attr: name of a method, property or attribute on the charm type that returns
        an optional absolute path to a CA certificate file to be used when sending traces to a
        remote server.
        If it returns None, an _insecure_ connection will be used. To avoid errors in transient
        situations where the endpoint is already https but there is no certificate on disk yet, it
        is recommended to disable tracing (by returning None from the tracing_endpoint) altogether
        until the cert has been written to disk.
    :param service_name: service name tag to attach to all traces generated by this charm.
        Defaults to the juju application name this charm is deployed under.
    :param extra_types: pass any number of types that you also wish to autoinstrument.
        For example, charm libs, relation endpoint wrappers, workload abstractions, ...
    :param buffer_path: path to buffer file to use for saving buffered spans.
    """
    dev_logger.debug(f'instrumenting {charm_type}')
    _setup_root_span_initializer(
        charm_type,
        tracing_endpoint_attr,
        server_cert_attr=server_cert_attr,
        service_name=service_name,
        buffer_path=buffer_path,
    )
    trace_type(charm_type)
    for type_ in extra_types:
        trace_type(type_)

    return charm_type


def trace_type(cls: _T) -> _T:
    """Set up tracing on this class.

    Use this decorator to get out-of-the-box traces for all method calls
    on instances of this class. It assumes that this class is only
    instantiated after a charm type decorated with `@trace_charm` has
    been instantiated.
    """
    dev_logger.debug(f'instrumenting {cls}')
    for name, method in inspect.getmembers(cls, predicate=inspect.isfunction):
        dev_logger.debug(f'discovered {method}')

        if method.__name__.startswith('__'):
            dev_logger.debug(f'skipping {method} (dunder)')
            continue

        # the span title in the general case should be: method call:
        # MyCharmWrappedMethods.b if the method has a name (functools.wrapped or regular
        # method), let _trace_callable use its default algorithm to determine what name
        # to give the span.
        trace_method_name = None
        try:
            qualname_c0 = method.__qualname__.split('.')[0]
            if not hasattr(cls, method.__name__):
                # if the callable doesn't have a __name__ (probably a decorated method),
                # it probably has a bad qualname too (such as
                # my_decorator.<locals>.wrapper) which is not great for finding out what
                # the trace is about. So we use the method name instead and add a
                # reference to the decorator name. Result: method call:
                # @my_decorator(MyCharmWrappedMethods.b)
                trace_method_name = f'@{qualname_c0}({cls.__name__}.{name})'
        except Exception:  # noqa: S110
            pass

        new_method = trace_method(method, name=trace_method_name)

        if isinstance(inspect.getattr_static(cls, name), staticmethod):
            new_method = staticmethod(new_method)
        setattr(cls, name, new_method)

    return cls


def trace_method(method: _F, name: str | None = None) -> _F:
    """Trace this method.

    A span will be opened when this method is called and closed when it
    returns.
    """
    return _trace_callable(method, 'method', name=name)


def trace_function(function: _F, name: str | None = None) -> _F:
    """Trace this function.

    A span will be opened when this function is called and closed when
    it returns.
    """
    return _trace_callable(function, 'function', name=name)



def _trace_callable(
    callable_: _F,
    qualifier: str,
    name: str | None = None,
) -> _F:
    dev_logger.debug(f'instrumenting {callable}')

    # sig = inspect.signature(callable)
    @functools.wraps(callable_)
    def wrapped_function(*args, **kwargs):  # type: ignore
        name_ = name or getattr(
            callable_, '__qualname__', getattr(callable, '__name__', str(callable))
        )
        # FIXME do we want this magical auto-instrumentation at all?
        import typing_extensions
        typing_extensions.reveal_type(autoinstrument_tracer.start_as_current_span)
        with autoinstrument_tracer.start_as_current_span(f'{qualifier} call: {name_}'):
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
                'cannot use @trace on CharmBase subclasses: use @trace_charm instead '
                '(we need some arguments!)'
            )
        return trace_type(obj)
    else:
        try:
            return trace_function(obj)
        except Exception:
            raise UntraceableObjectError(
                f'cannot create span from {type(obj)}; instrument {obj} manually.'
            ) from None
