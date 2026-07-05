# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Requirer-side models for the ``tracing`` and ``certificate_transfer`` relation interfaces.

Schemas:
- https://canonical.com/juju/docs/charmlibs/reference/interfaces/tracing/v2/
- https://canonical.com/juju/docs/charmlibs/reference/interfaces/certificate_transfer/v1/
"""

import dataclasses
import enum
from typing import List, Literal, Optional, Set

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


@dataclasses.dataclass(frozen=True)
class TracingRequirerAppData:
    """Application databag model for the tracing requirer."""

    receivers: List[ReceiverProtocol]
    """Requested receivers."""


@dataclasses.dataclass(frozen=True)
class CertificateTransferProviderAppData:
    """Application databag model for the certificate_transfer provider."""

    certificates: Set[str]
    """PEM-encoded certificates and/or CA certificates published by the provider."""


@dataclasses.dataclass(frozen=True)
class CertificateTransferProviderUnitDataV0:
    """Unit databag model for the certificate_transfer provider (v0 fallback).

    A v0 provider publishes a single CA plus certificate on the unit databag,
    with the full chain under ``chain``. A dual v0/v1 provider falls back to
    this shape when the requirer does not advertise ``version=1``.
    """

    ca: str
    certificate: str
    chain: Optional[List[str]] = None


@dataclasses.dataclass(frozen=True)
class CertificateTransferRequirerAppData:
    """Application databag model for the certificate_transfer requirer.

    Advertises the interface version we speak so a dual v0/v1 provider knows
    to publish v1 (app databag ``certificates``) rather than v0 (unit databag).
    """

    version: int = 1
