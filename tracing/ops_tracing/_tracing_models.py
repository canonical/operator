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
from typing import (
    List,
    Literal,
    MutableMapping,
    Optional,
    Sequence,
)

import ops

from . import _databag

logger = logging.getLogger(__name__)

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
        return _databag.load(cls, databag, DataValidationError)


@dataclasses.dataclass(frozen=True)
class TracingRequirerAppData:
    """Application databag model for the tracing requirer."""

    receivers: List[ReceiverProtocol]
    """Requested receivers."""

    @classmethod
    def load(cls, databag: MutableMapping[str, str]) -> 'TracingRequirerAppData':
        """Load this model from a Juju databag."""
        return _databag.load(cls, databag, DataValidationError)


class EndpointRemovedEvent(ops.RelationBrokenEvent):
    """Event representing a change in one of the receiver endpoints."""


class EndpointChangedEvent(ops.RelationEvent):
    """Event representing a change in one of the receiver endpoints."""


class TracingEndpointRequirerEvents(ops.CharmEvents):
    """TracingEndpointRequirer events."""

    endpoint_changed = ops.EventSource(EndpointChangedEvent)
    endpoint_removed = ops.EventSource(EndpointRemovedEvent)


class TracingEndpointRequirer(ops.Object):
    """A tracing endpoint for Tempo."""

    on = TracingEndpointRequirerEvents()  # type: ignore

    def __init__(
        self,
        charm: ops.CharmBase,
        relation_name: str = 'tracing',
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

    def request_protocols(self, protocols: Sequence[ReceiverProtocol]):
        """Publish the list of protocols which the provider should activate."""
        if not protocols:
            # empty sequence
            raise ValueError(
                'You need to pass a nonempty sequence of protocols to `request_protocols`.'
            )

        try:
            if self._charm.unit.is_leader():
                data = TracingRequirerAppData(receivers=list(protocols))
                for relation in self.relations:
                    relation.save(data, self._charm.app)

        except ops.ModelError as e:
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
    def relations(self) -> List[ops.Relation]:
        """The tracing relations associated with this endpoint."""
        return self._charm.model.relations[self._relation_name]

    @property
    def _relation(self) -> Optional[ops.Relation]:
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

    def is_ready(self, relation: Optional[ops.Relation] = None):
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
        self.on.endpoint_changed.emit(relation)  # type: ignore

    def _on_tracing_relation_broken(self, event: ops.RelationBrokenEvent):
        """Notify the providers that the endpoint is broken."""
        relation = event.relation
        self.on.endpoint_removed.emit(relation)  # type: ignore

    def _get_all_endpoints(
        self, relation: Optional[ops.Relation] = None
    ) -> Optional[TracingProviderAppData]:
        """Unmarshalled relation data."""
        relation = relation or self._relation
        if not self.is_ready(relation):
            return
        return TracingProviderAppData.load(relation.data[relation.app])  # type: ignore

    def _get_endpoint(
        self, relation: Optional[ops.Relation], protocol: ReceiverProtocol
    ) -> Optional[str]:
        app_data = self._get_all_endpoints(relation)
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

    def get_endpoint(self, protocol: ReceiverProtocol) -> Optional[str]:
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
        endpoint = self._get_endpoint(self._relation, protocol=protocol)
        if not endpoint:
            requested_protocols: set[ReceiverProtocol] = set()
            for relation in self.relations:
                try:
                    databag = TracingRequirerAppData.load(relation.data[self._charm.app])
                except DataValidationError:
                    continue

                requested_protocols.update(databag.receivers)

            if protocol not in requested_protocols:
                raise ProtocolNotRequestedError(protocol)

            return None
        return endpoint
