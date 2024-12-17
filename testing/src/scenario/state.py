#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""The core State object, and the components inside it."""

from __future__ import annotations

import dataclasses
import datetime
import inspect
import pathlib
import random
import re
import string
from enum import Enum
from itertools import chain
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    ClassVar,
    Dict,
    Final,
    Generic,
    Iterable,
    List,
    Literal,
    Mapping,
    NoReturn,
    Sequence,
    TypeVar,
    Union,
    cast,
)
from uuid import uuid4

import yaml

import ops
from ops import pebble, CharmBase, CharmEvents, SecretRotate, StatusBase
from ops import CloudCredential as CloudCredential_Ops
from ops import CloudSpec as CloudSpec_Ops

from .errors import MetadataNotFoundError, StateValidationError
from .logger import logger as scenario_logger

if TYPE_CHECKING:  # pragma: no cover
    from . import Context

AnyJson = Union[str, bool, Dict[str, "AnyJson"], int, float, List["AnyJson"]]
RawSecretRevisionContents = RawDataBagContents = Dict[str, str]
UnitID = int

CharmType = TypeVar("CharmType", bound=CharmBase)

logger = scenario_logger.getChild("state")

ATTACH_ALL_STORAGES = "ATTACH_ALL_STORAGES"
CREATE_ALL_RELATIONS = "CREATE_ALL_RELATIONS"
BREAK_ALL_RELATIONS = "BREAK_ALL_RELATIONS"
DETACH_ALL_STORAGES = "DETACH_ALL_STORAGES"

_ACTION_EVENT_SUFFIX = "_action"
# all builtin events except secret events. They're special because they carry secret metadata.
_BUILTIN_EVENTS = {
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
_FRAMEWORK_EVENTS = {
    "pre_commit",
    "commit",
    "collect_app_status",
    "collect_unit_status",
}
_PEBBLE_READY_EVENT_SUFFIX = "_pebble_ready"
_PEBBLE_CUSTOM_NOTICE_EVENT_SUFFIX = "_pebble_custom_notice"
_PEBBLE_CHECK_FAILED_EVENT_SUFFIX = "_pebble_check_failed"
_PEBBLE_CHECK_RECOVERED_EVENT_SUFFIX = "_pebble_check_recovered"
_RELATION_EVENTS_SUFFIX = {
    "_relation_changed",
    "_relation_broken",
    "_relation_joined",
    "_relation_departed",
    "_relation_created",
}
_STORAGE_EVENTS_SUFFIX = {
    "_storage_detaching",
    "_storage_attached",
}

_SECRET_EVENTS = {
    "secret_changed",
    "secret_remove",
    "secret_rotate",
    "secret_expired",
}


# This can be replaced with the KW_ONLY dataclasses functionality in Python 3.10+.
def _max_posargs(n: int):
    class _MaxPositionalArgs:
        """Raises TypeError when instantiating objects if arguments are not passed as keywords.

        Looks for a `_max_positional_args` class attribute, which should be an int
        indicating the maximum number of positional arguments that can be passed to
        `__init__` (excluding `self`).
        """

        _max_positional_args = n

        @classmethod
        def _annotate_class(cls):
            """Record information about which parameters are positional vs. keyword-only."""
            if hasattr(cls, "_init_parameters"):
                # We don't support dynamically changing the signature of a
                # class, so we assume here it's the same as previously.
                # In addition, the class and the function that provides it
                # are private, so we generally don't expect anyone to be
                # doing anything radical with these.
                return
            # inspect.signature guarantees the order of parameters is as
            # declared, which aligns with dataclasses. Simpler ways of
            # getting the arguments (like __annotations__) do not have that
            # guarantee, although in practice it is the case.
            cls._init_parameters = parameters = inspect.signature(
                cls.__init__
            ).parameters
            cls._init_kw_only = {
                name
                for name in tuple(parameters)[cls._max_positional_args :]
                if not name.startswith("_")
            }
            cls._init_required_args = [
                name
                for name in tuple(parameters)
                if name != "self"
                and parameters[name].default is inspect.Parameter.empty
            ]

        def __new__(cls, *args: Any, **kwargs: Any):
            cls._annotate_class()
            required_args = [
                name for name in cls._init_required_args if name not in kwargs
            ]
            n_posargs = len(args)
            max_n_posargs = cls._max_positional_args
            kw_only = cls._init_kw_only
            if n_posargs > max_n_posargs:
                raise TypeError(
                    f"{cls.__name__} takes {max_n_posargs} positional "
                    f"argument{'' if max_n_posargs == 1 else 's'} but "
                    f"{n_posargs} {'was' if n_posargs == 1 else 'were'} "
                    f"given. The following arguments are keyword-only: "
                    f"{', '.join(kw_only)}",
                ) from None
            # Also check if there are just not enough arguments at all, because
            # the default TypeError message will incorrectly describe some of
            # the arguments as positional.
            if n_posargs < len(required_args):
                required_pos = [
                    f"'{arg}'"
                    for arg in required_args[n_posargs:]
                    if arg not in kw_only
                ]
                required_kw = {
                    f"'{arg}'" for arg in required_args[n_posargs:] if arg in kw_only
                }
                if required_pos and required_kw:
                    details = f"positional: {', '.join(required_pos)} and keyword: {', '.join(required_kw)} arguments"
                elif required_pos:
                    details = f"positional argument{'' if len(required_pos) == 1 else 's'}: {', '.join(required_pos)}"
                else:
                    details = f"keyword argument{'' if len(required_kw) == 1 else 's'}: {', '.join(required_kw)}"
                raise TypeError(f"{cls.__name__} missing required {details}") from None
            return super().__new__(cls)

        def __reduce__(self):
            # The default __reduce__ doesn't understand that some arguments have
            # to be passed as keywords, so using the copy module fails.
            attrs = cast(Dict[str, Any], super().__reduce__()[2])
            return (lambda: self.__class__(**attrs), ())

    return _MaxPositionalArgs


# A lot of JujuLogLine objects are created, so we want them to be fast and light.
# Dataclasses define __slots__, so are small, and a namedtuple is actually
# slower to create than a dataclass. A plain dictionary (or TypedDict) would be
# about twice as fast, but less convenient to use.
@dataclasses.dataclass(frozen=True)
class JujuLogLine:
    """An entry in the Juju debug-log."""

    level: str
    """The level of the message, for example ``INFO`` or ``ERROR``."""
    message: str
    """The log message."""


@dataclasses.dataclass(frozen=True)
class CloudCredential(_max_posargs(0)):
    __doc__ = ops.CloudCredential.__doc__

    auth_type: str
    """Authentication type."""

    attributes: dict[str, str] = dataclasses.field(default_factory=dict)
    """A dictionary containing cloud credentials.
    For example, for AWS, it contains `access-key` and `secret-key`;
    for Azure, `application-id`, `application-password` and `subscription-id`
    can be found here.
    """

    redacted: list[str] = dataclasses.field(default_factory=list)
    """A list of redacted generic cloud API secrets."""

    def _to_ops(self) -> CloudCredential_Ops:
        return CloudCredential_Ops(
            auth_type=self.auth_type,
            attributes=self.attributes,
            redacted=self.redacted,
        )


@dataclasses.dataclass(frozen=True)
class CloudSpec(_max_posargs(1)):
    __doc__ = ops.CloudSpec.__doc__

    type: str
    """Type of the cloud."""

    name: str = "localhost"
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

    ca_certificates: list[str] = dataclasses.field(default_factory=list)
    """A list of CA certificates."""

    skip_tls_verify: bool = False
    """Whether to skip TLS verification."""

    is_controller_cloud: bool = False
    """If this is the cloud used by the controller."""

    def _to_ops(self) -> CloudSpec_Ops:
        return CloudSpec_Ops(
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


def _generate_secret_id():
    # This doesn't account for collisions, but the odds are so low that it
    # should not be possible in any realistic test run.
    secret_id = "".join(
        random.choice(string.ascii_lowercase + string.digits) for _ in range(20)
    )
    return f"secret:{secret_id}"


@dataclasses.dataclass(frozen=True)
class Secret(_max_posargs(1)):
    """A Juju secret.

    This class is used for both user and charm secrets.
    """

    tracked_content: RawSecretRevisionContents
    """The content of the secret that the charm is currently tracking.

    This is the content the charm will receive with a
    :meth:`ops.Secret.get_content` call."""
    latest_content: RawSecretRevisionContents | None = None
    """The content of the latest revision of the secret.

    This is the content the charm will receive with a
    :meth:`ops.Secret.peek_content` call."""

    id: str = dataclasses.field(default_factory=_generate_secret_id)
    """The Juju ID of the secret.

    This is automatically assigned and should not usually need to be explicitly set.
    """

    owner: Literal["unit", "app", None] = None
    """Indicates if the secret is owned by *this* unit, *this* application, or
    another application/unit.

    If None, the implication is that read access to the secret has been granted
    to this unit.
    """

    remote_grants: dict[int, set[str]] = dataclasses.field(default_factory=dict)
    """Mapping from relation IDs to remote units and applications to which this
    secret has been granted."""

    label: str | None = None
    """A human-readable label the charm can use to retrieve the secret.

    If this is set, it implies that the charm has previously set the label.
    """
    description: str | None = None
    """A human-readable description of the secret."""
    expire: datetime.datetime | None = None
    """The time at which the secret will expire."""
    rotate: SecretRotate | None = None
    """The rotation policy for the secret."""

    # what revision is currently tracked by this charm. Only meaningful if owner=False
    _tracked_revision: int = 1

    # what revision is the latest for this secret.
    _latest_revision: int = 1

    def __hash__(self) -> int:
        return hash(self.id)

    def __post_init__(self):
        if self.latest_content is None:
            # bypass frozen dataclass
            object.__setattr__(self, "latest_content", self.tracked_content)

    def _set_label(self, label: str):
        # bypass frozen dataclass
        object.__setattr__(self, "label", label)

    def _track_latest_revision(self):
        """Set the current revision to the tracked revision."""
        # bypass frozen dataclass
        object.__setattr__(self, "_tracked_revision", self._latest_revision)
        object.__setattr__(self, "tracked_content", self.latest_content)

    def _update_metadata(
        self,
        content: RawSecretRevisionContents | None = None,
        label: str | None = None,
        description: str | None = None,
        expire: datetime.datetime | None = None,
        rotate: SecretRotate | None = None,
    ):
        """Update the metadata."""
        # bypass frozen dataclass
        object.__setattr__(self, "_latest_revision", self._latest_revision + 1)
        if content:
            object.__setattr__(self, "latest_content", content)
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


def _normalise_name(s: str):
    """Event names, in Scenario, uniformly use underscores instead of dashes."""
    return s.replace("-", "_")


@dataclasses.dataclass(frozen=True)
class Address(_max_posargs(1)):
    """An address in a Juju network space."""

    value: str
    """The IP address in the space."""
    hostname: str = ""
    """A host name that maps to the address in :attr:`value`."""
    cidr: str = ""
    """The CIDR of the address in :attr:`value`."""

    @property
    def address(self):
        """A deprecated alias for :attr:`value`."""
        return self.value

    @address.setter
    def address(self, value: str):
        object.__setattr__(self, "value", value)


@dataclasses.dataclass(frozen=True)
class BindAddress(_max_posargs(1)):
    """An address bound to a network interface in a Juju space."""

    addresses: list[Address]
    """The addresses in the space."""
    interface_name: str = ""
    """The name of the network interface."""
    mac_address: str | None = None
    """The MAC address of the interface."""

    def _hook_tool_output_fmt(self):
        """Dumps itself to dict in the same format the hook tool would."""
        dct = {
            "interface-name": self.interface_name,
            "addresses": [dataclasses.asdict(addr) for addr in self.addresses],
        }
        if self.mac_address:
            dct["mac-address"] = self.mac_address
        return dct


@dataclasses.dataclass(frozen=True)
class Network(_max_posargs(2)):
    """A Juju network space."""

    binding_name: str
    """The name of the network space."""
    bind_addresses: list[BindAddress] = dataclasses.field(
        default_factory=lambda: [BindAddress([Address("192.0.2.0")])],
    )
    """Addresses that the charm's application should bind to."""
    ingress_addresses: list[str] = dataclasses.field(
        default_factory=lambda: ["192.0.2.0"],
    )
    """Addresses other applications should use to connect to the unit."""
    egress_subnets: list[str] = dataclasses.field(
        default_factory=lambda: ["192.0.2.0/24"],
    )
    """Subnets that other units will see the charm connecting from."""

    def __hash__(self) -> int:
        return hash(self.binding_name)

    def _hook_tool_output_fmt(self):
        # dumps itself to dict in the same format the hook tool would
        return {
            "bind-addresses": [
                ba._hook_tool_output_fmt() for ba in self.bind_addresses
            ],
            "egress-subnets": self.egress_subnets,
            "ingress-addresses": self.ingress_addresses,
        }


_next_relation_id_counter = 1


def _next_relation_id(*, update: bool = True):
    """Get the ID the next relation to be created will get.

    Pass update=False if you're only inspecting it.
    Pass update=True if you also want to bump it.
    """
    global _next_relation_id_counter
    cur = _next_relation_id_counter
    if update:
        _next_relation_id_counter += 1
    return cur


@dataclasses.dataclass(frozen=True)
class RelationBase(_max_posargs(2)):
    """Base class for the various types of integration (relation)."""

    endpoint: str
    """Relation endpoint name. Must match some endpoint name defined in the metadata."""

    interface: str | None = None
    """Interface name. Must match the interface name attached to this endpoint in the metadata.
    If left empty, it will be automatically derived from the metadata."""

    id: int = dataclasses.field(default_factory=_next_relation_id)
    """Juju relation ID. Every new Relation instance gets a unique one,
    if there's trouble, override."""

    local_app_data: RawDataBagContents = dataclasses.field(default_factory=dict)
    """This application's databag for this relation."""

    local_unit_data: RawDataBagContents = dataclasses.field(
        default_factory=lambda: _DEFAULT_JUJU_DATABAG.copy(),
    )
    """This unit's databag for this relation."""

    @property
    def relation_id(self) -> NoReturn:
        """Use `.id` instead of `.relation_id`.

        :private:
        """
        raise AttributeError("use .id instead of .relation_id")

    @property
    def _databags(self):
        """Yield all databags in this relation."""
        yield self.local_app_data
        yield self.local_unit_data

    @property
    def _remote_unit_ids(self) -> tuple[UnitID, ...]:
        """Ids of the units on the other end of this relation."""
        raise NotImplementedError()

    def _get_databag_for_remote(
        self,
        unit_id: int,  # noqa: U100
    ) -> RawDataBagContents:
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

    def __hash__(self) -> int:
        return hash(self.id)

    def _validate_databag(self, databag: dict[str, str]):
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


_DEFAULT_IP = "192.0.2.0"
_DEFAULT_JUJU_DATABAG = {
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

    remote_app_data: RawDataBagContents = dataclasses.field(default_factory=dict)
    """The current content of the application databag."""
    remote_units_data: dict[UnitID, RawDataBagContents] = dataclasses.field(
        default_factory=lambda: {0: _DEFAULT_JUJU_DATABAG.copy()},  # dedup
    )
    """The current content of the databag for each unit in the relation."""

    def __hash__(self) -> int:
        return hash(self.id)

    @property
    def _remote_app_name(self) -> str:
        """Who is on the other end of this relation?"""
        return self.remote_app_name

    @property
    def _remote_unit_ids(self) -> tuple[UnitID, ...]:
        """Ids of the units on the other end of this relation."""
        return tuple(self.remote_units_data)

    def _get_databag_for_remote(self, unit_id: UnitID) -> RawDataBagContents:
        """Return the databag for some remote unit ID."""
        return self.remote_units_data[unit_id]

    @property
    def _databags(self):  # type: ignore
        """Yield all databags in this relation."""
        yield self.local_app_data
        yield self.local_unit_data
        yield self.remote_app_data
        yield from self.remote_units_data.values()


@dataclasses.dataclass(frozen=True)
class SubordinateRelation(RelationBase):
    """A relation to share data between a subordinate and a principal charm."""

    remote_app_data: RawDataBagContents = dataclasses.field(default_factory=dict)
    """The current content of the remote application databag."""
    remote_unit_data: RawDataBagContents = dataclasses.field(
        default_factory=lambda: _DEFAULT_JUJU_DATABAG.copy(),
    )
    """The current content of the remote unit databag."""

    remote_app_name: str = "remote"
    """The name of the remote application that *this unit* is attached to."""
    remote_unit_id: int = 0
    """The ID of the remote unit that *this unit* is attached to."""

    def __hash__(self) -> int:
        return hash(self.id)

    @property
    def _remote_unit_ids(self) -> tuple[int]:
        """Ids of the units on the other end of this relation."""
        return (self.remote_unit_id,)

    def _get_databag_for_remote(self, unit_id: int) -> RawDataBagContents:
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
        """The full name of the remote unit, in the form ``remote/0``."""
        return f"{self.remote_app_name}/{self.remote_unit_id}"


@dataclasses.dataclass(frozen=True)
class PeerRelation(RelationBase):
    """A relation to share data between units of the charm."""

    peers_data: dict[UnitID, RawDataBagContents] = dataclasses.field(
        default_factory=lambda: {0: _DEFAULT_JUJU_DATABAG.copy()},
    )
    """Current contents of the peer databags."""
    # Consistency checks will validate that *this unit*'s ID is not in here.

    def __hash__(self) -> int:
        return hash(self.id)

    @property
    def _databags(self):  # type: ignore
        """Yield all databags in this relation."""
        yield self.local_app_data
        yield self.local_unit_data
        yield from self.peers_data.values()

    @property
    def _remote_unit_ids(self) -> tuple[UnitID, ...]:
        """Ids of the units on the other end of this relation."""
        return tuple(self.peers_data)

    def _get_databag_for_remote(self, unit_id: UnitID) -> RawDataBagContents:
        """Return the databag for some remote unit ID."""
        return self.peers_data[unit_id]


def _random_model_name():
    space = string.ascii_letters + string.digits
    return "".join(random.choice(space) for _ in range(20))


@dataclasses.dataclass(frozen=True)
class Model(_max_posargs(1)):
    """The Juju model in which the charm is deployed."""

    name: str = dataclasses.field(default_factory=_random_model_name)
    """The name of the model."""
    uuid: str = dataclasses.field(default_factory=lambda: str(uuid4()))
    """A unique identifier for the model, typically generated by Juju."""

    # whatever juju models --format=json | jq '.models[<current-model-index>].type' gives back.
    type: Literal["kubernetes", "lxd"] = "kubernetes"
    """The type of Juju model."""

    cloud_spec: CloudSpec | None = None
    """Cloud specification information (metadata) including credentials."""


_CHANGE_IDS = 0


def _generate_new_change_id():
    global _CHANGE_IDS
    _CHANGE_IDS += 1  # type: ignore
    logger.info(
        f"change ID unset; automatically assigning {_CHANGE_IDS}. "
        f"If there are problems, pass one manually.",
    )
    return _CHANGE_IDS


@dataclasses.dataclass(frozen=True)
class Exec(_max_posargs(1)):
    """Mock data for simulated :meth:`ops.Container.exec` calls."""

    command_prefix: Sequence[str]
    return_code: int = 0
    """The return code of the process.

    Use 0 to mock the process ending successfully, and other values for failure.
    """
    stdout: str = ""
    """Any content written to stdout by the process.

    Provide content that the real process would write to stdout, which can be
    read by the charm.
    """
    stderr: str = ""
    """Any content written to stderr by the process.

    Provide content that the real process would write to stderr, which can be
    read by the charm.
    """

    # change ID: used internally to keep track of mocked processes
    _change_id: int = dataclasses.field(default_factory=_generate_new_change_id)

    def __post_init__(self):
        # The command prefix can be any sequence type, and a list is tidier to
        # write when there's only one string. However, this object needs to be
        # hashable, so can't contain a list. We 'freeze' the sequence to a tuple
        # to support that.
        object.__setattr__(self, "command_prefix", tuple(self.command_prefix))

    def _run(self) -> int:
        return self._change_id


@dataclasses.dataclass(frozen=True)
class Mount(_max_posargs(0)):
    """Maps local files to a :class:`Container` filesystem."""

    location: str | pathlib.PurePosixPath
    """The location inside of the container."""
    source: str | pathlib.Path
    """The content to provide when the charm does :meth:`ops.Container.pull`."""


def _now_utc():
    return datetime.datetime.now(tz=datetime.timezone.utc)


_next_notice_id_counter = 1


def _next_notice_id(*, update: bool = True):
    """Get the ID the next Pebble notice to be created will get.

    Pass update=False if you're only inspecting it.
    Pass update=True if you also want to bump it.
    """
    global _next_notice_id_counter
    cur = _next_notice_id_counter
    if update:
        _next_notice_id_counter += 1
    return str(cur)


@dataclasses.dataclass(frozen=True)
class Notice(_max_posargs(1)):
    """A Pebble notice."""

    key: str
    """The notice key, a string that differentiates notices of this type.

    This is in the format ``domain/path``; for example:
    ``canonical.com/postgresql/backup`` or ``example.com/mycharm/notice``.
    """

    id: str = dataclasses.field(default_factory=_next_notice_id)
    """Unique ID for this notice."""

    user_id: int | None = None
    """UID of the user who may view this notice (None means notice is public)."""

    type: pebble.NoticeType | str = pebble.NoticeType.CUSTOM
    """Type of the notice."""

    first_occurred: datetime.datetime = dataclasses.field(default_factory=_now_utc)
    """The first time one of these notices (type and key combination) occurs."""

    last_occurred: datetime.datetime = dataclasses.field(default_factory=_now_utc)
    """The last time one of these notices occurred."""

    last_repeated: datetime.datetime = dataclasses.field(default_factory=_now_utc)
    """The time this notice was last repeated.

    See Pebble's `Notices documentation <https://canonical-pebble.readthedocs-hosted.com/en/latest/reference/notices/>`_
    for an explanation of what "repeated" means.
    """

    occurrences: int = 1
    """The number of times one of these notices has occurred."""

    last_data: dict[str, str] = dataclasses.field(default_factory=dict)
    """Additional data captured from the last occurrence of one of these notices."""

    repeat_after: datetime.timedelta | None = None
    """Minimum time after one of these was last repeated before Pebble will repeat it again."""

    expire_after: datetime.timedelta | None = None
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
class CheckInfo(_max_posargs(1)):
    """A health check for a Pebble workload container."""

    name: str
    """Name of the check."""

    level: pebble.CheckLevel | None = None
    """Level of the check."""

    status: pebble.CheckStatus = pebble.CheckStatus.UP
    """Status of the check.

    :attr:`ops.pebble.CheckStatus.UP` means the check is healthy (the number of
    failures is fewer than the threshold), :attr:`ops.pebble.CheckStatus.DOWN`
    means the check is unhealthy (the number of failures has reached the
    threshold).
    """

    failures: int = 0
    """Number of failures since the check last succeeded."""

    threshold: int = 3
    """Failure threshold.

    This is how many consecutive failures for the check to be considered 'down'.
    """

    def _to_ops(self) -> pebble.CheckInfo:
        return pebble.CheckInfo(
            name=self.name,
            level=self.level,
            status=self.status,
            failures=self.failures,
            threshold=self.threshold,
        )


@dataclasses.dataclass(frozen=True)
class Container(_max_posargs(1)):
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
    _base_plan: dict[str, Any] = dataclasses.field(default_factory=dict)
    # We expect most of the user-facing testing to be covered by this 'layers' attribute,
    # as it is all that will be known when unit-testing.
    layers: dict[str, pebble.Layer] = dataclasses.field(default_factory=dict)
    """All :class:`ops.pebble.Layer` definitions that have already been added to the container."""

    service_statuses: dict[str, pebble.ServiceStatus] = dataclasses.field(
        default_factory=dict,
    )
    """The current status of each Pebble service running in the container."""

    # this is how you specify the contents of the filesystem: suppose you want to express that your
    # container has:
    # - /home/foo/bar.py
    # - /bin/bash
    # - /bin/baz
    #
    # this becomes:
    # mounts = {
    #     'foo': Mount(location='/home/foo/', source=Path('/path/to/local/dir/containing/bar/py/'))
    #     'bin': Mount(location='/bin/', source=Path('/path/to/local/dir/containing/bash/and/baz/'))
    # }
    # when the charm runs `pebble.pull`, it will return .open() from one of those paths.
    # when the charm pushes, it will either overwrite one of those paths (careful!) or it will
    # create a tempfile and insert its path in the mock filesystem tree
    mounts: dict[str, Mount] = dataclasses.field(default_factory=dict)
    """Provides access to the contents of the simulated container filesystem.

    For example, suppose you want to express that your container has:

    * ``/home/foo/bar.py``
    * ``/bin/bash``
    * ``/bin/baz``

    this becomes::

        mounts = {
            'foo': Mount('/home/foo', pathlib.Path('/path/to/local/dir/containing/bar/py/')),
            'bin': Mount('/bin/', pathlib.Path('/path/to/local/dir/containing/bash/and/baz/')),
        }
    """

    execs: Iterable[Exec] = frozenset()
    """Simulate executing commands in the container.

    Specify each command the charm might run in the container and an :class:`Exec`
    containing its return code and any stdout/stderr.

    For example::

        container = Container(
            name='foo',
            execs={
                Exec(['whoami'], return_code=0, stdout='ubuntu'),
                Exec(
                    ['dig', '+short', 'canonical.com'],
                    return_code=0,
                    stdout='185.125.190.20\\n185.125.190.21',
                ),
            }
        )
    """

    notices: list[Notice] = dataclasses.field(default_factory=list)
    """Any Pebble notices that already exist in the container."""

    check_infos: frozenset[CheckInfo] = frozenset()
    """All Pebble health checks that have been added to the container."""

    def __hash__(self) -> int:
        return hash(self.name)

    def __post_init__(self):
        if not isinstance(self.execs, frozenset):
            # Allow passing a regular set (or other iterable) of Execs.
            object.__setattr__(self, "execs", frozenset(self.execs))

    def _render_services(self):
        # copied over from ops.testing._TestingPebbleClient._render_services()
        services: dict[str, pebble.Service] = {}
        for key in sorted(self.layers.keys()):
            layer = self.layers[key]
            for name, service in layer.services.items():
                services[name] = service
        return services

    @property
    def plan(self) -> pebble.Plan:
        """The 'computed' Pebble plan.

        This is the base plan plus the layers that have been added on top.
        You should run your assertions on this plan, not so much on the layers,
        as those are input data.
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
    def services(self) -> dict[str, pebble.ServiceInfo]:
        """The Pebble services as rendered in the plan."""
        services = self._render_services()
        infos: dict[str, pebble.ServiceInfo] = {}
        names = sorted(services.keys())
        for name in names:
            try:
                service = services[name]
            except KeyError:
                # in pebble, it just returns "nothing matched" if there are 0 matches,
                # but it ignores services it doesn't recognize
                continue
            status = self.service_statuses.get(name, pebble.ServiceStatus.INACTIVE)
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

    def get_filesystem(self, ctx: Context) -> pathlib.Path:
        """Simulated Pebble filesystem in this context.

        Returns:
            A temporary filesystem containing any files or directories the
            charm pushed to the container.
        """
        return ctx._get_container_root(self.name)


_RawStatusLiteral = Literal[
    "waiting",
    "blocked",
    "active",
    "unknown",
    "error",
    "maintenance",
]


@dataclasses.dataclass(frozen=True)
class _EntityStatus:
    """This class represents StatusBase and should not be interacted with directly."""

    # Why not use StatusBase directly? Because that can't be used with
    # dataclasses.asdict to then be JSON-serializable.

    name: _RawStatusLiteral
    message: str = ""

    _entity_statuses: ClassVar[dict[str, type[_EntityStatus]]] = {}

    def __eq__(self, other: Any):
        if isinstance(other, (StatusBase, _EntityStatus)):
            return (self.name, self.message) == (other.name, other.message)
        return super().__eq__(other)

    def __repr__(self):
        status_type_name = self.name.title() + "Status"
        if self.name == "unknown":
            return f"{status_type_name}()"
        return f"{status_type_name}('{self.message}')"

    @classmethod
    def from_status_name(
        cls,
        name: _RawStatusLiteral,
        message: str = "",
    ) -> _EntityStatus:
        """Convert the status name, such as 'active', to the class, such as ActiveStatus."""
        # Note that this won't work for UnknownStatus.
        # All subclasses have a default 'name' attribute, but the type checker can't tell that.
        return cls._entity_statuses[name](message=message)  # type:ignore

    @classmethod
    def from_ops(cls, obj: StatusBase) -> _EntityStatus:
        """Convert from the ops.StatusBase object to the matching _EntityStatus object."""
        return cls.from_status_name(obj.name, obj.message)


@dataclasses.dataclass(frozen=True, eq=False, repr=False)
class UnknownStatus(_EntityStatus, ops.UnknownStatus):
    __doc__ = ops.UnknownStatus.__doc__

    name: Literal["unknown"] = "unknown"

    def __init__(self):
        super().__init__(name=self.name)


@dataclasses.dataclass(frozen=True, eq=False, repr=False)
class ErrorStatus(_EntityStatus, ops.ErrorStatus):
    __doc__ = ops.ErrorStatus.__doc__

    name: Literal["error"] = "error"

    def __init__(self, message: str = ""):
        super().__init__(name="error", message=message)


@dataclasses.dataclass(frozen=True, eq=False, repr=False)
class ActiveStatus(_EntityStatus, ops.ActiveStatus):
    __doc__ = ops.ActiveStatus.__doc__

    name: Literal["active"] = "active"

    def __init__(self, message: str = ""):
        super().__init__(name="active", message=message)


@dataclasses.dataclass(frozen=True, eq=False, repr=False)
class BlockedStatus(_EntityStatus, ops.BlockedStatus):
    __doc__ = ops.BlockedStatus.__doc__

    name: Literal["blocked"] = "blocked"

    def __init__(self, message: str = ""):
        super().__init__(name="blocked", message=message)


@dataclasses.dataclass(frozen=True, eq=False, repr=False)
class MaintenanceStatus(_EntityStatus, ops.MaintenanceStatus):
    __doc__ = ops.MaintenanceStatus.__doc__

    name: Literal["maintenance"] = "maintenance"

    def __init__(self, message: str = ""):
        super().__init__(name="maintenance", message=message)


@dataclasses.dataclass(frozen=True, eq=False, repr=False)
class WaitingStatus(_EntityStatus, ops.WaitingStatus):
    __doc__ = ops.WaitingStatus.__doc__

    name: Literal["waiting"] = "waiting"

    def __init__(self, message: str = ""):
        super().__init__(name="waiting", message=message)


_EntityStatus._entity_statuses.update(
    unknown=UnknownStatus,
    error=ErrorStatus,
    active=ActiveStatus,
    blocked=BlockedStatus,
    maintenance=MaintenanceStatus,
    waiting=WaitingStatus,
)


@dataclasses.dataclass(frozen=True)
class StoredState(_max_posargs(1)):
    """Represents unit-local state that persists across events."""

    name: str = "_stored"
    """The attribute in the parent Object where the state is stored.

    For example, ``_stored`` in this class::

        class MyCharm(ops.CharmBase):
            _stored = ops.StoredState()

    """

    owner_path: str | None = None
    """The path to the owner of this StoredState instance.

    If None, the owner is the Framework. Otherwise, /-separated object names,
    for example MyCharm/MyCharmLib.
    """

    # Ideally, the type here would be only marshallable types, rather than Any.
    # However, it's complex to describe those types, since it's a recursive
    # definition - even in TypeShed the _Marshallable type includes containers
    # like list[Any], which seems to defeat the point.
    content: dict[str, Any] = dataclasses.field(default_factory=dict)
    """The content of the :class:`ops.StoredState` instance."""

    _data_type_name: str = "StoredStateData"

    @property
    def _handle_path(self):
        return f"{self.owner_path or ''}/{self._data_type_name}[{self.name}]"

    def __hash__(self) -> int:
        return hash(self._handle_path)


_RawPortProtocolLiteral = Literal["tcp", "udp", "icmp"]


@dataclasses.dataclass(frozen=True)
class Port(_max_posargs(1)):
    """Represents a port on the charm host.

    Port objects should not be instantiated directly: use :class:`TCPPort`,
    :class:`UDPPort`, or :class:`ICMPPort` instead.
    """

    port: int | None = None
    """The port to open. Required for TCP and UDP; not allowed for ICMP."""

    protocol: _RawPortProtocolLiteral = "tcp"
    """The protocol that data transferred over the port will use."""

    def __post_init__(self):
        if type(self) is Port:
            raise RuntimeError(
                "Port cannot be instantiated directly; "
                "please use TCPPort, UDPPort, or ICMPPort",
            )

    def __eq__(self, other: object) -> bool:
        if isinstance(other, (Port, ops.Port)):
            return (self.protocol, self.port) == (other.protocol, other.port)
        return False


@dataclasses.dataclass(frozen=True)
class TCPPort(Port):
    """Represents a TCP port on the charm host."""

    port: int  # type: ignore
    """The port to open."""
    protocol: _RawPortProtocolLiteral = "tcp"
    """The protocol that data transferred over the port will use.

    :meta private:
    """

    def __post_init__(self):
        super().__post_init__()
        if not (1 <= self.port <= 65535):
            raise StateValidationError(
                f"`port` outside bounds [1:65535], got {self.port}",
            )


@dataclasses.dataclass(frozen=True)
class UDPPort(Port):
    """Represents a UDP port on the charm host."""

    port: int  # type: ignore
    """The port to open."""
    protocol: _RawPortProtocolLiteral = "udp"
    """The protocol that data transferred over the port will use.

    :meta private:
    """

    def __post_init__(self):
        super().__post_init__()
        if not (1 <= self.port <= 65535):
            raise StateValidationError(
                f"`port` outside bounds [1:65535], got {self.port}",
            )


@dataclasses.dataclass(frozen=True)
class ICMPPort(Port):
    """Represents an ICMP port on the charm host."""

    protocol: _RawPortProtocolLiteral = "icmp"
    """The protocol that data transferred over the port will use.

    :meta private:
    """

    _max_positional_args: Final = 0

    def __post_init__(self):
        super().__post_init__()
        if self.port is not None:
            raise StateValidationError("`port` cannot be set for `ICMPPort`")


_port_cls_by_protocol = {
    "tcp": TCPPort,
    "udp": UDPPort,
    "icmp": ICMPPort,
}


_next_storage_index_counter = 0  # storage indices start at 0


def _next_storage_index(*, update: bool = True):
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
class Storage(_max_posargs(1)):
    """Represents an (attached) storage made available to the charm container."""

    name: str
    """The name of the storage, as found in the charm metadata."""

    index: int = dataclasses.field(default_factory=_next_storage_index)
    """The index of this storage instance.

    For Kubernetes charms, this will always be 1. For machine charms, each new
    Storage instance gets a new index."""

    def __eq__(self, other: object) -> bool:
        if isinstance(other, (Storage, ops.Storage)):
            return (self.name, self.index) == (other.name, other.index)
        return False

    def get_filesystem(self, ctx: Context) -> pathlib.Path:
        """Simulated filesystem root in this context."""
        return ctx._get_storage_root(self.name, self.index)


@dataclasses.dataclass(frozen=True)
class Resource(_max_posargs(0)):
    """Represents a resource made available to the charm."""

    name: str
    """The name of the resource, as found in the charm metadata."""
    path: str | pathlib.Path
    """A local path that will be provided to the charm as the content of the resource."""


@dataclasses.dataclass(frozen=True)
class State(_max_posargs(0)):
    """Represents the Juju-owned portion of a unit's state.

    Roughly speaking, it wraps all hook-tool- and pebble-mediated data a charm can access in its
    lifecycle. For example, status-get will return data from `State.unit_status`, is-leader will
    return data from `State.leader`, and so on.
    """

    config: dict[str, str | int | float | bool] = dataclasses.field(
        default_factory=dict,
    )
    """The present configuration of this charm."""
    relations: Iterable[RelationBase] = dataclasses.field(default_factory=frozenset)
    """All relations that currently exist for this charm."""
    networks: Iterable[Network] = dataclasses.field(default_factory=frozenset)
    """Manual overrides for any relation and extra bindings currently provisioned for this charm.
    If a metadata-defined relation endpoint is not explicitly mapped to a Network in this field,
    it will be defaulted.

    .. warning::
        `extra-bindings` is a deprecated, regretful feature in Juju/ops. For completeness we
        support it, but use at your own risk. If a metadata-defined extra-binding is left empty,
        it will be defaulted.
    """
    containers: Iterable[Container] = dataclasses.field(default_factory=frozenset)
    """All containers (whether they can connect or not) that this charm is aware of."""
    storages: Iterable[Storage] = dataclasses.field(default_factory=frozenset)
    """All **attached** storage instances for this charm.

    If a storage is not attached, omit it from this listing."""

    # we don't use sets to make json serialization easier
    opened_ports: Iterable[Port] = dataclasses.field(default_factory=frozenset)
    """Ports opened by Juju on this charm."""
    leader: bool = False
    """Whether this charm has leadership."""
    model: Model = Model()
    """The model this charm lives in."""
    secrets: Iterable[Secret] = dataclasses.field(default_factory=frozenset)
    """The secrets this charm has access to (as an owner, or as a grantee).

    The presence of a secret in this list entails that the charm can read it.
    Whether it can manage it or not depends on the individual secret's `owner` flag."""
    resources: Iterable[Resource] = dataclasses.field(default_factory=frozenset)
    """All resources that this charm can access."""
    planned_units: int = 1
    """Number of non-dying planned units that are expected to be running this application.

    Use with caution."""

    # Represents the OF's event queue. These events will be emitted before the event being
    # dispatched, and represent the events that had been deferred during the previous run.
    # If the charm defers any events during "this execution", they will be appended
    # to this list.
    deferred: list[DeferredEvent] = dataclasses.field(default_factory=list)
    """Events that have been deferred on this charm by some previous execution."""
    stored_states: Iterable[StoredState] = dataclasses.field(
        default_factory=frozenset,
    )
    """Contents of a charm's stored state."""

    # the current statuses.
    app_status: _EntityStatus = UnknownStatus()
    """Status of the application."""
    unit_status: _EntityStatus = UnknownStatus()
    """Status of the unit."""
    workload_version: str = ""
    """Workload version."""

    def __post_init__(self):
        # Let people pass in the ops classes, and convert them to the appropriate Scenario classes.
        for name in ["app_status", "unit_status"]:
            val = getattr(self, name)
            if isinstance(val, _EntityStatus):
                pass
            elif isinstance(val, StatusBase):
                object.__setattr__(self, name, _EntityStatus.from_ops(val))
            else:
                raise TypeError(f"Invalid status.{name}: {val!r}")
        normalised_ports = [
            Port(protocol=port.protocol, port=port.port)
            if isinstance(port, ops.Port)
            else port
            for port in self.opened_ports
        ]
        if self.opened_ports != normalised_ports:
            object.__setattr__(self, "opened_ports", normalised_ports)
        normalised_storage = [
            Storage(name=storage.name, index=storage.index)
            if isinstance(storage, ops.Storage)
            else storage
            for storage in self.storages
        ]
        if self.storages != normalised_storage:
            object.__setattr__(self, "storages", normalised_storage)

        # ops.Container, ops.Model, ops.Relation, ops.Secret should not be instantiated by charmers.
        # ops.Network does not have the relation name, so cannot be converted.
        # ops.Resources does not contain the source of the resource, so cannot be converted.
        # ops.StoredState is not convenient to initialise with data, so not useful here.

        # It's convenient to pass a set, but we really want the attributes to be
        # frozen sets to increase the immutability of State objects.
        for name in [
            "relations",
            "containers",
            "storages",
            "networks",
            "opened_ports",
            "secrets",
            "resources",
            "stored_states",
        ]:
            val = getattr(self, name)
            # It's ok to pass any iterable (of hashable objects), but you'll get
            # a frozenset as the actual attribute.
            if not isinstance(val, frozenset):
                object.__setattr__(self, name, frozenset(val))

    def _update_workload_version(self, new_workload_version: str):
        """Update the current app version and record the previous one."""
        # We don't keep a full history because we don't expect the app version to change more
        # than once per hook.

        # bypass frozen dataclass
        object.__setattr__(self, "workload_version", new_workload_version)

    def _update_status(
        self,
        new_status: _EntityStatus,
        is_app: bool = False,
    ):
        """Update the current app/unit status."""
        name = "app_status" if is_app else "unit_status"
        # bypass frozen dataclass
        object.__setattr__(self, name, new_status)

    def _update_opened_ports(self, new_ports: frozenset[Port]):
        """Update the current opened ports."""
        # bypass frozen dataclass
        object.__setattr__(self, "opened_ports", new_ports)

    def _update_secrets(self, new_secrets: frozenset[Secret]):
        """Update the current secrets."""
        # bypass frozen dataclass
        object.__setattr__(self, "secrets", new_secrets)

    def get_container(self, container: str, /) -> Container:
        """Get container from this State, based on its name."""
        for state_container in self.containers:
            if state_container.name == container:
                return state_container
        raise KeyError(f"container: {container} not found in the State")

    def get_network(self, binding_name: str, /) -> Network:
        """Get network from this State, based on its binding name."""
        for network in self.networks:
            if network.binding_name == binding_name:
                return network
        raise KeyError(f"network: {binding_name} not found in the State")

    def get_secret(
        self,
        *,
        id: str | None = None,
        label: str | None = None,
    ) -> Secret:
        """Get secret from this State, based on the secret's id or label."""
        if id is None and label is None:
            raise ValueError("An id or label must be provided.")

        for secret in self.secrets:
            if (
                (id and label and secret.id == id and secret.label == label)
                or (id and label is None and secret.id == id)
                or (id is None and label and secret.label == label)
            ):
                return secret
        raise KeyError("secret: not found in the State")

    def get_stored_state(
        self,
        stored_state: str,
        /,
        *,
        owner_path: str | None = None,
    ) -> StoredState:
        """Get stored state from this State, based on the stored state's name and owner_path."""
        for ss in self.stored_states:
            if ss.name == stored_state and ss.owner_path == owner_path:
                return ss
        raise ValueError(f"stored state: {stored_state} not found in the State")

    def get_storage(
        self,
        storage: str,
        /,
        *,
        index: int | None = 0,
    ) -> Storage:
        """Get storage from this State, based on the storage's name and index."""
        for state_storage in self.storages:
            if state_storage.name == storage and storage.index == index:
                return state_storage
        raise ValueError(
            f"storage: name={storage}, index={index} not found in the State",
        )

    def get_relation(self, relation: int, /) -> RelationBase:
        """Get relation from this State, based on the relation's id."""
        for state_relation in self.relations:
            if state_relation.id == relation:
                return state_relation
        raise KeyError(f"relation: id={relation} not found in the State")

    def get_relations(self, endpoint: str) -> tuple[RelationBase, ...]:
        """Get all relations on this endpoint from the current state."""

        # we rather normalize the endpoint than worry about cursed metadata situations such as:
        # requires:
        #   foo-bar: ...
        #   foo_bar: ...

        normalized_endpoint = _normalise_name(endpoint)
        return tuple(
            r
            for r in self.relations
            if _normalise_name(r.endpoint) == normalized_endpoint
        )


def _is_valid_charmcraft_25_metadata(meta: dict[str, Any]):
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
class _CharmSpec(Generic[CharmType]):
    """Charm spec."""

    charm_type: type[CharmBase]
    meta: dict[str, Any]
    actions: dict[str, Any] | None = None
    config: dict[str, Any] | None = None

    # autoloaded means: we are running a 'real' charm class, living in some
    # /src/charm.py, and the metadata files are 'real' metadata files.
    is_autoloaded: bool = False

    @staticmethod
    def _load_metadata_legacy(charm_root: pathlib.Path):
        """Load metadata from charm projects created with Charmcraft < 2.5."""
        # back in the days, we used to have separate metadata.yaml, config.yaml and actions.yaml
        # files for charm metadata.
        metadata_path = charm_root / "metadata.yaml"
        meta: dict[str, Any] = (
            yaml.safe_load(metadata_path.open()) if metadata_path.exists() else {}
        )

        config_path = charm_root / "config.yaml"
        config = yaml.safe_load(config_path.open()) if config_path.exists() else None

        actions_path = charm_root / "actions.yaml"
        actions = yaml.safe_load(actions_path.open()) if actions_path.exists() else None
        return meta, config, actions

    @staticmethod
    def _load_metadata(charm_root: pathlib.Path):
        """Load metadata from charm projects created with Charmcraft >= 2.5."""
        metadata_path = charm_root / "charmcraft.yaml"
        meta: dict[str, Any] = (
            yaml.safe_load(metadata_path.open()) if metadata_path.exists() else {}
        )
        if not _is_valid_charmcraft_25_metadata(meta):
            meta = {}
        config = meta.pop("config", None)
        actions = meta.pop("actions", None)
        return meta, config, actions

    @staticmethod
    def autoload(charm_type: type[CharmBase]) -> _CharmSpec[CharmType]:
        """Construct a ``_CharmSpec`` object by looking up the metadata from the charm's repo root.

        Will attempt to load the metadata off the ``charmcraft.yaml`` file
        """
        charm_source_path = pathlib.Path(inspect.getfile(charm_type))
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

    def get_all_relations(self) -> list[tuple[str, dict[str, str]]]:
        """A list of all relation endpoints defined in the metadata."""
        return list(
            chain(
                self.meta.get("requires", {}).items(),
                self.meta.get("provides", {}).items(),
                self.meta.get("peers", {}).items(),
            ),
        )


@dataclasses.dataclass(frozen=True)
class DeferredEvent:
    """An event that has been deferred to run prior to the next Juju event.

    Tests should not instantiate this class directly: use the `deferred` method
    of the event instead. For example:

        ctx = Context(MyCharm)
        deferred_start = ctx.on.start().deferred(handler=MyCharm._on_start)
        state = State(deferred=[deferred_start])
    """

    handle_path: str
    owner: str
    observer: str

    # needs to be marshal.dumps-able.
    snapshot_data: dict[Any, Any] = dataclasses.field(default_factory=dict)

    # It would be nicer if people could do something like:
    #   `isinstance(state.deferred[0], ops.StartEvent)`
    # than comparing with the string names, but there's only one `_Event`
    # class in Scenario, and it also needs to be created from the context,
    # which is not available here. For the ops classes, it's complex to create
    # them because they need a Handle.
    @property
    def name(self):
        """A comparable name for the event."""
        return self.handle_path.split("/")[-1].split("[")[0]


class _EventType(str, Enum):
    FRAMEWORK = "framework"
    BUILTIN = "builtin"
    RELATION = "relation"
    ACTION = "action"
    SECRET = "secret"
    STORAGE = "storage"
    WORKLOAD = "workload"
    CUSTOM = "custom"


class _EventPath(str):
    if TYPE_CHECKING:  # pragma: no cover
        name: str
        owner_path: list[str]
        suffix: str
        prefix: str
        is_custom: bool
        type: _EventType

    def __new__(cls, string: str):
        string = _normalise_name(string)
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
    def _get_suffix_and_type(s: str) -> tuple[str, _EventType]:
        for suffix in _RELATION_EVENTS_SUFFIX:
            if s.endswith(suffix):
                return suffix, _EventType.RELATION

        if s.endswith(_ACTION_EVENT_SUFFIX):
            return _ACTION_EVENT_SUFFIX, _EventType.ACTION

        if s in _SECRET_EVENTS:
            return s, _EventType.SECRET

        if s in _FRAMEWORK_EVENTS:
            return s, _EventType.FRAMEWORK

        # Whether the event name indicates that this is a storage event.
        for suffix in _STORAGE_EVENTS_SUFFIX:
            if s.endswith(suffix):
                return suffix, _EventType.STORAGE

        # Whether the event name indicates that this is a workload event.
        if s.endswith(_PEBBLE_READY_EVENT_SUFFIX):
            return _PEBBLE_READY_EVENT_SUFFIX, _EventType.WORKLOAD
        if s.endswith(_PEBBLE_CUSTOM_NOTICE_EVENT_SUFFIX):
            return _PEBBLE_CUSTOM_NOTICE_EVENT_SUFFIX, _EventType.WORKLOAD
        if s.endswith(_PEBBLE_CHECK_FAILED_EVENT_SUFFIX):
            return _PEBBLE_CHECK_FAILED_EVENT_SUFFIX, _EventType.WORKLOAD
        if s.endswith(_PEBBLE_CHECK_RECOVERED_EVENT_SUFFIX):
            return _PEBBLE_CHECK_RECOVERED_EVENT_SUFFIX, _EventType.WORKLOAD

        if s in _BUILTIN_EVENTS:
            return "", _EventType.BUILTIN

        return "", _EventType.CUSTOM


@dataclasses.dataclass(frozen=True)
class _Event:  # type: ignore
    """A Juju, ops, or custom event that can be run against a charm.

    Typically, for simple events, the string name (e.g. ``install``) can be used,
    and for more complex events, an ``event`` property will be available on the
    related object (e.g. ``relation.joined_event``).
    """

    path: str
    args: tuple[Any, ...] = ()
    kwargs: dict[str, Any] = dataclasses.field(default_factory=dict)

    storage: Storage | None = None
    """If this is a storage event, the storage it refers to."""
    relation: RelationBase | None = None
    """If this is a relation event, the relation it refers to."""
    relation_remote_unit_id: int | None = None
    relation_departed_unit_id: int | None = None

    secret: Secret | None = None
    """If this is a secret event, the secret it refers to."""

    # if this is a secret-removed or secret-expired event, the secret revision it refers to
    secret_revision: int | None = None

    container: Container | None = None
    """If this is a workload (container) event, the container it refers to."""

    notice: Notice | None = None
    """If this is a Pebble notice event, the notice it refers to."""

    check_info: CheckInfo | None = None
    """If this is a Pebble check event, the check info it provides."""

    action: _Action | None = None
    """If this is an action event, the :class:`Action` it refers to."""

    _owner_path: list[str] = dataclasses.field(default_factory=list)

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
    def owner_path(self) -> list[str]:
        """Path to the ObjectEvents instance owning this event.

        If this event is defined on the toplevel charm class, it should be ['on'].
        """
        return self._path.owner_path

    @property
    def _is_relation_event(self) -> bool:
        """Whether the event name indicates that this is a relation event."""
        return self._path.type is _EventType.RELATION

    @property
    def _is_action_event(self) -> bool:
        """Whether the event name indicates that this is a relation event."""
        return self._path.type is _EventType.ACTION

    @property
    def _is_secret_event(self) -> bool:
        """Whether the event name indicates that this is a secret event."""
        return self._path.type is _EventType.SECRET

    @property
    def _is_storage_event(self) -> bool:
        """Whether the event name indicates that this is a storage event."""
        return self._path.type is _EventType.STORAGE

    @property
    def _is_workload_event(self) -> bool:
        """Whether the event name indicates that this is a workload event."""
        return self._path.type is _EventType.WORKLOAD

    # this method is private because _CharmSpec is not quite user-facing; also,
    # the user should know.
    def _is_builtin_event(self, charm_spec: _CharmSpec[CharmType]) -> bool:
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
        return self._path.type is not _EventType.CUSTOM

    def deferred(self, handler: Callable[..., Any], event_id: int = 1) -> DeferredEvent:
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

        # Many events have no snapshot data: install, start, stop, remove, config-changed,
        # upgrade-charm, pre-series-upgrade, post-series-upgrade, leader-elected,
        # leader-settings-changed, collect-metrics
        snapshot_data: dict[str, Any] = {}

        # fixme: at this stage we can't determine if the event is a builtin one or not; if it is
        #  not, then the coming checks are meaningless: the custom event could be named like a
        #  relation event but not *be* one.
        if self._is_workload_event:
            # Enforced by the consistency checker, but for type checkers:
            assert self.container is not None
            snapshot_data["container_name"] = self.container.name
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
            elif self.check_info:
                snapshot_data["check_name"] = self.check_info.name

        elif self._is_relation_event:
            # Enforced by the consistency checker, but for type checkers:
            assert self.relation is not None
            relation = self.relation
            if isinstance(relation, PeerRelation):
                # FIXME: relation.unit for peers should point to <this unit>, but we
                #  don't have access to the local app name in this context.
                remote_app = "local"
            elif isinstance(relation, (Relation, SubordinateRelation)):
                remote_app = relation.remote_app_name
            else:
                raise RuntimeError(f"unexpected relation type: {relation!r}")

            snapshot_data.update(
                {
                    "relation_name": relation.endpoint,
                    "relation_id": relation.id,
                    "app_name": remote_app,
                },
            )
            if not self.name.endswith(("_created", "_broken")):
                snapshot_data["unit_name"] = (
                    f"{remote_app}/{self.relation_remote_unit_id}"
                )
            if self.name.endswith("_departed"):
                snapshot_data["departing_unit"] = (
                    f"{remote_app}/{self.relation_departed_unit_id}"
                )

        elif self._is_storage_event:
            # Enforced by the consistency checker, but for type checkers:
            assert self.storage is not None
            snapshot_data.update(
                {
                    "storage_name": self.storage.name,
                    "storage_index": self.storage.index,
                    # "storage_location": str(self.storage.get_filesystem(self._context)),
                },
            )

        elif self._is_secret_event:
            # Enforced by the consistency checker, but for type checkers:
            assert self.secret is not None
            snapshot_data.update(
                {"secret_id": self.secret.id, "secret_label": self.secret.label},
            )
            if self.name.endswith(("_remove", "_expired")):
                snapshot_data["secret_revision"] = self.secret_revision

        elif self._is_action_event:
            # Enforced by the consistency checker, but for type checkers:
            assert self.action is not None
            snapshot_data["id"] = self.action.id

        return DeferredEvent(
            handle_path,
            owner_name,
            handler_name,
            snapshot_data=snapshot_data,
        )


_next_action_id_counter = 1


def _next_action_id(*, update: bool = True):
    """Get the ID the next action to be created will get.

    Pass update=False if you're only inspecting it.
    Pass update=True if you also want to bump it.
    """
    global _next_action_id_counter
    cur = _next_action_id_counter
    if update:
        _next_action_id_counter += 1
    # Juju currently uses numbers for the ID, but in the past used UUIDs, so
    # we need these to be strings.
    return str(cur)


@dataclasses.dataclass(frozen=True)
class _Action(_max_posargs(1)):
    """A ``juju run`` command.

    Used to simulate ``juju run``, passing in any parameters. For example::

        def test_backup_action():
            ctx = Context(MyCharm)
            state = ctx.run(
                ctx.on.action('do_backup', params={'filename': 'foo'}),
                State(),
            )
            assert ctx.action_results == ...
    """

    name: str
    """Juju action name, as found in the charm metadata."""

    params: Mapping[str, AnyJson] = dataclasses.field(default_factory=dict)
    """Parameter values passed to the action."""

    id: str = dataclasses.field(default_factory=_next_action_id)
    """Juju action ID.

    Every action invocation is automatically assigned a new one. Override in
    the rare cases where a specific ID is required."""
