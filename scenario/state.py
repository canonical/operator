#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""The core Scenario State object, and the components inside it."""

import copy
import dataclasses
import datetime
import inspect
import re
import warnings
from collections import namedtuple
from enum import Enum
from itertools import chain
from pathlib import Path, PurePosixPath
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    Generic,
    List,
    Literal,
    Optional,
    Set,
    Tuple,
    Type,
    TypeVar,
    Union,
    cast,
)
from uuid import uuid4

import ops
import yaml
from ops import pebble
from ops.charm import CharmBase, CharmEvents
from ops.model import SecretRotate, StatusBase

from scenario.logger import logger as scenario_logger

JujuLogLine = namedtuple("JujuLogLine", ("level", "message"))

if TYPE_CHECKING:  # pragma: no cover
    try:
        from typing import Self  # type: ignore
    except ImportError:
        from typing_extensions import Self

    from scenario import Context

PathLike = Union[str, Path]
AnyRelation = Union["Relation", "PeerRelation", "SubordinateRelation"]
AnyJson = Union[str, bool, dict, int, float, list]
RawSecretRevisionContents = RawDataBagContents = Dict[str, str]
UnitID = int

CharmType = TypeVar("CharmType", bound=CharmBase)

logger = scenario_logger.getChild("state")

ATTACH_ALL_STORAGES = "ATTACH_ALL_STORAGES"
CREATE_ALL_RELATIONS = "CREATE_ALL_RELATIONS"
BREAK_ALL_RELATIONS = "BREAK_ALL_RELATIONS"
DETACH_ALL_STORAGES = "DETACH_ALL_STORAGES"

ACTION_EVENT_SUFFIX = "_action"
# all builtin events except secret events. They're special because they carry secret metadata.
BUILTIN_EVENTS = {
    "start",
    "stop",
    "install",
    "install",
    "start",
    "stop",
    "remove",
    "update_status",
    "config_changed",
    "upgrade_charm",
    "pre_series_upgrade",
    "post_series_upgrade",
    "leader_elected",
    "leader_settings_changed",
    "collect_metrics",
}
FRAMEWORK_EVENTS = {
    "pre_commit",
    "commit",
    "collect_app_status",
    "collect_unit_status",
}
PEBBLE_READY_EVENT_SUFFIX = "_pebble_ready"
PEBBLE_CUSTOM_NOTICE_EVENT_SUFFIX = "_pebble_custom_notice"
RELATION_EVENTS_SUFFIX = {
    "_relation_changed",
    "_relation_broken",
    "_relation_joined",
    "_relation_departed",
    "_relation_created",
}
STORAGE_EVENTS_SUFFIX = {
    "_storage_detaching",
    "_storage_attached",
}

SECRET_EVENTS = {
    "secret_changed",
    "secret_remove",
    "secret_rotate",
    "secret_expired",
}

META_EVENTS = {
    "CREATE_ALL_RELATIONS": "_relation_created",
    "BREAK_ALL_RELATIONS": "_relation_broken",
    "DETACH_ALL_STORAGES": "_storage_detaching",
    "ATTACH_ALL_STORAGES": "_storage_attached",
}


class StateValidationError(RuntimeError):
    """Raised when individual parts of the State are inconsistent."""

    # as opposed to InconsistentScenario error where the
    # **combination** of several parts of the State are.


class MetadataNotFoundError(RuntimeError):
    """Raised when Scenario can't find a metadata.yaml file in the provided charm root."""


class BindFailedError(RuntimeError):
    """Raised when Event.bind fails."""


@dataclasses.dataclass(frozen=True)
class _DCBase:
    def replace(self, *args, **kwargs):
        """Produce a deep copy of this class, with some arguments replaced with new ones."""
        return dataclasses.replace(self.copy(), *args, **kwargs)

    def copy(self) -> "Self":
        """Produce a deep copy of this object."""
        return copy.deepcopy(self)


@dataclasses.dataclass(frozen=True)
class CloudCredential:
    auth_type: str
    """Authentication type."""

    attributes: Dict[str, str] = dataclasses.field(default_factory=dict)
    """A dictionary containing cloud credentials.
    For example, for AWS, it contains `access-key` and `secret-key`;
    for Azure, `application-id`, `application-password` and `subscription-id`
    can be found here.
    """

    redacted: List[str] = dataclasses.field(default_factory=list)
    """A list of redacted generic cloud API secrets."""

    def _to_ops(self) -> ops.CloudCredential:
        return ops.CloudCredential(
            auth_type=self.auth_type,
            attributes=self.attributes,
            redacted=self.redacted,
        )


@dataclasses.dataclass(frozen=True)
class CloudSpec:
    type: str
    """Type of the cloud."""

    name: str = "localhost"
    """Juju cloud name."""

    region: Optional[str] = None
    """Region of the cloud."""

    endpoint: Optional[str] = None
    """Endpoint of the cloud."""

    identity_endpoint: Optional[str] = None
    """Identity endpoint of the cloud."""

    storage_endpoint: Optional[str] = None
    """Storage endpoint of the cloud."""

    credential: Optional[CloudCredential] = None
    """Cloud credentials with key-value attributes."""

    ca_certificates: List[str] = dataclasses.field(default_factory=list)
    """A list of CA certificates."""

    skip_tls_verify: bool = False
    """Whether to skip TLS verfication."""

    is_controller_cloud: bool = False
    """If this is the cloud used by the controller."""

    def _to_ops(self) -> ops.CloudSpec:
        return ops.CloudSpec(
            type=self.type,
            name=self.name,
            region=self.region,
            endpoint=self.endpoint,
            identity_endpoint=self.identity_endpoint,
            storage_endpoint=self.storage_endpoint,
            credential=self.credential._to_ops() if self.credential else None,
            ca_certificates=self.ca_certificates,
            skip_tls_verify=self.skip_tls_verify,
            is_controller_cloud=self.is_controller_cloud,
        )


@dataclasses.dataclass(frozen=True)
class Secret(_DCBase):
    id: str
    # CAUTION: ops-created Secrets (via .add_secret()) will have a canonicalized
    #  secret id (`secret:` prefix)
    #  but user-created ones will not. Using post-init to patch it in feels bad, but requiring the user to
    #  add the prefix manually every time seems painful as well.

    # mapping from revision IDs to each revision's contents
    contents: Dict[int, "RawSecretRevisionContents"]

    # indicates if the secret is owned by THIS unit, THIS app or some other app/unit.
    # if None, the implication is that the secret has been granted to this unit.
    owner: Literal["unit", "app", None] = None

    # deprecated! if a secret is not granted to this unit, omit it from State.secrets altogether.
    # this attribute will be removed in Scenario 7+
    granted: Any = "<DEPRECATED>"  # noqa

    # what revision is currently tracked by this charm. Only meaningful if owner=False
    revision: int = 0

    # mapping from relation IDs to remote unit/apps to which this secret has been granted.
    # Only applicable if owner
    remote_grants: Dict[int, Set[str]] = dataclasses.field(default_factory=dict)

    label: Optional[str] = None
    description: Optional[str] = None
    expire: Optional[datetime.datetime] = None
    rotate: Optional[SecretRotate] = None

    def __post_init__(self):
        if self.granted != "<DEPRECATED>":
            msg = (
                "``state.Secret.granted`` is deprecated and will be removed in Scenario 7+. "
                "If a Secret is not owned by the app/unit you are testing, nor has been granted to "
                "it by the (remote) owner, then omit it from ``State.secrets`` altogether."
            )
            logger.warning(msg)
            warnings.warn(msg, DeprecationWarning, stacklevel=2)

        if self.owner == "application":
            msg = (
                "Secret.owner='application' is deprecated in favour of 'app' "
                "and will be removed in Scenario 7+."
            )
            logger.warning(msg)
            warnings.warn(msg, DeprecationWarning, stacklevel=2)

            # bypass frozen dataclass
            object.__setattr__(self, "owner", "app")

    # consumer-only events
    @property
    def changed_event(self):
        """Sugar to generate a secret-changed event."""
        if self.owner:
            raise ValueError(
                "This unit will never receive secret-changed for a secret it owns.",
            )
        return Event("secret_changed", secret=self)

    # owner-only events
    @property
    def rotate_event(self):
        """Sugar to generate a secret-rotate event."""
        if not self.owner:
            raise ValueError(
                "This unit will never receive secret-rotate for a secret it does not own.",
            )
        return Event("secret_rotate", secret=self)

    @property
    def expired_event(self):
        """Sugar to generate a secret-expired event."""
        if not self.owner:
            raise ValueError(
                "This unit will never receive secret-expired for a secret it does not own.",
            )
        return Event("secret_expired", secret=self)

    @property
    def remove_event(self):
        """Sugar to generate a secret-remove event."""
        if not self.owner:
            raise ValueError(
                "This unit will never receive secret-remove for a secret it does not own.",
            )
        return Event("secret_remove", secret=self)

    def _set_revision(self, revision: int):
        """Set a new tracked revision."""
        # bypass frozen dataclass
        object.__setattr__(self, "revision", revision)

    def _update_metadata(
        self,
        content: Optional["RawSecretRevisionContents"] = None,
        label: Optional[str] = None,
        description: Optional[str] = None,
        expire: Optional[datetime.datetime] = None,
        rotate: Optional[SecretRotate] = None,
    ):
        """Update the metadata."""
        revision = max(self.contents.keys())
        if content:
            self.contents[revision + 1] = content

        # bypass frozen dataclass
        if label:
            object.__setattr__(self, "label", label)
        if description:
            object.__setattr__(self, "description", description)
        if expire:
            if isinstance(expire, datetime.timedelta):
                expire = datetime.datetime.now() + expire
            object.__setattr__(self, "expire", expire)
        if rotate:
            object.__setattr__(self, "rotate", rotate)


def normalize_name(s: str):
    """Event names, in Scenario, uniformly use underscores instead of dashes."""
    return s.replace("-", "_")


@dataclasses.dataclass(frozen=True)
class Address(_DCBase):
    """An address in a Juju network space."""

    hostname: str
    """A host name that maps to the address in :attr:`value`."""
    value: str
    """The IP address in the space."""
    cidr: str
    """The CIDR of the address in :attr:`value`."""

    @property
    def address(self):
        """A deprecated alias for :attr:`value`."""
        return self.value

    @address.setter
    def address(self, value):
        object.__setattr__(self, "value", value)


@dataclasses.dataclass(frozen=True)
class BindAddress(_DCBase):
    """An address bound to a network interface in a Juju space."""

    interface_name: str
    addresses: List[Address]
    mac_address: Optional[str] = None

    def hook_tool_output_fmt(self):
        # dumps itself to dict in the same format the hook tool would
        # todo support for legacy (deprecated) `interfacename` and `macaddress` fields?
        dct = {
            "interface-name": self.interface_name,
            "addresses": [dataclasses.asdict(addr) for addr in self.addresses],
        }
        if self.mac_address:
            dct["mac-address"] = self.mac_address
        return dct


@dataclasses.dataclass(frozen=True)
class Network(_DCBase):
    bind_addresses: List[BindAddress]
    ingress_addresses: List[str]
    egress_subnets: List[str]

    def hook_tool_output_fmt(self):
        # dumps itself to dict in the same format the hook tool would
        return {
            "bind-addresses": [ba.hook_tool_output_fmt() for ba in self.bind_addresses],
            "egress-subnets": self.egress_subnets,
            "ingress-addresses": self.ingress_addresses,
        }

    @classmethod
    def default(
        cls,
        private_address: str = "192.0.2.0",
        hostname: str = "",
        cidr: str = "",
        interface_name: str = "",
        mac_address: Optional[str] = None,
        egress_subnets=("192.0.2.0/24",),
        ingress_addresses=("192.0.2.0",),
    ) -> "Network":
        """Helper to create a minimal, heavily defaulted Network."""
        return cls(
            bind_addresses=[
                BindAddress(
                    interface_name=interface_name,
                    mac_address=mac_address,
                    addresses=[
                        Address(hostname=hostname, value=private_address, cidr=cidr),
                    ],
                ),
            ],
            egress_subnets=list(egress_subnets),
            ingress_addresses=list(ingress_addresses),
        )


_next_relation_id_counter = 1


def next_relation_id(update=True):
    global _next_relation_id_counter
    cur = _next_relation_id_counter
    if update:
        _next_relation_id_counter += 1
    return cur


@dataclasses.dataclass(frozen=True)
class RelationBase(_DCBase):
    endpoint: str
    """Relation endpoint name. Must match some endpoint name defined in metadata.yaml."""

    interface: Optional[str] = None
    """Interface name. Must match the interface name attached to this endpoint in metadata.yaml.
    If left empty, it will be automatically derived from metadata.yaml."""

    relation_id: int = dataclasses.field(default_factory=next_relation_id)
    """Juju relation ID. Every new Relation instance gets a unique one,
    if there's trouble, override."""

    local_app_data: "RawDataBagContents" = dataclasses.field(default_factory=dict)
    """This application's databag for this relation."""

    local_unit_data: "RawDataBagContents" = dataclasses.field(
        default_factory=lambda: DEFAULT_JUJU_DATABAG.copy(),
    )
    """This unit's databag for this relation."""

    @property
    def _databags(self):
        """Yield all databags in this relation."""
        yield self.local_app_data
        yield self.local_unit_data

    @property
    def _remote_unit_ids(self) -> Tuple["UnitID", ...]:
        """Ids of the units on the other end of this relation."""
        raise NotImplementedError()

    def _get_databag_for_remote(
        self,
        unit_id: int,  # noqa: U100
    ) -> "RawDataBagContents":
        """Return the databag for some remote unit ID."""
        raise NotImplementedError()

    def __post_init__(self):
        if type(self) is RelationBase:
            raise RuntimeError(
                "RelationBase cannot be instantiated directly; "
                "please use Relation, PeerRelation, or SubordinateRelation",
            )

        for databag in self._databags:
            self._validate_databag(databag)

    def _validate_databag(self, databag: dict):
        if not isinstance(databag, dict):
            raise StateValidationError(
                f"all databags should be dicts, not {type(databag)}",
            )
        for v in databag.values():
            if not isinstance(v, str):
                raise StateValidationError(
                    f"all databags should be Dict[str,str]; "
                    f"found a value of type {type(v)}",
                )

    @property
    def changed_event(self) -> "Event":
        """Sugar to generate a <this relation>-relation-changed event."""
        return Event(
            path=normalize_name(self.endpoint + "-relation-changed"),
            relation=cast("AnyRelation", self),
        )

    @property
    def joined_event(self) -> "Event":
        """Sugar to generate a <this relation>-relation-joined event."""
        return Event(
            path=normalize_name(self.endpoint + "-relation-joined"),
            relation=cast("AnyRelation", self),
        )

    @property
    def created_event(self) -> "Event":
        """Sugar to generate a <this relation>-relation-created event."""
        return Event(
            path=normalize_name(self.endpoint + "-relation-created"),
            relation=cast("AnyRelation", self),
        )

    @property
    def departed_event(self) -> "Event":
        """Sugar to generate a <this relation>-relation-departed event."""
        return Event(
            path=normalize_name(self.endpoint + "-relation-departed"),
            relation=cast("AnyRelation", self),
        )

    @property
    def broken_event(self) -> "Event":
        """Sugar to generate a <this relation>-relation-broken event."""
        return Event(
            path=normalize_name(self.endpoint + "-relation-broken"),
            relation=cast("AnyRelation", self),
        )


_DEFAULT_IP = " 192.0.2.0"
DEFAULT_JUJU_DATABAG = {
    "egress-subnets": _DEFAULT_IP,
    "ingress-address": _DEFAULT_IP,
    "private-address": _DEFAULT_IP,
}


@dataclasses.dataclass(frozen=True)
class Relation(RelationBase):
    """An integration between the charm and another application."""

    remote_app_name: str = "remote"
    """The name of the remote application, as in the charm's metadata."""

    # local limit
    limit: int = 1
    """The maximum number of integrations on this endpoint."""

    remote_app_data: "RawDataBagContents" = dataclasses.field(default_factory=dict)
    """The current content of the application databag."""
    remote_units_data: Dict["UnitID", "RawDataBagContents"] = dataclasses.field(
        default_factory=lambda: {0: DEFAULT_JUJU_DATABAG.copy()},  # dedup
    )
    """The current content of the databag for each unit in the relation."""

    @property
    def _remote_app_name(self) -> str:
        """Who is on the other end of this relation?"""
        return self.remote_app_name

    @property
    def _remote_unit_ids(self) -> Tuple["UnitID", ...]:
        """Ids of the units on the other end of this relation."""
        return tuple(self.remote_units_data)

    def _get_databag_for_remote(self, unit_id: "UnitID") -> "RawDataBagContents":
        """Return the databag for some remote unit ID."""
        return self.remote_units_data[unit_id]

    @property
    def _databags(self):
        """Yield all databags in this relation."""
        yield self.local_app_data
        yield self.local_unit_data
        yield self.remote_app_data
        yield from self.remote_units_data.values()


@dataclasses.dataclass(frozen=True)
class SubordinateRelation(RelationBase):
    remote_app_data: "RawDataBagContents" = dataclasses.field(default_factory=dict)
    remote_unit_data: "RawDataBagContents" = dataclasses.field(
        default_factory=lambda: DEFAULT_JUJU_DATABAG.copy(),
    )

    # app name and ID of the remote unit that *this unit* is attached to.
    remote_app_name: str = "remote"
    remote_unit_id: int = 0

    @property
    def _remote_unit_ids(self) -> Tuple[int]:
        """Ids of the units on the other end of this relation."""
        return (self.remote_unit_id,)

    def _get_databag_for_remote(self, unit_id: int) -> "RawDataBagContents":
        """Return the databag for some remote unit ID."""
        if unit_id is not self.remote_unit_id:
            raise ValueError(
                f"invalid unit id ({unit_id}): subordinate relation only has one "
                f"remote and that has id {self.remote_unit_id}",
            )
        return self.remote_unit_data

    @property
    def _databags(self):
        """Yield all databags in this relation."""
        yield self.local_app_data
        yield self.local_unit_data
        yield self.remote_app_data
        yield self.remote_unit_data

    @property
    def remote_unit_name(self) -> str:
        return f"{self.remote_app_name}/{self.remote_unit_id}"


@dataclasses.dataclass(frozen=True)
class PeerRelation(RelationBase):
    """A relation to share data between units of the charm."""

    peers_data: Dict["UnitID", "RawDataBagContents"] = dataclasses.field(
        default_factory=lambda: {0: DEFAULT_JUJU_DATABAG.copy()},
    )
    """Current contents of the peer databags."""
    # Consistency checks will validate that *this unit*'s ID is not in here.

    @property
    def _databags(self):
        """Yield all databags in this relation."""
        yield self.local_app_data
        yield self.local_unit_data
        yield from self.peers_data.values()

    @property
    def _remote_unit_ids(self) -> Tuple["UnitID", ...]:
        """Ids of the units on the other end of this relation."""
        return tuple(self.peers_data)

    def _get_databag_for_remote(self, unit_id: "UnitID") -> "RawDataBagContents":
        """Return the databag for some remote unit ID."""
        return self.peers_data[unit_id]


def _random_model_name():
    import random
    import string

    space = string.ascii_letters + string.digits
    return "".join(random.choice(space) for _ in range(20))


@dataclasses.dataclass(frozen=True)
class Model(_DCBase):
    """The Juju model in which the charm is deployed."""

    name: str = dataclasses.field(default_factory=_random_model_name)
    """The name of the model."""
    uuid: str = dataclasses.field(default_factory=lambda: str(uuid4()))
    """A unique identifier for the model, typically generated by Juju."""

    # whatever juju models --format=json | jq '.models[<current-model-index>].type' gives back.
    # TODO: make this exhaustive.
    type: Literal["kubernetes", "lxd"] = "kubernetes"
    """The type of Juju model."""

    cloud_spec: Optional[CloudSpec] = None
    """Cloud specification information (metadata) including credentials."""


# for now, proc mock allows you to map one command to one mocked output.
# todo extend: one input -> multiple outputs, at different times


_CHANGE_IDS = 0


def _generate_new_change_id():
    global _CHANGE_IDS
    _CHANGE_IDS += 1
    logger.info(
        f"change ID unset; automatically assigning {_CHANGE_IDS}. "
        f"If there are problems, pass one manually.",
    )
    return _CHANGE_IDS


@dataclasses.dataclass(frozen=True)
class ExecOutput:
    """Mock data for simulated :meth:`ops.Container.exec` calls."""

    return_code: int = 0
    """The return code of the process (0 is success)."""
    stdout: str = ""
    """Any content written to stdout by the process."""
    stderr: str = ""
    """Any content written to stderr by the process."""

    # change ID: used internally to keep track of mocked processes
    _change_id: int = dataclasses.field(default_factory=_generate_new_change_id)

    def _run(self) -> int:
        return self._change_id


_ExecMock = Dict[Tuple[str, ...], ExecOutput]


@dataclasses.dataclass(frozen=True)
class Mount(_DCBase):
    """Maps local files to a :class:`Container` filesystem."""

    location: Union[str, PurePosixPath]
    """The location inside of the container."""
    src: Union[str, Path]
    """The content to provide when the charm does :meth:`ops.Container.pull`."""


def _now_utc():
    return datetime.datetime.now(tz=datetime.timezone.utc)


_next_notice_id_counter = 1


def next_notice_id(update=True):
    global _next_notice_id_counter
    cur = _next_notice_id_counter
    if update:
        _next_notice_id_counter += 1
    return str(cur)


@dataclasses.dataclass(frozen=True)
class Notice(_DCBase):
    key: str
    """The notice key, a string that differentiates notices of this type.

    This is in the format ``domain/path``; for example:
    ``canonical.com/postgresql/backup`` or ``example.com/mycharm/notice``.
    """

    id: str = dataclasses.field(default_factory=next_notice_id)
    """Unique ID for this notice."""

    user_id: Optional[int] = None
    """UID of the user who may view this notice (None means notice is public)."""

    type: Union[pebble.NoticeType, str] = pebble.NoticeType.CUSTOM
    """Type of the notice."""

    first_occurred: datetime.datetime = dataclasses.field(default_factory=_now_utc)
    """The first time one of these notices (type and key combination) occurs."""

    last_occurred: datetime.datetime = dataclasses.field(default_factory=_now_utc)
    """The last time one of these notices occurred."""

    last_repeated: datetime.datetime = dataclasses.field(default_factory=_now_utc)
    """The time this notice was last repeated.

    See Pebble's `Notices documentation <https://github.com/canonical/pebble/#notices>`_
    for an explanation of what "repeated" means.
    """

    occurrences: int = 1
    """The number of times one of these notices has occurred."""

    last_data: Dict[str, str] = dataclasses.field(default_factory=dict)
    """Additional data captured from the last occurrence of one of these notices."""

    repeat_after: Optional[datetime.timedelta] = None
    """Minimum time after one of these was last repeated before Pebble will repeat it again."""

    expire_after: Optional[datetime.timedelta] = None
    """How long since one of these last occurred until Pebble will drop the notice."""

    def _to_ops(self) -> pebble.Notice:
        return pebble.Notice(
            id=self.id,
            user_id=self.user_id,
            type=self.type,
            key=self.key,
            first_occurred=self.first_occurred,
            last_occurred=self.last_occurred,
            last_repeated=self.last_repeated,
            occurrences=self.occurrences,
            last_data=self.last_data,
            repeat_after=self.repeat_after,
            expire_after=self.expire_after,
        )


@dataclasses.dataclass(frozen=True)
class _BoundNotice(_DCBase):
    notice: Notice
    container: "Container"

    @property
    def event(self):
        """Sugar to generate a <container's name>-pebble-custom-notice event for this notice."""
        suffix = PEBBLE_CUSTOM_NOTICE_EVENT_SUFFIX
        return Event(
            path=normalize_name(self.container.name) + suffix,
            container=self.container,
            notice=self.notice,
        )


@dataclasses.dataclass(frozen=True)
class Container(_DCBase):
    """A Kubernetes container where a charm's workload runs."""

    name: str
    """Name of the container, as found in the charm metadata."""

    can_connect: bool = False
    """When False, all Pebble operations will fail."""

    # This is the base plan. On top of it, one can add layers.
    # We need to model pebble in this way because it's impossible to retrieve the layers from
    # pebble or derive them from the resulting plan (which one CAN get from pebble).
    # So if we are instantiating Container by fetching info from a 'live' charm, the 'layers'
    # will be unknown. all that we can know is the resulting plan (the 'computed plan').
    _base_plan: dict = dataclasses.field(default_factory=dict)
    # We expect most of the user-facing testing to be covered by this 'layers' attribute,
    # as all will be known when unit-testing.
    layers: Dict[str, pebble.Layer] = dataclasses.field(default_factory=dict)
    """All :class:`ops.pebble.Layer` definitions that have already been added to the container."""

    service_status: Dict[str, pebble.ServiceStatus] = dataclasses.field(
        default_factory=dict,
    )
    """The current status of each Pebble service running in the container."""

    # when the charm runs `pebble.pull`, it will return .open() from one of these paths.
    # when the charm pushes, it will either overwrite one of those paths (careful!) or it will
    # create a tempfile and insert its path in the mock filesystem tree
    mounts: Dict[str, Mount] = dataclasses.field(default_factory=dict)
    """Provides access to the contents of the simulated container filesystem.

    For example, suppose you want to express that your container has:

    * ``/home/foo/bar.py``
    * ``/bin/bash``
    * ``/bin/baz``

    this becomes::

        mounts = {
            'foo': scenario.Mount('/home/foo',  Path('/path/to/local/dir/containing/bar/py/')),
            'bin': Mount('/bin/', Path('/path/to/local/dir/containing/bash/and/baz/')),
        }
    """

    exec_mock: _ExecMock = dataclasses.field(default_factory=dict)
    """Simulate executing commands in the container.

    Specify each command the charm might run in the container and a :class:`ExecOutput`
    containing its return code and any stdout/stderr.

    For example::

        container = scenario.Container(
            name='foo',
            exec_mock={
                ('whoami', ): scenario.ExecOutput(return_code=0, stdout='ubuntu')
                ('dig', '+short', 'canonical.com'):
                    scenario.ExecOutput(return_code=0, stdout='185.125.190.20\\n185.125.190.21')
            }
        )
    """

    notices: List[Notice] = dataclasses.field(default_factory=list)

    def _render_services(self):
        # copied over from ops.testing._TestingPebbleClient._render_services()
        services = {}  # type: Dict[str, pebble.Service]
        for key in sorted(self.layers.keys()):
            layer = self.layers[key]
            for name, service in layer.services.items():
                services[name] = service
        return services

    @property
    def plan(self) -> pebble.Plan:
        """The 'computed' Pebble plan.

        i.e. the base plan plus the layers that have been added on top.
        You should run your assertions on this plan, not so much on the layers, as those are
        input data.
        """

        # copied over from ops.testing._TestingPebbleClient.get_plan().
        plan = pebble.Plan(yaml.safe_dump(self._base_plan))
        services = self._render_services()
        if not services:
            return plan
        for name in sorted(services.keys()):
            plan.services[name] = services[name]
        return plan

    @property
    def services(self) -> Dict[str, pebble.ServiceInfo]:
        """The Pebble services as rendered in the plan."""
        services = self._render_services()
        infos = {}  # type: Dict[str, pebble.ServiceInfo]
        names = sorted(services.keys())
        for name in names:
            try:
                service = services[name]
            except KeyError:
                # in pebble, it just returns "nothing matched" if there are 0 matches,
                # but it ignores services it doesn't recognize
                continue
            status = self.service_status.get(name, pebble.ServiceStatus.INACTIVE)
            if service.startup == "":
                startup = pebble.ServiceStartup.DISABLED
            else:
                startup = pebble.ServiceStartup(service.startup)
            info = pebble.ServiceInfo(
                name,
                startup=startup,
                current=pebble.ServiceStatus(status),
            )
            infos[name] = info
        return infos

    def get_filesystem(self, ctx: "Context") -> Path:
        """Simulated Pebble filesystem in this context.

        Returns:
            A temporary filesystem containing any files or directories the
            charm pushed to the container.
        """
        return ctx._get_container_root(self.name)

    @property
    def pebble_ready_event(self):
        """Sugar to generate a <this container's name>-pebble-ready event."""
        if not self.can_connect:
            logger.warning(
                "you **can** fire pebble-ready while the container cannot connect, "
                "but that's most likely not what you want.",
            )
        return Event(path=normalize_name(self.name + "-pebble-ready"), container=self)

    def get_notice(
        self,
        key: str,
        notice_type: pebble.NoticeType = pebble.NoticeType.CUSTOM,
    ) -> _BoundNotice:
        """Get a Pebble notice by key and type.

        Raises:
            KeyError: if the notice is not found.
        """
        for notice in self.notices:
            if notice.key == key and notice.type == notice_type:
                return _BoundNotice(notice, self)
        raise KeyError(
            f"{self.name} does not have a notice with key {key} and type {notice_type}",
        )


_RawStatusLiteral = Literal[
    "waiting",
    "blocked",
    "active",
    "unknown",
    "error",
    "maintenance",
]


@dataclasses.dataclass(frozen=True)
class _EntityStatus(_DCBase):
    """This class represents StatusBase and should not be interacted with directly."""

    # Why not use StatusBase directly? Because that's not json-serializable.

    name: _RawStatusLiteral
    message: str = ""

    def __eq__(self, other):
        if isinstance(other, Tuple):
            logger.warning(
                "Comparing Status with Tuples is deprecated and will be removed soon.",
            )
            return (self.name, self.message) == other
        if isinstance(other, (StatusBase, _EntityStatus)):
            return (self.name, self.message) == (other.name, other.message)
        logger.warning(
            f"Comparing Status with {other} is not stable and will be forbidden soon."
            f"Please compare with StatusBase directly.",
        )
        return super().__eq__(other)

    def __repr__(self):
        status_type_name = self.name.title() + "Status"
        if self.name == "unknown":
            return f"{status_type_name}()"
        return f"{status_type_name}('{self.message}')"


def _status_to_entitystatus(obj: StatusBase) -> _EntityStatus:
    """Convert StatusBase to _EntityStatus."""
    statusbase_subclass = type(StatusBase.from_name(obj.name, obj.message))

    class _MyClass(_EntityStatus, statusbase_subclass):
        # Custom type inheriting from a specific StatusBase subclass to support instance checks:
        #  isinstance(state.unit_status, ops.ActiveStatus)
        pass

    return _MyClass(cast(_RawStatusLiteral, obj.name), obj.message)


@dataclasses.dataclass(frozen=True)
class StoredState(_DCBase):
    # /-separated Object names. E.g. MyCharm/MyCharmLib.
    # if None, this StoredState instance is owned by the Framework.
    owner_path: Optional[str]

    name: str = "_stored"
    content: Dict[str, Any] = dataclasses.field(default_factory=dict)

    data_type_name: str = "StoredStateData"

    @property
    def handle_path(self):
        return f"{self.owner_path or ''}/{self.data_type_name}[{self.name}]"


_RawPortProtocolLiteral = Literal["tcp", "udp", "icmp"]


@dataclasses.dataclass(frozen=True)
class Port(_DCBase):
    """Represents a port on the charm host."""

    protocol: _RawPortProtocolLiteral
    """The protocol that data transferred over the port will use."""
    port: Optional[int] = None
    """The port to open. Required for TCP and UDP; not allowed for ICMP."""

    def __post_init__(self):
        port = self.port
        is_icmp = self.protocol == "icmp"
        if port:
            if is_icmp:
                raise StateValidationError(
                    "`port` arg not supported with `icmp` protocol",
                )
            if not (1 <= port <= 65535):
                raise StateValidationError(
                    f"`port` outside bounds [1:65535], got {port}",
                )
        elif not is_icmp:
            raise StateValidationError(
                f"`port` arg required with `{self.protocol}` protocol",
            )


_next_storage_index_counter = 0  # storage indices start at 0


def next_storage_index(update=True):
    """Get the index (used to be called ID) the next Storage to be created will get.

    Pass update=False if you're only inspecting it.
    Pass update=True if you also want to bump it.
    """
    global _next_storage_index_counter
    cur = _next_storage_index_counter
    if update:
        _next_storage_index_counter += 1
    return cur


@dataclasses.dataclass(frozen=True)
class Storage(_DCBase):
    """Represents an (attached!) storage made available to the charm container."""

    name: str

    index: int = dataclasses.field(default_factory=next_storage_index)
    # Every new Storage instance gets a new one, if there's trouble, override.

    def get_filesystem(self, ctx: "Context") -> Path:
        """Simulated filesystem root in this context."""
        return ctx._get_storage_root(self.name, self.index)

    @property
    def attached_event(self) -> "Event":
        """Sugar to generate a <this storage>-storage-attached event."""
        return Event(
            path=normalize_name(self.name + "-storage-attached"),
            storage=self,
        )

    @property
    def detaching_event(self) -> "Event":
        """Sugar to generate a <this storage>-storage-detached event."""
        return Event(
            path=normalize_name(self.name + "-storage-detaching"),
            storage=self,
        )


@dataclasses.dataclass(frozen=True)
class State(_DCBase):
    """Represents the juju-owned portion of a unit's state.

    Roughly speaking, it wraps all hook-tool- and pebble-mediated data a charm can access in its
    lifecycle. For example, status-get will return data from `State.status`, is-leader will
    return data from `State.leader`, and so on.
    """

    config: Dict[str, Union[str, int, float, bool]] = dataclasses.field(
        default_factory=dict,
    )
    """The present configuration of this charm."""
    relations: List["AnyRelation"] = dataclasses.field(default_factory=list)
    """All relations that currently exist for this charm."""
    networks: Dict[str, Network] = dataclasses.field(default_factory=dict)
    """Manual overrides for any relation and extra bindings currently provisioned for this charm.
    If a metadata-defined relation endpoint is not explicitly mapped to a Network in this field,
    it will be defaulted.
    [CAVEAT: `extra-bindings` is a deprecated, regretful feature in juju/ops. For completeness we
    support it, but use at your own risk.] If a metadata-defined extra-binding is left empty,
    it will be defaulted.
    """
    containers: List[Container] = dataclasses.field(default_factory=list)
    """All containers (whether they can connect or not) that this charm is aware of."""
    storage: List[Storage] = dataclasses.field(default_factory=list)
    """All ATTACHED storage instances for this charm.
    If a storage is not attached, omit it from this listing."""

    # we don't use sets to make json serialization easier
    opened_ports: List[Port] = dataclasses.field(default_factory=list)
    """Ports opened by juju on this charm."""
    leader: bool = False
    """Whether this charm has leadership."""
    model: Model = Model()
    """The model this charm lives in."""
    secrets: List[Secret] = dataclasses.field(default_factory=list)
    """The secrets this charm has access to (as an owner, or as a grantee).
    The presence of a secret in this list entails that the charm can read it.
    Whether it can manage it or not depends on the individual secret's `owner` flag."""
    resources: Dict[str, "PathLike"] = dataclasses.field(default_factory=dict)
    """Mapping from resource name to path at which the resource can be found."""
    planned_units: int = 1
    """Number of non-dying planned units that are expected to be running this application.
    Use with caution."""

    # represents the OF's event queue. These events will be emitted before the event being
    # dispatched, and represent the events that had been deferred during the previous run.
    # If the charm defers any events during "this execution", they will be appended
    # to this list.
    deferred: List["DeferredEvent"] = dataclasses.field(default_factory=list)
    """Events that have been deferred on this charm by some previous execution."""
    stored_state: List["StoredState"] = dataclasses.field(default_factory=list)
    """Contents of a charm's stored state."""

    # the current statuses. Will be cast to _EntitiyStatus in __post_init__
    app_status: Union[StatusBase, _EntityStatus] = _EntityStatus("unknown")
    """Status of the application."""
    unit_status: Union[StatusBase, _EntityStatus] = _EntityStatus("unknown")
    """Status of the unit."""
    workload_version: str = ""
    """Workload version."""

    def __post_init__(self):
        for name in ["app_status", "unit_status"]:
            val = getattr(self, name)
            if isinstance(val, _EntityStatus):
                pass
            elif isinstance(val, StatusBase):
                object.__setattr__(self, name, _status_to_entitystatus(val))
            else:
                raise TypeError(f"Invalid status.{name}: {val!r}")

    def _update_workload_version(self, new_workload_version: str):
        """Update the current app version and record the previous one."""
        # We don't keep a full history because we don't expect the app version to change more
        # than once per hook.

        # bypass frozen dataclass
        object.__setattr__(self, "workload_version", new_workload_version)

    def _update_status(
        self,
        new_status: _RawStatusLiteral,
        new_message: str = "",
        is_app: bool = False,
    ):
        """Update the current app/unit status and add the previous one to the history."""
        name = "app_status" if is_app else "unit_status"
        # bypass frozen dataclass
        object.__setattr__(self, name, _EntityStatus(new_status, new_message))

    def with_can_connect(self, container_name: str, can_connect: bool) -> "State":
        def replacer(container: Container):
            if container.name == container_name:
                return container.replace(can_connect=can_connect)
            return container

        ctrs = tuple(map(replacer, self.containers))
        return self.replace(containers=ctrs)

    def with_leadership(self, leader: bool) -> "State":
        return self.replace(leader=leader)

    def with_unit_status(self, status: StatusBase) -> "State":
        return self.replace(
            status=dataclasses.replace(
                cast(_EntityStatus, self.unit_status),
                unit=_status_to_entitystatus(status),
            ),
        )

    def get_container(self, container: Union[str, Container]) -> Container:
        """Get container from this State, based on an input container or its name."""
        container_name = (
            container.name if isinstance(container, Container) else container
        )
        containers = [c for c in self.containers if c.name == container_name]
        if not containers:
            raise ValueError(f"container: {container_name} not found in the State")
        return containers[0]

    def get_relations(self, endpoint: str) -> Tuple["AnyRelation", ...]:
        """Get all relations on this endpoint from the current state."""

        # we rather normalize the endpoint than worry about cursed metadata situations such as:
        # requires:
        #   foo-bar: ...
        #   foo_bar: ...

        normalized_endpoint = normalize_name(endpoint)
        return tuple(
            r
            for r in self.relations
            if normalize_name(r.endpoint) == normalized_endpoint
        )

    def get_storages(self, name: str) -> Tuple["Storage", ...]:
        """Get all storages with this name."""
        return tuple(s for s in self.storage if s.name == name)

    # FIXME: not a great way to obtain a delta, but is "complete". todo figure out a better way.
    def jsonpatch_delta(self, other: "State"):
        try:
            import jsonpatch  # type: ignore
        except ModuleNotFoundError:
            logger.error(
                "cannot import jsonpatch: using the .delta() "
                "extension requires jsonpatch to be installed."
                "Fetch it with pip install jsonpatch.",
            )
            return NotImplemented
        patch = jsonpatch.make_patch(
            dataclasses.asdict(other),
            dataclasses.asdict(self),
        ).patch
        return sort_patch(patch)


def _is_valid_charmcraft_25_metadata(meta: Dict[str, Any]):
    # Check whether this dict has the expected mandatory metadata fields according to the
    # charmcraft >2.5 charmcraft.yaml schema
    if (config_type := meta.get("type")) != "charm":
        logger.debug(
            f"Not a charm: charmcraft yaml config ``.type`` is {config_type!r}.",
        )
        return False
    if not all(field in meta for field in {"name", "summary", "description"}):
        logger.debug("Not a charm: charmcraft yaml misses some required fields")
        return False
    return True


@dataclasses.dataclass(frozen=True)
class _CharmSpec(_DCBase, Generic[CharmType]):
    """Charm spec."""

    charm_type: Type[CharmBase]
    meta: Dict[str, Any]
    actions: Optional[Dict[str, Any]] = None
    config: Optional[Dict[str, Any]] = None

    # autoloaded means: we are running a 'real' charm class, living in some
    # /src/charm.py, and the metadata files are 'real' metadata files.
    is_autoloaded: bool = False

    @staticmethod
    def _load_metadata_legacy(charm_root: Path):
        """Load metadata from charm projects created with Charmcraft < 2.5."""
        # back in the days, we used to have separate metadata.yaml, config.yaml and actions.yaml
        # files for charm metadata.
        metadata_path = charm_root / "metadata.yaml"
        meta = yaml.safe_load(metadata_path.open()) if metadata_path.exists() else {}

        config_path = charm_root / "config.yaml"
        config = yaml.safe_load(config_path.open()) if config_path.exists() else None

        actions_path = charm_root / "actions.yaml"
        actions = yaml.safe_load(actions_path.open()) if actions_path.exists() else None
        return meta, config, actions

    @staticmethod
    def _load_metadata(charm_root: Path):
        """Load metadata from charm projects created with Charmcraft >= 2.5."""
        metadata_path = charm_root / "charmcraft.yaml"
        meta = yaml.safe_load(metadata_path.open()) if metadata_path.exists() else {}
        if not _is_valid_charmcraft_25_metadata(meta):
            meta = {}
        config = meta.pop("config", None)
        actions = meta.pop("actions", None)
        return meta, config, actions

    @staticmethod
    def autoload(charm_type: Type[CharmBase]) -> "_CharmSpec[CharmType]":
        """Construct a ``_CharmSpec`` object by looking up the metadata from the charm's repo root.

        Will attempt to load the metadata off the ``charmcraft.yaml`` file
        """
        charm_source_path = Path(inspect.getfile(charm_type))
        charm_root = charm_source_path.parent.parent

        # attempt to load metadata from unified charmcraft.yaml
        meta, config, actions = _CharmSpec._load_metadata(charm_root)

        if not meta:
            # try to load using legacy metadata.yaml/actions.yaml/config.yaml files
            meta, config, actions = _CharmSpec._load_metadata_legacy(charm_root)

        if not meta:
            # still no metadata? bug out
            raise MetadataNotFoundError(
                f"invalid charm root {charm_root!r}; "
                f"expected to contain at least a `charmcraft.yaml` file "
                f"(or a `metadata.yaml` file if it's an old charm).",
            )

        return _CharmSpec(
            charm_type=charm_type,
            meta=meta,
            actions=actions,
            config=config,
            is_autoloaded=True,
        )

    def get_all_relations(self) -> List[Tuple[str, Dict[str, str]]]:
        """A list of all relation endpoints defined in the metadata."""
        return list(
            chain(
                self.meta.get("requires", {}).items(),
                self.meta.get("provides", {}).items(),
                self.meta.get("peers", {}).items(),
            ),
        )


def sort_patch(patch: List[Dict], key=lambda obj: obj["path"] + obj["op"]):
    return sorted(patch, key=key)


@dataclasses.dataclass(frozen=True)
class DeferredEvent(_DCBase):
    """An event that has been deferred to run prior to the next Juju event.

    In most cases, the :func:`deferred` function should be used to create a
    ``DeferredEvent`` instance."""

    handle_path: str
    owner: str
    observer: str

    # needs to be marshal.dumps-able.
    snapshot_data: Dict = dataclasses.field(default_factory=dict)

    @property
    def name(self):
        return self.handle_path.split("/")[-1].split("[")[0]


class _EventType(str, Enum):
    framework = "framework"
    builtin = "builtin"
    relation = "relation"
    action = "action"
    secret = "secret"
    storage = "storage"
    workload = "workload"
    custom = "custom"


class _EventPath(str):
    if TYPE_CHECKING:  # pragma: no cover
        name: str
        owner_path: List[str]
        suffix: str
        prefix: str
        is_custom: bool
        type: _EventType

    def __new__(cls, string):
        string = normalize_name(string)
        instance = super().__new__(cls, string)

        instance.name = name = string.split(".")[-1]
        instance.owner_path = string.split(".")[:-1] or ["on"]

        instance.suffix, instance.type = suffix, _ = _EventPath._get_suffix_and_type(
            name,
        )
        if suffix:
            instance.prefix, _ = string.rsplit(suffix)
        else:
            instance.prefix = string

        instance.is_custom = suffix == ""
        return instance

    @staticmethod
    def _get_suffix_and_type(s: str) -> Tuple[str, _EventType]:
        for suffix in RELATION_EVENTS_SUFFIX:
            if s.endswith(suffix):
                return suffix, _EventType.relation

        if s.endswith(ACTION_EVENT_SUFFIX):
            return ACTION_EVENT_SUFFIX, _EventType.action

        if s in SECRET_EVENTS:
            return s, _EventType.secret

        if s in FRAMEWORK_EVENTS:
            return s, _EventType.framework

        # Whether the event name indicates that this is a storage event.
        for suffix in STORAGE_EVENTS_SUFFIX:
            if s.endswith(suffix):
                return suffix, _EventType.storage

        # Whether the event name indicates that this is a workload event.
        if s.endswith(PEBBLE_READY_EVENT_SUFFIX):
            return PEBBLE_READY_EVENT_SUFFIX, _EventType.workload
        if s.endswith(PEBBLE_CUSTOM_NOTICE_EVENT_SUFFIX):
            return PEBBLE_CUSTOM_NOTICE_EVENT_SUFFIX, _EventType.workload

        if s in BUILTIN_EVENTS:
            return "", _EventType.builtin

        return "", _EventType.custom


@dataclasses.dataclass(frozen=True)
class Event(_DCBase):
    """A Juju, ops, or custom event that can be run against a charm.

    Typically, for simple events, the string name (e.g. ``install``) can be used,
    and for more complex events, an ``event`` property will be available on the
    related object (e.g. ``relation.joined_event``).
    """

    path: str
    args: Tuple[Any, ...] = ()
    kwargs: Dict[str, Any] = dataclasses.field(default_factory=dict)

    storage: Optional["Storage"] = None
    """If this is a storage event, the storage it refers to."""
    relation: Optional["AnyRelation"] = None
    """If this is a relation event, the relation it refers to."""
    relation_remote_unit_id: Optional[int] = None
    """If this is a relation event, the name of the remote unit the event is about."""

    secret: Optional[Secret] = None
    """If this is a secret event, the secret it refers to."""

    container: Optional[Container] = None
    """If this is a workload (container) event, the container it refers to."""

    notice: Optional[Notice] = None
    """If this is a Pebble notice event, the notice it refers to."""

    action: Optional["Action"] = None
    """If this is an action event, the :class:`Action` it refers to."""

    # TODO: add other meta for
    #  - secret events
    #  - pebble?
    #  - action?

    _owner_path: List[str] = dataclasses.field(default_factory=list)

    def __call__(self, remote_unit_id: Optional[int] = None) -> "Event":
        if remote_unit_id and not self._is_relation_event:
            raise ValueError(
                "cannot pass param `remote_unit_id` to a "
                "non-relation event constructor.",
            )
        return self.replace(relation_remote_unit_id=remote_unit_id)

    def __post_init__(self):
        path = _EventPath(self.path)
        # bypass frozen dataclass
        object.__setattr__(self, "path", path)

    @property
    def _path(self) -> _EventPath:
        # we converted it in __post_init__, but the type checker doesn't know about that
        return cast(_EventPath, self.path)

    @property
    def name(self) -> str:
        """Full event name.

        Consists of a 'prefix' and a 'suffix'. The suffix denotes the type of the event, the
        prefix the name of the entity the event is about.

        "foo-relation-changed":
         - "foo"=prefix (name of a relation),
         - "-relation-changed"=suffix (relation event)
        """
        return self._path.name

    @property
    def owner_path(self) -> List[str]:
        """Path to the ObjectEvents instance owning this event.

        If this event is defined on the toplevel charm class, it should be ['on'].
        """
        return self._path.owner_path

    @property
    def _is_relation_event(self) -> bool:
        """Whether the event name indicates that this is a relation event."""
        return self._path.type is _EventType.relation

    @property
    def _is_action_event(self) -> bool:
        """Whether the event name indicates that this is a relation event."""
        return self._path.type is _EventType.action

    @property
    def _is_secret_event(self) -> bool:
        """Whether the event name indicates that this is a secret event."""
        return self._path.type is _EventType.secret

    @property
    def _is_storage_event(self) -> bool:
        """Whether the event name indicates that this is a storage event."""
        return self._path.type is _EventType.storage

    @property
    def _is_workload_event(self) -> bool:
        """Whether the event name indicates that this is a workload event."""
        return self._path.type is _EventType.workload

    # this method is private because _CharmSpec is not quite user-facing; also,
    # the user should know.
    def _is_builtin_event(self, charm_spec: "_CharmSpec"):
        """Determine whether the event is a custom-defined one or a builtin one."""
        event_name = self.name

        # simple case: this is an event type owned by our charm base.on
        if hasattr(charm_spec.charm_type.on, event_name):
            return hasattr(CharmEvents, event_name)

        # this could be an event defined on some other Object, e.g. a charm lib.
        # We don't support (yet) directly emitting those, but they COULD have names that conflict
        # with events owned by the base charm. E.g. if the charm has a `foo` relation, the charm
        # will get a  charm.on.foo_relation_created. Your charm lib is free to define its own
        # `foo_relation_created`  custom event, because its handle will be
        # `charm.lib.on.foo_relation_created` and therefore be  unique and the Framework is happy.
        # However, our Event data structure ATM has no knowledge of which Object/Handle it is
        # owned by. So the only thing we can do right now is: check whether the event name,
        # assuming it is owned by the charm, LOOKS LIKE that of a builtin event or not.
        return self._path.type is not _EventType.custom

    def bind(self, state: State):
        """Attach to this event the state component it needs.

        For example, a relation event initialized without a Relation instance will search for
        a suitable relation in the provided state and return a copy of itself with that
        relation attached.

        In case of ambiguity (e.g. multiple relations found on 'foo' for event
        'foo-relation-changed', we pop a warning and bind the first one. Use with care!
        """
        entity_name = self._path.prefix

        if self._is_workload_event and not self.container:
            try:
                container = state.get_container(entity_name)
            except ValueError:
                raise BindFailedError(f"no container found with name {entity_name}")
            return self.replace(container=container)

        if self._is_secret_event and not self.secret:
            if len(state.secrets) < 1:
                raise BindFailedError(f"no secrets found in state: cannot bind {self}")
            if len(state.secrets) > 1:
                raise BindFailedError(
                    f"too many secrets found in state: cannot automatically bind {self}",
                )
            return self.replace(secret=state.secrets[0])

        if self._is_storage_event and not self.storage:
            storages = state.get_storages(entity_name)
            if len(storages) < 1:
                raise BindFailedError(
                    f"no storages called {entity_name} found in state",
                )
            if len(storages) > 1:
                logger.warning(
                    f"too many storages called {entity_name}: binding to first one",
                )
            storage = storages[0]
            return self.replace(storage=storage)

        if self._is_relation_event and not self.relation:
            ep_name = entity_name
            relations = state.get_relations(ep_name)
            if len(relations) < 1:
                raise BindFailedError(f"no relations on {ep_name} found in state")
            if len(relations) > 1:
                logger.warning(f"too many relations on {ep_name}: binding to first one")
            return self.replace(relation=relations[0])

        if self._is_action_event and not self.action:
            raise BindFailedError(
                "cannot automatically bind action events: if the action has mandatory parameters "
                "this would probably result in horrible, undebuggable failures downstream.",
            )

        else:
            raise BindFailedError(
                f"cannot bind {self}: only relation, secret, "
                f"or workload events can be bound.",
            )

    def deferred(self, handler: Callable, event_id: int = 1) -> DeferredEvent:
        """Construct a DeferredEvent from this Event."""
        handler_repr = repr(handler)
        handler_re = re.compile(r"<function (.*) at .*>")
        match = handler_re.match(handler_repr)
        if not match:
            raise ValueError(
                f"cannot construct DeferredEvent from {handler}; please create one manually.",
            )
        owner_name, handler_name = match.groups()[0].split(".")[-2:]
        handle_path = f"{owner_name}/on/{self.name}[{event_id}]"

        snapshot_data = {}

        # fixme: at this stage we can't determine if the event is a builtin one or not; if it is
        #  not, then the coming checks are meaningless: the custom event could be named like a
        #  relation event but not *be* one.
        if self._is_workload_event:
            # this is a WorkloadEvent. The snapshot:
            container = cast(Container, self.container)
            snapshot_data = {
                "container_name": container.name,
            }
            if self.notice:
                if hasattr(self.notice.type, "value"):
                    notice_type = cast(pebble.NoticeType, self.notice.type).value
                else:
                    notice_type = str(self.notice.type)
                snapshot_data.update(
                    {
                        "notice_id": self.notice.id,
                        "notice_key": self.notice.key,
                        "notice_type": notice_type,
                    },
                )

        elif self._is_relation_event:
            # this is a RelationEvent.
            relation = cast("AnyRelation", self.relation)
            if isinstance(relation, PeerRelation):
                # FIXME: relation.unit for peers should point to <this unit>, but we
                #  don't have access to the local app name in this context.
                remote_app = "local"
            else:
                remote_app = relation.remote_app_name

            snapshot_data = {
                "relation_name": relation.endpoint,
                "relation_id": relation.relation_id,
                "app_name": remote_app,
                "unit_name": f"{remote_app}/{self.relation_remote_unit_id}",
            }

        return DeferredEvent(
            handle_path,
            owner_name,
            handler_name,
            snapshot_data=snapshot_data,
        )


_next_action_id_counter = 1


def next_action_id(update=True):
    global _next_action_id_counter
    cur = _next_action_id_counter
    if update:
        _next_action_id_counter += 1
    # Juju currently uses numbers for the ID, but in the past used UUIDs, so
    # we need these to be strings.
    return str(cur)


@dataclasses.dataclass(frozen=True)
class Action(_DCBase):
    """A ``juju run`` command.

    Used to simulate ``juju run``, passing in any parameters. For example::

        def test_backup_action():
            action = scenario.Action('do_backup', params={'filename': 'foo'})
            ctx = scenario.Context(MyCharm)
            out: scenario.ActionOutput = ctx.run_action(action, scenario.State())
    """

    name: str
    """Juju action name, as found in the charm metadata."""

    params: Dict[str, "AnyJson"] = dataclasses.field(default_factory=dict)
    """Parameter values passed to the action."""

    id: str = dataclasses.field(default_factory=next_action_id)
    """Juju action ID.

    Every action invocation is automatically assigned a new one. Override in
    the rare cases where a specific ID is required."""

    @property
    def event(self) -> Event:
        """Helper to generate an action event from this action."""
        return Event(self.name + ACTION_EVENT_SUFFIX, action=self)


def deferred(
    event: Union[str, Event],
    handler: Callable,
    event_id: int = 1,
    relation: Optional["Relation"] = None,
    container: Optional["Container"] = None,
    notice: Optional["Notice"] = None,
):
    """Construct a DeferredEvent from an Event or an event name."""
    if isinstance(event, str):
        event = Event(event, relation=relation, container=container, notice=notice)
    return event.deferred(handler=handler, event_id=event_id)
