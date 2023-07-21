#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import copy
import dataclasses
import datetime
import inspect
import re
import typing
from collections import namedtuple
from itertools import chain
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Dict, List, Literal, Optional, Set, Tuple, Type, Union
from uuid import uuid4

import yaml
from ops import pebble
from ops.charm import CharmEvents
from ops.model import SecretRotate, StatusBase

from scenario.fs_mocks import _MockFileSystem, _MockStorageMount
from scenario.logger import logger as scenario_logger

JujuLogLine = namedtuple("JujuLogLine", ("level", "message"))

if typing.TYPE_CHECKING:
    try:
        from typing import Self
    except ImportError:
        from typing_extensions import Self
    from ops.testing import CharmType

    PathLike = Union[str, Path]
    AnyRelation = Union["Relation", "PeerRelation", "SubordinateRelation"]
    AnyJson = Union[str, bool, dict, int, float, list]

logger = scenario_logger.getChild("state")

ATTACH_ALL_STORAGES = "ATTACH_ALL_STORAGES"
CREATE_ALL_RELATIONS = "CREATE_ALL_RELATIONS"
BREAK_ALL_RELATIONS = "BREAK_ALL_RELATIONS"
DETACH_ALL_STORAGES = "DETACH_ALL_STORAGES"

ACTION_EVENT_SUFFIX = "_action"
PEBBLE_READY_EVENT_SUFFIX = "_pebble_ready"
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
    "secret_removed",
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


@dataclasses.dataclass(frozen=True)
class _DCBase:
    def replace(self, *args, **kwargs):
        """Produce a deep copy of this class, with some arguments replaced with new ones."""
        return dataclasses.replace(self.copy(), *args, **kwargs)

    def copy(self) -> "Self":
        """Produce a deep copy of this object."""
        return copy.deepcopy(self)


@dataclasses.dataclass(frozen=True)
class Secret(_DCBase):
    id: str

    # mapping from revision IDs to each revision's contents
    contents: Dict[int, Dict[str, str]]

    # indicates if the secret is owned by THIS unit, THIS app or some other app/unit.
    owner: Literal["unit", "application", None] = None

    # has this secret been granted to this unit/app or neither? Only applicable if NOT owner
    granted: Literal["unit", "app", False] = False

    # what revision is currently tracked by this charm. Only meaningful if owner=False
    revision: int = 0

    # mapping from relation IDs to remote unit/apps to which this secret has been granted.
    # Only applicable if owner
    remote_grants: Dict[int, Set[str]] = dataclasses.field(default_factory=dict)

    label: Optional[str] = None
    description: Optional[str] = None
    expire: Optional[datetime.datetime] = None
    rotate: SecretRotate = SecretRotate.NEVER

    # consumer-only events
    @property
    def changed_event(self):
        """Sugar to generate a secret-changed event."""
        if self.owner:
            raise ValueError(
                "This unit will never receive secret-changed for a secret it owns.",
            )
        return Event(name="secret_changed", secret=self)

    # owner-only events
    @property
    def rotate_event(self):
        """Sugar to generate a secret-rotate event."""
        if not self.owner:
            raise ValueError(
                "This unit will never receive secret-rotate for a secret it does not own.",
            )
        return Event(name="secret_rotate", secret=self)

    @property
    def expired_event(self):
        """Sugar to generate a secret-expired event."""
        if not self.owner:
            raise ValueError(
                "This unit will never receive secret-expire for a secret it does not own.",
            )
        return Event(name="secret_expire", secret=self)

    @property
    def remove_event(self):
        """Sugar to generate a secret-remove event."""
        if not self.owner:
            raise ValueError(
                "This unit will never receive secret-removed for a secret it does not own.",
            )
        return Event(name="secret_removed", secret=self)

    def _set_revision(self, revision: int):
        """Set a new tracked revision."""
        # bypass frozen dataclass
        object.__setattr__(self, "revision", revision)

    def _update_metadata(
        self,
        content: Optional[Dict[str, str]] = None,
        label: Optional[str] = None,
        description: Optional[str] = None,
        expire: Optional[datetime.datetime] = None,
        rotate: Optional[SecretRotate] = None,
    ):
        """Update the metadata."""
        revision = max(self.contents.keys())
        # bypass frozen dataclass
        object.__setattr__(self, "contents"[revision + 1], content)
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
    """Event names need underscores instead of dashes."""
    return s.replace("-", "_")


class ParametrizedEvent:
    def __init__(self, accept_params: Tuple[str], category: str, *args, **kwargs):
        self._accept_params = accept_params
        self._category = category
        self._args = args
        self._kwargs = kwargs

    def __call__(self, remote_unit: Optional[str] = None) -> "Event":
        """Construct an Event object using the arguments provided at init and any extra params."""
        if remote_unit and "remote_unit" not in self._accept_params:
            raise ValueError(
                f"cannot pass param `remote_unit` to a "
                f"{self._category} event constructor.",
            )

        return Event(*self._args, *self._kwargs, relation_remote_unit_id=remote_unit)

    def deferred(self, handler: Callable, event_id: int = 1) -> "DeferredEvent":
        return self().deferred(handler=handler, event_id=event_id)


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

    # we can derive this from the charm's metadata
    interface: str = None

    # Every new Relation instance gets a new one, if there's trouble, override.
    relation_id: int = dataclasses.field(default_factory=next_relation_id)

    local_app_data: Dict[str, str] = dataclasses.field(default_factory=dict)
    local_unit_data: Dict[str, str] = dataclasses.field(default_factory=dict)

    @property
    def _databags(self):
        """Yield all databags in this relation."""
        yield self.local_app_data
        yield self.local_unit_data

    @property
    def _remote_unit_ids(self) -> Tuple[int]:
        """Ids of the units on the other end of this relation."""
        raise NotImplementedError()

    def _get_databag_for_remote(self, unit_id: int) -> Dict[str, str]:  # noqa: U100
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
            relation=self,
        )

    @property
    def joined_event(self) -> "Event":
        """Sugar to generate a <this relation>-relation-joined event."""
        return Event(
            path=normalize_name(self.endpoint + "-relation-joined"),
            relation=self,
        )

    @property
    def created_event(self) -> "Event":
        """Sugar to generate a <this relation>-relation-created event."""
        return Event(
            path=normalize_name(self.endpoint + "-relation-created"),
            relation=self,
        )

    @property
    def departed_event(self) -> "Event":
        """Sugar to generate a <this relation>-relation-departed event."""
        return Event(
            path=normalize_name(self.endpoint + "-relation-departed"),
            relation=self,
        )

    @property
    def broken_event(self) -> "Event":
        """Sugar to generate a <this relation>-relation-broken event."""
        return Event(
            path=normalize_name(self.endpoint + "-relation-broken"),
            relation=self,
        )


def unify_ids_and_remote_units_data(ids: List[int], data: Dict[int, Any]):
    """Unify and validate a list of unit IDs and a mapping from said ids to databag contents.

    This allows the user to pass equivalently:
    ids = []
    data = {1: {}}

    or

    ids = [1]
    data = {}

    or

    ids = [1]
    data = {1: {}}

    but catch the inconsistent:

    ids = [1]
    data = {2: {}}

    or

    ids = [2]
    data = {1: {}}
    """
    if ids and data:
        if not set(ids) == set(data):
            raise StateValidationError(
                f"{ids} should include any and all IDs from {data}",
            )
    elif ids:
        data = {x: {} for x in ids}
    elif data:
        ids = list(data)
    else:
        ids = [0]
        data = {0: {}}
    return ids, data


@dataclasses.dataclass(frozen=True)
class Relation(RelationBase):
    remote_app_name: str = "remote"

    # fixme: simplify API by deriving remote_unit_ids from remote_units_data.
    remote_unit_ids: List[int] = dataclasses.field(default_factory=list)

    # local limit
    limit: int = 1

    remote_app_data: Dict[str, str] = dataclasses.field(default_factory=dict)
    remote_units_data: Dict[int, Dict[str, str]] = dataclasses.field(
        default_factory=dict,
    )

    def __post_init__(self):
        super().__post_init__()

        remote_unit_ids, remote_units_data = unify_ids_and_remote_units_data(
            self.remote_unit_ids,
            self.remote_units_data,
        )
        # bypass frozen dataclass
        object.__setattr__(self, "remote_unit_ids", remote_unit_ids)
        object.__setattr__(self, "remote_units_data", remote_units_data)

    @property
    def _remote_app_name(self) -> str:
        """Who is on the other end of this relation?"""
        return self.remote_app_name

    @property
    def _remote_unit_ids(self) -> Tuple[int]:
        """Ids of the units on the other end of this relation."""
        return tuple(self.remote_unit_ids)

    def _get_databag_for_remote(self, unit_id: int) -> Dict[str, str]:
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
    remote_app_data: Dict[str, str] = dataclasses.field(default_factory=dict)
    remote_unit_data: Dict[str, str] = dataclasses.field(default_factory=dict)

    # app name and ID of the remote unit that *this unit* is attached to.
    remote_app_name: str = "remote"
    remote_unit_id: int = 0

    @property
    def _remote_unit_ids(self) -> Tuple[int]:
        """Ids of the units on the other end of this relation."""
        return (self.remote_unit_id,)

    def _get_databag_for_remote(self, unit_id: int) -> Dict[str, str]:
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
    peers_data: Dict[int, Dict[str, str]] = dataclasses.field(default_factory=dict)

    # IDs of the peers. Consistency checks will validate that *this unit*'s ID is not in here.
    peers_ids: List[int] = dataclasses.field(default_factory=list)

    @property
    def _databags(self):
        """Yield all databags in this relation."""
        yield self.local_app_data
        yield self.local_unit_data
        yield from self.peers_data.values()

    @property
    def _remote_unit_ids(self) -> Tuple[int]:
        """Ids of the units on the other end of this relation."""
        return tuple(self.peers_ids)

    def _get_databag_for_remote(self, unit_id: int) -> Dict[str, str]:
        """Return the databag for some remote unit ID."""
        return self.peers_data[unit_id]

    def __post_init__(self):
        peers_ids, peers_data = unify_ids_and_remote_units_data(
            self.peers_ids,
            self.peers_data,
        )
        # bypass frozen dataclass guards
        object.__setattr__(self, "peers_ids", peers_ids)
        object.__setattr__(self, "peers_data", peers_data)


def _random_model_name():
    import random
    import string

    space = string.ascii_letters + string.digits
    return "".join(random.choice(space) for _ in range(20))


@dataclasses.dataclass(frozen=True)
class Model(_DCBase):
    name: str = _random_model_name()
    uuid: str = str(uuid4())

    # whatever juju models --format=json | jq '.models[<current-model-index>].type' gives back.
    # TODO: make this exhaustive.
    type: Literal["kubernetes", "lxd"] = "kubernetes"


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
    return_code: int = 0
    stdout: str = ""
    stderr: str = ""

    # change ID: used internally to keep track of mocked processes
    _change_id: int = dataclasses.field(default_factory=_generate_new_change_id)

    def _run(self) -> int:
        return self._change_id


_ExecMock = Dict[Tuple[str, ...], ExecOutput]


@dataclasses.dataclass(frozen=True)
class Mount(_DCBase):
    location: Union[str, PurePosixPath]
    src: Union[str, Path]


@dataclasses.dataclass(frozen=True)
class Container(_DCBase):
    name: str
    can_connect: bool = False

    # This is the base plan. On top of it, one can add layers.
    # We need to model pebble in this way because it's impossible to retrieve the layers from
    # pebble or derive them from the resulting plan (which one CAN get from pebble).
    # So if we are instantiating Container by fetching info from a 'live' charm, the 'layers'
    # will be unknown. all that we can know is the resulting plan (the 'computed plan').
    _base_plan: dict = dataclasses.field(default_factory=dict)
    # We expect most of the user-facing testing to be covered by this 'layers' attribute,
    # as all will be known when unit-testing.
    layers: Dict[str, pebble.Layer] = dataclasses.field(default_factory=dict)

    service_status: Dict[str, pebble.ServiceStatus] = dataclasses.field(
        default_factory=dict,
    )

    # this is how you specify the contents of the filesystem: suppose you want to express that your
    # container has:
    # - /home/foo/bar.py
    # - /bin/bash
    # - /bin/baz
    #
    # this becomes:
    # mounts = {
    #     'foo': Mount('/home/foo/', Path('/path/to/local/dir/containing/bar/py/'))
    #     'bin': Mount('/bin/', Path('/path/to/local/dir/containing/bash/and/baz/'))
    # }
    # when the charm runs `pebble.pull`, it will return .open() from one of those paths.
    # when the charm pushes, it will either overwrite one of those paths (careful!) or it will
    # create a tempfile and insert its path in the mock filesystem tree
    mounts: Dict[str, Mount] = dataclasses.field(default_factory=dict)

    exec_mock: _ExecMock = dataclasses.field(default_factory=dict)

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
        """The 'computed' pebble plan.

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
        """The pebble services as rendered in the plan."""
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

    @property
    def filesystem(self) -> "_MockFileSystem":
        """Simulated pebble filesystem."""
        mounts = {
            name: _MockStorageMount(
                src=Path(spec.src),
                location=PurePosixPath(spec.location),
            )
            for name, spec in self.mounts.items()
        }
        return _MockFileSystem(mounts=mounts)

    @property
    def pebble_ready_event(self):
        """Sugar to generate a <this container's name>-pebble-ready event."""
        if not self.can_connect:
            logger.warning(
                "you **can** fire pebble-ready while the container cannot connect, "
                "but that's most likely not what you want.",
            )
        return Event(path=normalize_name(self.name + "-pebble-ready"), container=self)


@dataclasses.dataclass(frozen=True)
class Address(_DCBase):
    hostname: str
    value: str
    cidr: str
    address: str = ""  # legacy


@dataclasses.dataclass(frozen=True)
class BindAddress(_DCBase):
    interface_name: str
    addresses: List[Address]
    mac_address: Optional[str] = None

    def hook_tool_output_fmt(self):
        # dumps itself to dict in the same format the hook tool would
        # todo support for legacy (deprecated `interfacename` and `macaddress` fields?
        dct = {
            "interface-name": self.interface_name,
            "addresses": [dataclasses.asdict(addr) for addr in self.addresses],
        }
        if self.mac_address:
            dct["mac-address"] = self.mac_address
        return dct


@dataclasses.dataclass(frozen=True)
class Network(_DCBase):
    name: str

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
        name,
        private_address: str = "1.1.1.1",
        hostname: str = "",
        cidr: str = "",
        interface_name: str = "",
        mac_address: Optional[str] = None,
        egress_subnets=("1.1.1.2/32",),
        ingress_addresses=("1.1.1.2",),
    ) -> "Network":
        """Helper to create a minimal, heavily defaulted Network."""
        return cls(
            name=name,
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


@dataclasses.dataclass(frozen=True)
class _EntityStatus(_DCBase):
    """This class represents StatusBase and should not be interacted with directly."""

    # Why not use StatusBase directly? Because that's not json-serializable.

    name: Literal["waiting", "blocked", "active", "unknown", "error", "maintenance"]
    message: str = ""

    def __eq__(self, other):
        if isinstance(other, Tuple):
            logger.warning(
                "Comparing Status with Tuples is deprecated and will be removed soon.",
            )
            return (self.name, self.message) == other
        if isinstance(other, StatusBase):
            return (self.name, self.message) == (other.name, other.message)
        logger.warning(
            f"Comparing Status with {other} is not stable and will be forbidden soon."
            f"Please compare with StatusBase directly.",
        )
        return super().__eq__(other)

    def __iter__(self):
        return iter([self.name, self.message])

    def __repr__(self):
        status_type_name = self.name.title() + "Status"
        return f"{status_type_name}('{self.message}')"


def _status_to_entitystatus(obj: StatusBase) -> _EntityStatus:
    """Convert StatusBase to _EntityStatus."""
    return _EntityStatus(obj.name, obj.message)


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
    relations: List["AnyRelation"] = dataclasses.field(default_factory=list)
    networks: List[Network] = dataclasses.field(default_factory=list)
    containers: List[Container] = dataclasses.field(default_factory=list)
    leader: bool = False
    model: Model = Model()
    secrets: List[Secret] = dataclasses.field(default_factory=list)

    unit_id: int = 0
    # represents the OF's event queue. These events will be emitted before the event being
    # dispatched, and represent the events that had been deferred during the previous run.
    # If the charm defers any events during "this execution", they will be appended
    # to this list.
    deferred: List["DeferredEvent"] = dataclasses.field(default_factory=list)
    stored_state: List["StoredState"] = dataclasses.field(default_factory=list)

    """Represents the 'juju statuses' of the application/unit being tested."""

    # the current statuses. Will be cast to _EntitiyStatus in __post_init__
    app_status: Union[StatusBase, _EntityStatus] = _EntityStatus("unknown")
    unit_status: Union[StatusBase, _EntityStatus] = _EntityStatus("unknown")
    workload_version: str = ""

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
        new_status: str,
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
                self.unit_status,
                unit=_status_to_entitystatus(status),
            ),
        )

    def get_container(self, container: Union[str, Container]) -> Container:
        """Get container from this State, based on an input container or its name."""
        name = container.name if isinstance(container, Container) else container
        try:
            return next(filter(lambda c: c.name == name, self.containers))
        except StopIteration as e:
            raise ValueError(f"container: {name}") from e

    def get_relations(self, endpoint: str) -> Tuple["AnyRelation"]:
        """Get relation from this State, based on an input relation or its endpoint name."""
        try:
            return tuple(filter(lambda c: c.endpoint == endpoint, self.relations))
        except StopIteration as e:
            raise ValueError(f"relation: {endpoint}") from e

    # FIXME: not a great way to obtain a delta, but is "complete". todo figure out a better way.
    def jsonpatch_delta(self, other: "State"):
        try:
            import jsonpatch
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


@dataclasses.dataclass(frozen=True)
class _CharmSpec(_DCBase):
    """Charm spec."""

    charm_type: Type["CharmType"]
    meta: Optional[Dict[str, Any]]
    actions: Optional[Dict[str, Any]] = None
    config: Optional[Dict[str, Any]] = None

    # autoloaded means: trigger() is being invoked on a 'real' charm class, living in some
    # /src/charm.py, and the metadata files are 'real' metadata files.
    is_autoloaded: bool = False

    @staticmethod
    def autoload(charm_type: Type["CharmType"]):
        charm_source_path = Path(inspect.getfile(charm_type))
        charm_root = charm_source_path.parent.parent

        metadata_path = charm_root / "metadata.yaml"
        meta = yaml.safe_load(metadata_path.open())

        actions = config = None

        config_path = charm_root / "config.yaml"
        if config_path.exists():
            config = yaml.safe_load(config_path.open())

        actions_path = charm_root / "actions.yaml"
        if actions_path.exists():
            actions = yaml.safe_load(actions_path.open())

        return _CharmSpec(
            charm_type=charm_type,
            meta=meta,
            actions=actions,
            config=config,
            is_autoloaded=True,
        )


def sort_patch(patch: List[Dict], key=lambda obj: obj["path"] + obj["op"]):
    return sorted(patch, key=key)


@dataclasses.dataclass(frozen=True)
class DeferredEvent(_DCBase):
    handle_path: str
    owner: str
    observer: str

    # needs to be marshal.dumps-able.
    snapshot_data: Dict = dataclasses.field(default_factory=dict)

    @property
    def name(self):
        return self.handle_path.split("/")[-1].split("[")[0]


@dataclasses.dataclass(frozen=True)
class Event(_DCBase):
    path: str
    args: Tuple[Any] = ()
    kwargs: Dict[str, Any] = dataclasses.field(default_factory=dict)

    # if this is a relation event, the relation it refers to
    relation: Optional["AnyRelation"] = None
    # and the name of the remote unit this relation event is about
    relation_remote_unit_id: Optional[int] = None

    # if this is a secret event, the secret it refers to
    secret: Optional[Secret] = None

    # if this is a workload (container) event, the container it refers to
    container: Optional[Container] = None

    # if this is an action event, the Action instance
    action: Optional["Action"] = None

    # todo add other meta for
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
        if "-" in self.path:
            logger.warning(f"Only use underscores in event paths. {self.path!r}")

        path = normalize_name(self.path)
        # bypass frozen dataclass
        object.__setattr__(self, "path", path)

    @property
    def name(self) -> str:
        """Event name."""
        return self.path.split(".")[-1]

    @property
    def owner_path(self) -> List[str]:
        """Path to the ObjectEvents instance owning this event.

        If this event is defined on the toplevel charm class, it should be ['on'].
        """
        return self.path.split(".")[:-1] or ["on"]

    @property
    def _is_relation_event(self) -> bool:
        """Whether the event name indicates that this is a relation event."""
        return any(self.name.endswith(suffix) for suffix in RELATION_EVENTS_SUFFIX)

    @property
    def _is_action_event(self) -> bool:
        """Whether the event name indicates that this is a relation event."""
        return self.name.endswith(ACTION_EVENT_SUFFIX)

    @property
    def _is_secret_event(self) -> bool:
        """Whether the event name indicates that this is a secret event."""
        return self.name in SECRET_EVENTS

    @property
    def _is_storage_event(self) -> bool:
        """Whether the event name indicates that this is a storage event."""
        return any(self.name.endswith(suffix) for suffix in STORAGE_EVENTS_SUFFIX)

    @property
    def _is_workload_event(self) -> bool:
        """Whether the event name indicates that this is a workload event."""
        return self.name.endswith("_pebble_ready")

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
        # assuming it is owned by the charm, is that of a builtin event or not.
        builtins = []
        for relation_name in chain(
            charm_spec.meta.get("requires", ()),
            charm_spec.meta.get("provides", ()),
            charm_spec.meta.get("peers", ()),
        ):
            relation_name = relation_name.replace("-", "_")
            for relation_evt_suffix in RELATION_EVENTS_SUFFIX:
                builtins.append(relation_name + relation_evt_suffix)

        for storage_name in charm_spec.meta.get("storages", ()):
            storage_name = storage_name.replace("-", "_")
            for storage_evt_suffix in STORAGE_EVENTS_SUFFIX:
                builtins.append(storage_name + storage_evt_suffix)

        for action_name in charm_spec.actions or ():
            action_name = action_name.replace("-", "_")
            builtins.append(action_name + ACTION_EVENT_SUFFIX)

        for container_name in charm_spec.meta.get("containers", ()):
            container_name = container_name.replace("-", "_")
            builtins.append(container_name + PEBBLE_READY_EVENT_SUFFIX)

        return event_name in builtins

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
            snapshot_data = {
                "container_name": self.container.name,
            }

        elif self._is_relation_event:
            # this is a RelationEvent. The snapshot:
            snapshot_data = {
                "relation_name": self.relation.endpoint,
                "relation_id": self.relation.relation_id,
                "app_name": self.relation.remote_app_name,
                "unit_name": f"{self.relation.remote_app_name}/{self.relation_remote_unit_id}",
            }

        return DeferredEvent(
            handle_path,
            owner_name,
            handler_name,
            snapshot_data=snapshot_data,
        )


@dataclasses.dataclass(frozen=True)
class Action(_DCBase):
    name: str

    params: Dict[str, "AnyJson"] = dataclasses.field(default_factory=dict)

    @property
    def event(self) -> Event:
        """Helper to generate an action event from this action."""
        return Event(self.name + ACTION_EVENT_SUFFIX, action=self)


def deferred(
    event: Union[str, Event],
    handler: Callable,
    event_id: int = 1,
    relation: "Relation" = None,
    container: "Container" = None,
):
    """Construct a DeferredEvent from an Event or an event name."""
    if isinstance(event, str):
        event = Event(event, relation=relation, container=container)
    return event.deferred(handler=handler, event_id=event_id)


@dataclasses.dataclass(frozen=True)
class Inject(_DCBase):
    """Base class for injectors: special placeholders used to tell harness_ctx
    to inject instances that can't be retrieved in advance in event args or kwargs.
    """


@dataclasses.dataclass(frozen=True)
class InjectRelation(Inject):
    relation_name: str
    relation_id: Optional[int] = None


def _derive_args(event_name: str):
    args = []
    for term in RELATION_EVENTS_SUFFIX:
        # fixme: we can't disambiguate between relation id-s.
        if event_name.endswith(term):
            args.append(InjectRelation(relation_name=event_name[: -len(term)]))

    return tuple(args)


# todo: consider
#  def get_containers_from_metadata(CharmType, can_connect: bool = False) -> List[Container]:
#     pass
