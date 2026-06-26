# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Requirer-side models for the ``tracing`` relation interface.

Schema: https://canonical.com/juju/docs/charmlibs/reference/interfaces/tracing/v2/
"""

import dataclasses
import enum
from typing import List, Literal, MutableMapping

from . import _databag

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


class DataValidationError(Exception):
    """Raised when data validation fails on tracing relation data."""


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
