# Copyright 2025 Canonical Ltd.
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

from __future__ import annotations

import dataclasses
import datetime
import pathlib
from collections.abc import Sequence
from typing import (
    TYPE_CHECKING,
    Any,
    Literal,
    TypeAlias,
    TypedDict,
)

from .._private import timeconv

SecretRotate = Literal['never', 'hourly', 'daily', 'weekly', 'monthly', 'quarterly', 'yearly']
SettableStatusName = Literal['active', 'blocked', 'maintenance', 'waiting']
ReadOnlyStatusName = Literal['error', 'unknown']
StatusName: TypeAlias = SettableStatusName | ReadOnlyStatusName


if TYPE_CHECKING:
    from typing_extensions import NotRequired

    class AddressDict(TypedDict, total=False):
        hostname: str
        address: str  # Juju < 2.9
        value: str  # Juju >= 2.9
        cidr: str

    BindAddressDict = TypedDict(
        'BindAddressDict',
        {
            'mac-address': NotRequired[str],
            'interface-name': str,
            'addresses': list[AddressDict] | None,
        },
    )


@dataclasses.dataclass(frozen=True, kw_only=True)
class Address:
    """A Juju space address, found in :class:`BindAddress` objects."""

    hostname: str
    # These may be IP addresses or hostnames, so we keep things simple and use
    # str, and leave it to users to convert them to ipaddress types if needed.
    # See #818 for more information.
    value: str
    cidr: str

    @classmethod
    def _from_dict(cls, d: AddressDict) -> Address:
        return cls(
            hostname=d.get('hostname', ''),
            value=d.get('value', d.get('address', '')),
            cidr=d.get('cidr', ''),
        )


@dataclasses.dataclass(frozen=True, kw_only=True)
class BindAddress:
    """A Juju space bind address, found in :class:`Network` objects."""

    mac_address: str
    interface_name: str
    addresses: list[Address] = dataclasses.field(default_factory=list[Address])

    @classmethod
    def _from_dict(cls, d: BindAddressDict) -> BindAddress:
        addresses = [Address._from_dict(addr) for addr in d.get('addresses') or []]
        return cls(
            mac_address=d.get('mac-address', ''),
            interface_name=d.get('interface-name', ''),
            addresses=addresses,
        )


@dataclasses.dataclass(frozen=True, kw_only=True)
class CloudCredential:
    """Credentials for cloud.

    Used as the type of attribute `credential` in :class:`CloudSpec`.
    """

    auth_type: str
    """Authentication type."""

    attributes: dict[str, str] = dataclasses.field(default_factory=dict[str, str])
    """A dictionary containing cloud credentials.

    For example, for AWS, it contains `access-key` and `secret-key`;
    for Azure, `application-id`, `application-password` and `subscription-id`
    can be found here.
    """

    redacted: list[str] = dataclasses.field(default_factory=list[str])
    """A list of redacted secrets."""

    @classmethod
    def _from_dict(cls, d: dict[str, Any]) -> CloudCredential:
        """Create a new CloudCredential object from a dictionary."""
        return cls(
            auth_type=d['auth-type'],
            attributes=d.get('attrs') or {},
            redacted=d.get('redacted') or [],
        )


@dataclasses.dataclass(frozen=True, kw_only=True)
class CloudSpec:
    """Cloud specification information (metadata) including credentials."""

    type: str
    """Type of the cloud."""

    name: str
    """Juju cloud name."""

    region: str | None = None
    """Region of the cloud."""

    endpoint: str | None = None
    """Endpoint of the cloud."""

    identity_endpoint: str | None = None
    """Identity endpoint of the cloud."""

    storage_endpoint: str | None = None
    """Storage endpoint of the cloud."""

    credential: CloudCredential | None = None
    """Cloud credentials with key-value attributes."""

    ca_certificates: list[str] = dataclasses.field(default_factory=list[str])
    """A list of CA certificates."""

    skip_tls_verify: bool = False
    """Whether to skip TLS verification."""

    is_controller_cloud: bool = False
    """If this is the cloud used by the controller, defaults to ``False``."""

    @classmethod
    def _from_dict(cls, d: dict[str, Any]) -> CloudSpec:
        """Create a new CloudSpec object from a dict parsed from JSON."""
        return cls(
            type=d['type'],
            name=d['name'],
            region=d.get('region') or None,
            endpoint=d.get('endpoint') or None,
            identity_endpoint=d.get('identity-endpoint') or None,
            storage_endpoint=d.get('storage-endpoint') or None,
            credential=CloudCredential._from_dict(d['credential'])
            if d.get('credential')
            else None,
            ca_certificates=d.get('cacertificates') or [],
            skip_tls_verify=d.get('skip-tls-verify') or False,
            is_controller_cloud=d.get('is-controller-cloud') or False,
        )


class GoalDict(TypedDict):
    status: str
    since: str


class GoalStateDict(TypedDict):
    units: dict[str, GoalDict]
    relations: dict[str, dict[str, GoalDict]]


@dataclasses.dataclass(frozen=True, kw_only=True)
class Goal:
    """A goal status and when it was last updated, found in :class:`GoalState` objects."""

    status: str
    since: datetime.datetime

    @classmethod
    def _from_dict(cls, d: GoalDict) -> Goal:
        return cls(
            status=d['status'],
            since=timeconv.parse_rfc3339(d['since']),
        )


@dataclasses.dataclass(frozen=True, kw_only=True)
class GoalState:
    """The units and relations that the model should have, and the status of achieving that."""

    units: dict[str, Goal]
    # The top key is the endpoint/relation name, the second key is the app/unit name.
    relations: dict[str, dict[str, Goal]]

    @classmethod
    def _from_dict(cls, d: GoalStateDict) -> GoalState:
        units: dict[str, Goal] = {
            name: Goal._from_dict(unit) for name, unit in d.get('units', {}).items()
        }
        relations: dict[str, dict[str, Goal]] = {}
        for name, relation in d.get('relations', {}).items():
            goals: dict[str, Goal] = {
                app_or_unit: Goal._from_dict(data) for app_or_unit, data in relation.items()
            }
            relations[name] = goals
        return cls(units=units, relations=relations)


@dataclasses.dataclass(frozen=True, kw_only=True)
class Network:
    """A Juju space."""

    bind_addresses: Sequence[BindAddress]
    # These may be IP addresses or hostnames, so we keep things simple and use
    # str, and leave it to users to convert them to ipaddress types if needed.
    # See #818 for more information.
    egress_subnets: Sequence[str]
    ingress_addresses: Sequence[str]

    @classmethod
    def _from_dict(cls, d: dict[str, Any]) -> Network:
        bind_dicts: list[BindAddressDict] = d.get('bind-addresses', [])
        bind = [BindAddress._from_dict(bind_dict) for bind_dict in bind_dicts]
        egress = d.get('egress-subnets', [])
        ingress = d.get('ingress-addresses', [])
        return cls(bind_addresses=bind, egress_subnets=egress, ingress_addresses=ingress)


# Note that we intend to merge this with model.py's `Port` in the future, and
# that does not have `kw_only=True`. That means that we should not use it here,
# either, so that merging can be backwards compatible.
@dataclasses.dataclass(frozen=True)
class Port:
    """A port that Juju has opened for the charm."""

    protocol: Literal['tcp', 'udp', 'icmp'] | None = 'tcp'
    """The IP protocol."""

    port: int | None = None
    """The port number. Will be ``None`` if protocol is ``'icmp'``."""

    to_port: int | None = None
    """The final port number if this is a range of ports."""

    endpoints: list[str] | None = None
    """The endpoints this port applies to, ``['*']`` if all endpoints, or ``None`` if unknown."""


class RelationModelDict(TypedDict):
    uuid: str


@dataclasses.dataclass(frozen=True, kw_only=True)
class RelationModel:
    """Details of the model on the remote side of the relation."""

    uuid: str

    @classmethod
    def _from_dict(cls, d: RelationModelDict) -> RelationModel:
        return cls(
            uuid=d['uuid'],
        )


@dataclasses.dataclass(frozen=True, kw_only=True)
class SecretInfo:
    """Metadata for Juju secrets."""

    revision: int
    id: str = ''
    label: str = ''
    description: str = ''
    expiry: datetime.datetime | None = None
    rotation: SecretRotate | None = None
    rotates: datetime.datetime | None = None

    @classmethod
    def _from_dict(cls, d: dict[str, Any]) -> SecretInfo:
        id, data = next(iter(d.items()))  # Juju returns dict of {secret_id: {info}}
        return cls(
            id=id,
            label=data.get('label'),
            description=data.get('description'),
            expiry=timeconv.parse_rfc3339(data['expiry']) if data.get('expiry') else None,
            rotation=data.get('rotation'),
            rotates=timeconv.parse_rfc3339(data['rotates']) if data.get('rotates') else None,
            revision=data['revision'],
        )


@dataclasses.dataclass(frozen=True, kw_only=True)
class Storage:
    """Metadata for Juju storage."""

    kind: str
    location: pathlib.Path

    @classmethod
    def _from_dict(cls, d: dict[str, Any]) -> Storage:
        return cls(
            kind=d['kind'],
            location=pathlib.Path(d['location']),
        )


StatusDict = TypedDict(
    'StatusDict', {'message': str, 'status': str, 'status-data': dict[str, Any]}
)
AppStatusDict = TypedDict(
    'AppStatusDict',
    {
        'application-status': StatusDict,
        'units': dict[str, StatusDict],
    },
)


@dataclasses.dataclass(frozen=True, kw_only=True)
class UnitStatus:
    """The status of a Juju unit."""

    status: str = ''
    message: str = ''
    status_data: dict[str, Any]

    @classmethod
    def _from_dict(cls, d: StatusDict) -> UnitStatus:
        return cls(
            status=d['status'],
            message=d['message'],
            status_data=d['status-data'],
        )


@dataclasses.dataclass(frozen=True, kw_only=True)
class AppStatus:
    """The status of a Juju application."""

    status: str = ''
    message: str = ''
    status_data: dict[str, Any]
    units: dict[str, UnitStatus]

    @classmethod
    def _from_dict(cls, d: AppStatusDict) -> AppStatus:
        units = {name: UnitStatus._from_dict(u) for name, u in d.get('units', {}).items()}
        app = d['application-status']
        return cls(
            status=app['status'],
            message=app['message'],
            status_data=app['status-data'],
            units=units,
        )
