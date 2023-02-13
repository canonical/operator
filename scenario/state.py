import copy
import dataclasses
import datetime
import inspect
import typing
from pathlib import Path, PurePosixPath
from typing import (
    Any,
    Callable,
    Dict,
    Set,
    List,
    Literal,
    Optional,
    Sequence,
    Tuple,
    Type,
    Union,
)
from uuid import uuid4

import yaml
from ops import pebble
from ops.model import SecretRotate

from scenario.logger import logger as scenario_logger
from scenario.mocking import _MockFileSystem, _MockStorageMount
from scenario.runtime import trigger

if typing.TYPE_CHECKING:
    try:
        from typing import Self
    except ImportError:
        from typing_extensions import Self
    from ops.testing import CharmType

logger = scenario_logger.getChild("structs")

ATTACH_ALL_STORAGES = "ATTACH_ALL_STORAGES"
CREATE_ALL_RELATIONS = "CREATE_ALL_RELATIONS"
BREAK_ALL_RELATIONS = "BREAK_ALL_RELATIONS"
DETACH_ALL_STORAGES = "DETACH_ALL_STORAGES"
META_EVENTS = {
    "CREATE_ALL_RELATIONS": "-relation-created",
    "BREAK_ALL_RELATIONS": "-relation-broken",
    "DETACH_ALL_STORAGES": "-storage-detaching",
    "ATTACH_ALL_STORAGES": "-storage-attached",
}


@dataclasses.dataclass
class _DCBase:
    def replace(self, *args, **kwargs):
        return dataclasses.replace(self, *args, **kwargs)

    def copy(self) -> "Self":
        return copy.deepcopy(self)


@dataclasses.dataclass
class Secret(_DCBase):
    id: str

    # mapping from revision IDs to each revision's contents
    contents: Dict[int, Dict[str, str]]

    # indicates if the secret is owned by THIS unit, THIS app or some other app/unit.
    owner: Literal['unit', 'application', None] = None

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
                "This unit will never receive secret-changed for a secret it owns."
            )
        return Event(name="secret-changed", secret=self)

    # owner-only events
    @property
    def rotate_event(self):
        """Sugar to generate a secret-rotate event."""
        if not self.owner:
            raise ValueError(
                "This unit will never receive secret-rotate for a secret it does not own."
            )
        return Event(name="secret-rotate", secret=self)

    @property
    def expired_event(self):
        """Sugar to generate a secret-expired event."""
        if not self.owner:
            raise ValueError(
                "This unit will never receive secret-expire for a secret it does not own."
            )
        return Event(name="secret-expire", secret=self)

    @property
    def remove_event(self):
        """Sugar to generate a secret-remove event."""
        if not self.owner:
            raise ValueError(
                "This unit will never receive secret-removed for a secret it does not own."
            )
        return Event(name="secret-removed", secret=self)


_RELATION_IDS_CTR = 0


@dataclasses.dataclass
class Relation(_DCBase):
    endpoint: str
    remote_app_name: str
    remote_unit_ids: List[int] = dataclasses.field(default_factory=list)

    # local limit
    limit: int = 1

    # scale of the remote application; number of units, leader ID?
    # TODO figure out if this is relevant
    scale: int = 1
    leader_id: int = 0

    # we can derive this from the charm's metadata
    interface: str = None

    # Every new Relation instance gets a new one, if there's trouble, override.
    relation_id: int = -1

    local_app_data: Dict[str, str] = dataclasses.field(default_factory=dict)
    remote_app_data: Dict[str, str] = dataclasses.field(default_factory=dict)
    local_unit_data: Dict[str, str] = dataclasses.field(default_factory=dict)
    remote_units_data: Dict[int, Dict[str, str]] = dataclasses.field(
        default_factory=dict
    )

    def __post_init__(self):
        global _RELATION_IDS_CTR
        if self.relation_id == -1:
            _RELATION_IDS_CTR += 1
            self.relation_id = _RELATION_IDS_CTR

        if self.remote_unit_ids and self.remote_units_data:
            if not set(self.remote_unit_ids) == set(self.remote_units_data):
                raise ValueError(
                    f"{self.remote_unit_ids} should include any and all IDs from {self.remote_units_data}"
                )
        elif self.remote_unit_ids:
            self.remote_units_data = {x: {} for x in self.remote_unit_ids}
        elif self.remote_units_data:
            self.remote_unit_ids = [x for x in self.remote_units_data]
        else:
            self.remote_unit_ids = [0]
            self.remote_units_data = {0: {}}

    @property
    def changed_event(self):
        """Sugar to generate a <this relation>-relation-changed event."""
        return Event(name=self.endpoint + "-relation-changed", relation=self)

    @property
    def joined_event(self):
        """Sugar to generate a <this relation>-relation-joined event."""
        return Event(name=self.endpoint + "-relation-joined", relation=self)

    @property
    def created_event(self):
        """Sugar to generate a <this relation>-relation-created event."""
        return Event(name=self.endpoint + "-relation-created", relation=self)

    @property
    def departed_event(self):
        """Sugar to generate a <this relation>-relation-departed event."""
        return Event(name=self.endpoint + "-relation-departed", relation=self)

    @property
    def broken_event(self):
        """Sugar to generate a <this relation>-relation-broken event."""
        return Event(name=self.endpoint + "-relation-broken", relation=self)


def _random_model_name():
    import random
    import string

    space = string.ascii_letters + string.digits
    return "".join(random.choice(space) for _ in range(20))


@dataclasses.dataclass
class Model(_DCBase):
    name: str = _random_model_name()
    uuid: str = str(uuid4())


# for now, proc mock allows you to map one command to one mocked output.
# todo extend: one input -> multiple outputs, at different times


_CHANGE_IDS = 0


@dataclasses.dataclass
class ExecOutput:
    return_code: int = 0
    stdout: str = ""
    stderr: str = ""

    # change ID: used internally to keep track of mocked processes
    _change_id: int = -1

    def _run(self) -> int:
        global _CHANGE_IDS
        _CHANGE_IDS = self._change_id = _CHANGE_IDS + 1
        return _CHANGE_IDS


_ExecMock = Dict[Tuple[str, ...], ExecOutput]


@dataclasses.dataclass
class Mount(_DCBase):
    location: Union[str, PurePosixPath]
    src: Union[str, Path]

    def __post_init__(self):
        self.src = Path(self.src)


@dataclasses.dataclass
class Container(_DCBase):
    name: str
    can_connect: bool = False
    layers: Dict[str, pebble.Layer] = dataclasses.field(default_factory=dict)
    service_status: Dict[str, pebble.ServiceStatus] = dataclasses.field(
        default_factory=dict
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

    @property
    def filesystem(self) -> _MockFileSystem:
        mounts = {
            name: _MockStorageMount(src=spec.src, location=spec.location)
            for name, spec in self.mounts.items()
        }
        return _MockFileSystem(mounts=mounts)

    @property
    def pebble_ready_event(self):
        """Sugar to generate a <this container's name>-pebble-ready event."""
        if not self.can_connect:
            logger.warning(
                "you **can** fire pebble-ready while the container cannot connect, "
                "but that's most likely not what you want."
            )
        return Event(name=self.name + "-pebble-ready", container=self)


@dataclasses.dataclass
class Address(_DCBase):
    hostname: str
    value: str
    cidr: str


@dataclasses.dataclass
class BindAddress(_DCBase):
    mac_address: str
    interface_name: str
    interfacename: str  # noqa legacy
    addresses: List[Address]

    def hook_tool_output_fmt(self):
        # dumps itself to dict in the same format the hook tool would
        return {
            "bind-addresses": self.mac_address,
            "interface-name": self.interface_name,
            "interfacename": self.interfacename,
            "addresses": [dataclasses.asdict(addr) for addr in self.addresses],
        }


@dataclasses.dataclass
class Network(_DCBase):
    name: str
    bind_id: int

    bind_addresses: List[BindAddress]
    bind_address: str
    egress_subnets: List[str]
    ingress_addresses: List[str]

    is_default: bool = False

    def hook_tool_output_fmt(self):
        # dumps itself to dict in the same format the hook tool would
        return {
            "bind-addresses": [ba.hook_tool_output_fmt() for ba in self.bind_addresses],
            "bind-address": self.bind_address,
            "egress-subnets": self.egress_subnets,
            "ingress-addresses": self.ingress_addresses,
        }

    @classmethod
    def default(
            cls,
            name,
            bind_id,
            private_address: str = "1.1.1.1",
            mac_address: str = "",
            hostname: str = "",
            cidr: str = "",
            interface_name: str = "",
            egress_subnets=("1.1.1.2/32",),
            ingress_addresses=("1.1.1.2",),
    ) -> "Network":
        """Helper to create a minimal, heavily defaulted Network."""
        return cls(
            name=name,
            bind_id=bind_id,
            bind_addresses=[
                BindAddress(
                    mac_address=mac_address,
                    interface_name=interface_name,
                    interfacename=interface_name,
                    addresses=[
                        Address(hostname=hostname, value=private_address, cidr=cidr)
                    ],
                )
            ],
            bind_address=private_address,
            egress_subnets=list(egress_subnets),
            ingress_addresses=list(ingress_addresses),
        )


@dataclasses.dataclass
class Status(_DCBase):
    app: Tuple[str, str] = ("unknown", "")
    unit: Tuple[str, str] = ("unknown", "")
    app_version: str = ""


@dataclasses.dataclass
class State(_DCBase):
    config: Dict[str, Union[str, int, float, bool]] = None
    relations: Sequence[Relation] = dataclasses.field(default_factory=list)
    networks: Sequence[Network] = dataclasses.field(default_factory=list)
    containers: Sequence[Container] = dataclasses.field(default_factory=list)
    status: Status = dataclasses.field(default_factory=Status)
    leader: bool = False
    model: Model = Model()
    juju_log: Sequence[Tuple[str, str]] = dataclasses.field(default_factory=list)
    secrets: List[Secret] = dataclasses.field(default_factory=list)

    # meta stuff: actually belongs in event data structure.
    juju_version: str = "3.0.0"
    unit_id: str = "0"
    app_name: str = "local"

    # todo:
    #  actions?

    @property
    def unit_name(self):
        return self.app_name + "/" + self.unit_id

    def with_can_connect(self, container_name: str, can_connect: bool):
        def replacer(container: Container):
            if container.name == container_name:
                return container.replace(can_connect=can_connect)
            return container

        ctrs = tuple(map(replacer, self.containers))
        return self.replace(containers=ctrs)

    def with_leadership(self, leader: bool):
        return self.replace(leader=leader)

    def with_unit_status(self, status: str, message: str):
        return self.replace(
            status=dataclasses.replace(self.status, unit=(status, message))
        )

    def get_container(self, name) -> Container:
        try:
            return next(filter(lambda c: c.name == name, self.containers))
        except StopIteration as e:
            raise ValueError(f"container: {name}") from e

    # FIXME: not a great way to obtain a delta, but is "complete" todo figure out a better way.
    def jsonpatch_delta(self, other: "State"):
        try:
            import jsonpatch
        except ModuleNotFoundError:
            logger.error(
                "cannot import jsonpatch: using the .delta() "
                "extension requires jsonpatch to be installed."
                "Fetch it with pip install jsonpatch."
            )
            return NotImplemented
        patch = jsonpatch.make_patch(
            dataclasses.asdict(other), dataclasses.asdict(self)
        ).patch
        return sort_patch(patch)

    def trigger(
            self,
            event: Union["Event", str],
            charm_type: Type["CharmType"],
            # callbacks
            pre_event: Optional[Callable[["CharmType"], None]] = None,
            post_event: Optional[Callable[["CharmType"], None]] = None,
            # if not provided, will be autoloaded from charm_type.
            meta: Optional[Dict[str, Any]] = None,
            actions: Optional[Dict[str, Any]] = None,
            config: Optional[Dict[str, Any]] = None,
    ):
        """Fluent API for trigger."""
        return trigger(
            state=self,
            event=event,
            charm_type=charm_type,
            pre_event=pre_event,
            post_event=post_event,
            meta=meta,
            actions=actions,
            config=config,
        )


@dataclasses.dataclass
class _CharmSpec(_DCBase):
    """Charm spec."""

    charm_type: Type["CharmType"]
    meta: Optional[Dict[str, Any]]
    actions: Optional[Dict[str, Any]] = None
    config: Optional[Dict[str, Any]] = None

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
            charm_type=charm_type, meta=meta, actions=actions, config=config
        )


def sort_patch(patch: List[Dict], key=lambda obj: obj["path"] + obj["op"]):
    return sorted(patch, key=key)


@dataclasses.dataclass
class Event(_DCBase):
    name: str
    args: Tuple[Any] = ()
    kwargs: Dict[str, Any] = dataclasses.field(default_factory=dict)

    # if this is a relation event, the relation it refers to
    relation: Optional[Relation] = None

    # if this is a secret event, the secret it refers to
    secret: Optional[Secret] = None

    # if this is a workload (container) event, the container it refers to
    container: Optional[Container] = None

    # todo add other meta for
    #  - secret events
    #  - pebble?
    #  - action?


@dataclasses.dataclass
class Inject(_DCBase):
    """Base class for injectors: special placeholders used to tell harness_ctx
    to inject instances that can't be retrieved in advance in event args or kwargs.
    """

    pass


@dataclasses.dataclass
class InjectRelation(Inject):
    relation_name: str
    relation_id: Optional[int] = None


def _derive_args(event_name: str):
    args = []
    terms = {
        "-relation-changed",
        "-relation-broken",
        "-relation-joined",
        "-relation-departed",
        "-relation-created",
    }

    for term in terms:
        # fixme: we can't disambiguate between relation IDs.
        if event_name.endswith(term):
            args.append(InjectRelation(relation_name=event_name[: -len(term)]))

    return tuple(args)

# todo: consider
#  def get_containers_from_metadata(CharmType, can_connect: bool = False) -> List[Container]:
#     pass
