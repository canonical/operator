# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

# Forked from
# https://github.com/canonical/tempo-coordinator-k8s-operator
# (lib charms.tempo_coordinator_k8s.v0.tracing, LIBAPI 0 LIBPATCH 6).
# De-pydantic'd for ops_tracing's use: the pydantic ``BaseModel`` databag
# models (``DatabagModel``, ``ProtocolType``, ``Receiver``,
# ``TracingProviderAppData``, ``TracingRequirerAppData``) have been replaced
# with stdlib ``dataclasses`` plus manual validation, so that ops_tracing no
# longer pulls ``pydantic`` (and ``pydantic-core`` / ``annotated-types`` /
# ``typing-inspection``) into its dependency tree.
#
# Dropped vs upstream, since ops_tracing only acts as a requirer and never
# re-publishes this copy:
#  - the charmhub publish metadata (``LIBID`` / ``LIBAPI`` / ``LIBPATCH`` /
#    ``PYDEPS``) and unused module constants (``RawReceiver``,
#    ``BUILTIN_JUJU_KEYS``, ``receiver_protocol_to_transport_protocol``);
#  - the whole provider side (``TracingEndpointProvider`` and its
#    ``RequestEvent`` / ``BrokenEvent`` / ``TracingEndpointProviderEvents`` and
#    ``NotReadyError``);
#  - the relation-direction validation helper
#    (``_validate_relation_by_interface_and_direction`` and its
#    ``Relation*MismatchError`` / ``RelationNotFoundError`` exceptions) —
#    ops_tracing already validates the relation's existence, role and interface
#    before constructing the requirer;
#  - the ``charm_tracing_config`` convenience wrapper;
#  - the pydantic-v1 compatibility branches.
#
# Do NOT re-sync from upstream without re-applying this fork. See
# ``non-roadmap/depydantic-charm-libs`` in the canonical-work-queue repo for
# the audit of exactly what was dropped.

"""## Overview.

This document explains how to integrate with the Tempo charm for the purpose of pushing traces to a
tracing endpoint provided by Tempo.

## Requirer Library Usage

Charms seeking to push traces to Tempo, must do so using the `TracingEndpointRequirer`
object from this charm library. For the simplest use cases, using the `TracingEndpointRequirer`
object only requires instantiating it, typically in the constructor of your charm. The
`TracingEndpointRequirer` constructor requires the name of the relation over which a tracing
endpoint is exposed by the Tempo charm, and a list of protocols it intends to send traces with.
 This relation must use the `tracing` interface.
 The `TracingEndpointRequirer` object may be instantiated as follows

    from charms.tempo_coordinator_k8s.v0.tracing import TracingEndpointRequirer

    def __init__(self, *args):
        super().__init__(*args)
        # ...
        self.tracing = TracingEndpointRequirer(self,
            protocols=['otlp_grpc', 'otlp_http', 'jaeger_http_thrift']
        )
        # ...

Note that the first argument (`self`) to `TracingEndpointRequirer` is always a reference to the
parent charm.

Units of requirer charms obtain the tempo endpoint to which they will push their traces by calling
`TracingEndpointRequirer.get_endpoint(protocol: str)`, where `protocol` is, for example:
- `otlp_grpc`
- `otlp_http`
- `zipkin`
- `tempo`

If the `protocol` is not in the list of protocols that the charm requested at endpoint set-up time,
the library will raise an error.
"""

import dataclasses
import enum
import json
import logging
import typing
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Dict,
    List,
    Literal,
    MutableMapping,
    Optional,
    Sequence,
    Tuple,
)

from ops.charm import (
    CharmBase,
    CharmEvents,
    RelationBrokenEvent,
    RelationEvent,
)
from ops.framework import EventSource, Object
from ops.model import ModelError, Relation

logger = logging.getLogger(__name__)

DEFAULT_RELATION_NAME = 'tracing'
RELATION_INTERFACE_NAME = 'tracing'

# Supported list rationale https://github.com/canonical/tempo-coordinator-k8s-operator/issues/8
ReceiverProtocol = Literal[
    'zipkin',
    'otlp_grpc',
    'otlp_http',
    'jaeger_grpc',
    'jaeger_thrift_http',
]


class TransportProtocolType(str, enum.Enum):
    """Receiver Type."""

    http = 'http'
    grpc = 'grpc'


class TracingError(Exception):
    """Base class for custom errors raised by this library."""


class ProtocolNotRequestedError(TracingError):
    """Raised if the user attempts to obtain an endpoint for a protocol it did not request."""


class DataValidationError(TracingError):
    """Raised when data validation fails on IPU relation data."""


class AmbiguousRelationUsageError(TracingError):
    """Raised when one wrongly assumes that there can only be one relation on an endpoint."""


def _json_safe(value: Any) -> Any:
    """Recursively convert a value into a JSON-serialisable form.

    Replaces what pydantic's ``model_dump()`` did for the field types this
    library uses: nested dataclasses become dicts and enums become their value.
    """
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: _json_safe(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, (set, frozenset)):
        return sorted(_json_safe(v) for v in value)
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    return value


def _coerce(tp: Any, value: Any) -> Any:
    """Coerce a JSON-decoded ``value`` into the dataclass field type ``tp``."""
    origin = typing.get_origin(tp)
    if origin is not None:
        args = typing.get_args(tp)
        if origin in (list, tuple):
            return [_coerce(args[0], v) for v in value]
        if origin in (set, frozenset):
            return {_coerce(args[0], v) for v in value}
        # Literal, Union, etc.: accept the value as-is.
        return value
    if isinstance(tp, type):
        if dataclasses.is_dataclass(tp):
            return _build(tp, value)
        if issubclass(tp, enum.Enum):
            return tp(value)
    return value


def _build(cls: Any, data: MutableMapping[str, Any]) -> Any:
    """Construct a dataclass ``cls`` from a plain ``data`` mapping.

    Required fields (those with no default) must be present; missing ones raise
    ``DataValidationError`` (mirroring pydantic's required-field behaviour).
    """
    hints = typing.get_type_hints(cls)
    kwargs: Dict[str, Any] = {}
    for field in dataclasses.fields(cls):
        if field.name not in data:
            has_default = (
                field.default is not dataclasses.MISSING
                or field.default_factory is not dataclasses.MISSING
            )
            if has_default:
                continue
            raise DataValidationError(f'missing required field {field.name!r}')
        kwargs[field.name] = _coerce(hints[field.name], data[field.name])
    return cls(**kwargs)


def _is_default(field: 'dataclasses.Field[Any]', value: Any) -> bool:
    """Whether ``value`` equals the field's declared default."""
    if field.default is not dataclasses.MISSING:
        return value == field.default
    if field.default_factory is not dataclasses.MISSING:
        return value == field.default_factory()
    return False


def _databag_load(cls: Any, databag: MutableMapping[str, str]) -> Any:
    """``DatabagModel.load`` replacement: per-key ``json.loads`` then validate.

    Each databag key holds a JSON-encoded value (Juju's relation-databag
    convention). Unknown keys are ignored (matching pydantic's
    ``extra="ignore"``).
    """
    field_names = {f.name for f in dataclasses.fields(cls)}
    try:
        data = {k: json.loads(v) for k, v in databag.items() if k in field_names}
    except json.JSONDecodeError as e:
        msg = f'invalid databag contents: expecting json. {databag}'
        logger.error(msg)
        raise DataValidationError(msg) from e

    try:
        return _build(cls, data)
    except (TypeError, ValueError, KeyError) as e:
        msg = f'failed to validate databag: {databag}'
        logger.debug(msg, exc_info=True)
        raise DataValidationError(msg) from e


def _databag_dump(
    obj: Any,
    databag: Optional[MutableMapping[str, str]] = None,
    clear: bool = True,
) -> MutableMapping[str, str]:
    """``DatabagModel.dump`` replacement: JSON-encode each non-default field."""
    if clear and databag:
        databag.clear()
    if databag is None:
        databag = {}
    for field in dataclasses.fields(obj):
        value = getattr(obj, field.name)
        # Skip values equal to the field default (matches pydantic's
        # ``exclude_defaults=True``).
        if _is_default(field, value):
            continue
        databag[field.name] = json.dumps(_json_safe(value))
    return databag


@dataclasses.dataclass(frozen=True)
class ProtocolType:
    """Protocol Type."""

    name: str
    """Receiver protocol name. What protocols are supported (and what they are
    called) may differ per provider."""
    type: TransportProtocolType
    """The transport protocol used by this receiver."""


@dataclasses.dataclass(frozen=True)
class Receiver:
    """Specification of an active receiver."""

    protocol: ProtocolType
    """Receiver protocol name and type."""
    url: str
    """URL at which the receiver is reachable. If there's an ingress, it would
    be the external URL. Otherwise, it would be the service's fqdn or internal
    IP. If the protocol type is grpc, the url will not contain a scheme."""


@dataclasses.dataclass(frozen=True)
class TracingProviderAppData:
    """Application databag model for the tracing provider."""

    receivers: List[Receiver]
    """List of all receivers enabled on the tracing provider."""

    @classmethod
    def load(cls, databag: MutableMapping[str, str]) -> 'TracingProviderAppData':
        """Load this model from a Juju databag."""
        return _databag_load(cls, databag)

    def dump(
        self, databag: Optional[MutableMapping[str, str]] = None, clear: bool = True
    ) -> MutableMapping[str, str]:
        """Write the contents of this model to a Juju databag."""
        return _databag_dump(self, databag, clear)


@dataclasses.dataclass(frozen=True)
class TracingRequirerAppData:
    """Application databag model for the tracing requirer."""

    receivers: List[ReceiverProtocol]
    """Requested receivers."""

    @classmethod
    def load(cls, databag: MutableMapping[str, str]) -> 'TracingRequirerAppData':
        """Load this model from a Juju databag."""
        return _databag_load(cls, databag)

    def dump(
        self, databag: Optional[MutableMapping[str, str]] = None, clear: bool = True
    ) -> MutableMapping[str, str]:
        """Write the contents of this model to a Juju databag."""
        return _databag_dump(self, databag, clear)


class _AutoSnapshotEvent(RelationEvent):
    __args__: ClassVar[Tuple[str, ...]] = ()
    __optional_kwargs__: ClassVar[Dict[str, Any]] = {}

    @classmethod
    def __attrs__(cls):
        return cls.__args__ + tuple(cls.__optional_kwargs__.keys())

    def __init__(self, handle, relation, *args, **kwargs):
        super().__init__(handle, relation)

        if not len(self.__args__) == len(args):
            raise TypeError(f'expected {len(self.__args__)} args, got {len(args)}')

        for attr, obj in zip(self.__args__, args):
            setattr(self, attr, obj)
        for attr, default in self.__optional_kwargs__.items():
            obj = kwargs.get(attr, default)
            setattr(self, attr, obj)

    def snapshot(self) -> dict:
        dct = super().snapshot()
        for attr in self.__attrs__():
            obj = getattr(self, attr)
            try:
                dct[attr] = obj
            except ValueError as e:
                raise ValueError(
                    f'cannot automagically serialize {obj}: '
                    'override this method and do it '
                    'manually.'
                ) from e

        return dct

    def restore(self, snapshot: dict) -> None:
        super().restore(snapshot)
        for attr, obj in snapshot.items():
            setattr(self, attr, obj)


class EndpointRemovedEvent(RelationBrokenEvent):
    """Event representing a change in one of the receiver endpoints."""


class EndpointChangedEvent(_AutoSnapshotEvent):
    """Event representing a change in one of the receiver endpoints."""

    __args__ = ('_receivers',)

    if TYPE_CHECKING:
        _receivers = []  # type: List[dict]


class TracingEndpointRequirerEvents(CharmEvents):
    """TracingEndpointRequirer events."""

    endpoint_changed = EventSource(EndpointChangedEvent)
    endpoint_removed = EventSource(EndpointRemovedEvent)


class TracingEndpointRequirer(Object):
    """A tracing endpoint for Tempo."""

    on = TracingEndpointRequirerEvents()  # type: ignore

    def __init__(
        self,
        charm: CharmBase,
        relation_name: str = DEFAULT_RELATION_NAME,
        protocols: Optional[List[ReceiverProtocol]] = None,
    ):
        """Construct a tracing requirer for a Tempo charm.

        If your application supports pushing traces to a distributed tracing backend, the
        `TracingEndpointRequirer` object enables your charm to easily access endpoint information
        exchanged over a `tracing` relation interface.

        Args:
            charm: a `CharmBase` object that manages this
                `TracingEndpointRequirer` object. Typically, this is `self` in the instantiating
                class.
            relation_name: an optional string name of the relation between `charm`
                and the Tempo charmed service. The default is "tracing". It is strongly
                advised not to change the default, so that people deploying your charm will have a
                consistent experience with all other charms that provide tracing endpoints.
            protocols: optional list of protocols that the charm intends to send traces with.
                The provider will enable receivers for these and only these protocols,
                so be sure to enable all protocols the charm or its workload are going to need.
        """
        super().__init__(charm, f'internal: {relation_name}')

        self._is_single_endpoint = charm.meta.relations[relation_name].limit == 1

        self._charm = charm
        self._relation_name = relation_name

        events = self._charm.on[self._relation_name]
        self.framework.observe(events.relation_changed, self._on_tracing_relation_changed)
        self.framework.observe(events.relation_broken, self._on_tracing_relation_broken)

        if protocols:
            self.request_protocols(protocols)

    def request_protocols(
        self, protocols: Sequence[ReceiverProtocol], relation: Optional[Relation] = None
    ):
        """Publish the list of protocols which the provider should activate."""
        # todo: should we check if _is_single_endpoint and len(self.relations) > 1 and raise, here?
        relations = [relation] if relation else self.relations

        if not protocols:
            # empty sequence
            raise ValueError(
                'You need to pass a nonempty sequence of protocols to `request_protocols`.'
            )

        try:
            if self._charm.unit.is_leader():
                for relation in relations:
                    TracingRequirerAppData(
                        receivers=list(protocols),
                    ).dump(relation.data[self._charm.app])

        except ModelError as e:
            # args are bytes
            msg = e.args[0]
            if isinstance(msg, bytes) and msg.startswith(
                b'ERROR cannot read relation application settings: permission denied'
            ):
                logger.error(
                    f'encountered error {e} while attempting to request_protocols.'
                    f'The relation must be gone.'
                )
                return
            raise

    @property
    def relations(self) -> List[Relation]:
        """The tracing relations associated with this endpoint."""
        return self._charm.model.relations[self._relation_name]

    @property
    def _relation(self) -> Optional[Relation]:
        """If this wraps a single endpoint, the relation bound to it, if any."""
        if not self._is_single_endpoint:
            objname = type(self).__name__
            raise AmbiguousRelationUsageError(
                f'This {objname} wraps a {self._relation_name} endpoint that has '
                "limit != 1. We can't determine what relation, of the possibly many, you are "
                f'talking about. Please pass a relation instance while calling {objname}, '
                'or set limit=1 in the charm metadata.'
            )
        relations = self.relations
        return relations[0] if relations else None

    def is_ready(self, relation: Optional[Relation] = None):
        """Return whether this endpoint is ready."""
        relation = relation or self._relation
        if not relation:
            logger.debug(f'no relation on {self._relation_name!r}: tracing not ready')
            return False
        if relation.data is None:
            logger.error(f'relation data is None for {relation}')
            return False
        if not relation.app:
            logger.error(f'{relation} event received but there is no relation.app')
            return False
        try:
            databag = dict(relation.data[relation.app])
            TracingProviderAppData.load(databag)

        except (json.JSONDecodeError, DataValidationError):
            logger.info(f'failed validating relation data for {relation}')
            return False
        return True

    def _on_tracing_relation_changed(self, event):
        """Notify the providers that there is new endpoint information available."""
        relation = event.relation
        if not self.is_ready(relation):
            self.on.endpoint_removed.emit(relation)  # type: ignore
            return

        data = TracingProviderAppData.load(relation.data[relation.app])
        self.on.endpoint_changed.emit(relation, [_json_safe(i) for i in data.receivers])  # type: ignore

    def _on_tracing_relation_broken(self, event: RelationBrokenEvent):
        """Notify the providers that the endpoint is broken."""
        relation = event.relation
        self.on.endpoint_removed.emit(relation)  # type: ignore

    def get_all_endpoints(
        self, relation: Optional[Relation] = None
    ) -> Optional[TracingProviderAppData]:
        """Unmarshalled relation data."""
        relation = relation or self._relation
        if not self.is_ready(relation):
            return
        return TracingProviderAppData.load(relation.data[relation.app])  # type: ignore

    def _get_endpoint(
        self, relation: Optional[Relation], protocol: ReceiverProtocol
    ) -> Optional[str]:
        app_data = self.get_all_endpoints(relation)
        if not app_data:
            return None
        receivers: List[Receiver] = list(
            filter(lambda i: i.protocol.name == protocol, app_data.receivers)
        )
        if not receivers:
            # It can happen if the charm requests tracing protocols, but the relay (such as
            # grafana-agent) isn't yet connected to the tracing backend. In this case, it's not
            # an error the charm author can do anything about.
            logger.warning(f'no receiver found with protocol={protocol!r}.')
            return
        if len(receivers) > 1:
            # If we have more than 1 receiver that matches, it shouldn't matter which receiver
            # we'll be using.
            logger.warning(
                f'too many receivers with protocol={protocol!r}; using first one.'
                f' Found: {receivers}'
            )

        receiver = receivers[0]
        return receiver.url

    def get_endpoint(
        self, protocol: ReceiverProtocol, relation: Optional[Relation] = None
    ) -> Optional[str]:
        """Receiver endpoint for the given protocol.

        It could happen that this function gets called before the provider publishes the
        endpoints. In such a scenario, if a non-leader unit calls this function, a permission
        denied exception will be raised due to restricted access. To prevent this, this function
        needs to be guarded by the `is_ready` check.

        Raises:
        ProtocolNotRequestedError:
            If the charm unit is the leader unit and attempts to obtain an endpoint for a
            protocol it did not request.
        """
        endpoint = self._get_endpoint(relation or self._relation, protocol=protocol)
        if not endpoint:
            requested_protocols = set()
            relations = [relation] if relation else self.relations
            for relation in relations:
                try:
                    databag = TracingRequirerAppData.load(relation.data[self._charm.app])
                except DataValidationError:
                    continue

                requested_protocols.update(databag.receivers)

            if protocol not in requested_protocols:
                raise ProtocolNotRequestedError(protocol, relation)

            return None
        return endpoint
