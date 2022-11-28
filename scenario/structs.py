import dataclasses
from dataclasses import dataclass
from typing import Any, Dict, Literal, Optional, Tuple, Type, Union

from ops.charm import CharmBase
from ops.testing import CharmType

from scenario.runtime import memo
from scenario.consts import META_EVENTS


@dataclass
class DCBase:
    def replace(self, *args, **kwargs):
        return dataclasses.replace(self, *args, **kwargs)

    def copy(self):
        return dataclasses.replace(self)


@dataclass
class Event(DCBase):
    name: str
    args: Tuple[Any] = ()
    kwargs: Dict[str, Any] = dataclasses.field(default_factory=dict)

    @property
    def is_meta(self):
        return self.name in META_EVENTS

    @classmethod
    def from_dict(cls, obj):
        return cls(**obj)

    def as_scene(self, state: "State") -> "Scene":
        """Utility to get to a single-event Scenario from a single event instance."""
        return Scene(context=Context(state=state), event=self)


# from show-relation!
@dataclass
class RelationMeta(memo.RelationMeta, DCBase):
    pass


@dataclass
class RelationSpec(memo.RelationSpec, DCBase):
    pass


def network(
    private_address: str = "1.1.1.1",
    mac_address: str = "",
    hostname: str = "",
    cidr: str = "",
    interface_name: str = "",
    egress_subnets=("1.1.1.2/32",),
    ingress_addresses=("1.1.1.2",),
) -> memo.Network:
    """Construct a network object."""
    return memo.Network(
        bind_addresses=[
            memo.BindAddress(
                mac_address=mac_address,
                interface_name=interface_name,
                interfacename=interface_name,
                addresses=[
                    memo.Address(hostname=hostname, value=private_address, cidr=cidr)
                ],
            )
        ],
        bind_address=private_address,
        egress_subnets=list(egress_subnets),
        ingress_addresses=list(ingress_addresses),
    )


@dataclass
class NetworkSpec(memo.NetworkSpec, DCBase):
    pass


@dataclass
class ContainerSpec(memo.ContainerSpec, DCBase):
    @classmethod
    def from_dict(cls, obj):
        return cls(**obj)


@dataclass
class Model(memo.Model, DCBase):
    pass


@dataclass
class State(memo.State, DCBase):
    def with_can_connect(self, container_name: str, can_connect: bool):
        def replacer(container: ContainerSpec):
            if container.name == container_name:
                return container.replace(can_connect=can_connect)
            return container

        ctrs = tuple(map(replacer, self.containers))
        return self.replace(containers=ctrs)

    def with_leadership(self, leader: bool):
        return self.replace(leader=leader)

    def with_unit_status(self, status: str, message: str):
        return self.replace(status=dataclasses.replace(
            self.status, unit=(status, message)))


@ dataclass
class CharmSpec:
    """Charm spec."""

    charm_type: Type["CharmType"]
    meta: Optional[Dict[str, Any]] = None
    actions: Optional[Dict[str, Any]] = None
    config: Optional[Dict[str, Any]] = None

    @staticmethod
    def cast(obj: Union["CharmSpec", CharmType, Type[CharmBase]]):
        if isinstance(obj, type) and issubclass(obj, CharmBase):
            return CharmSpec(charm_type=obj)
        elif isinstance(obj, CharmSpec):
            return obj
        else:
            raise ValueError(f"cannot convert {obj} to CharmSpec")


@dataclass
class Memo(DCBase):
    calls: Dict[str, Any]
    cursor: int = 0
    caching_policy: Literal["loose", "strict"] = "strict"

    @classmethod
    def from_dict(cls, obj):
        return Memo(**obj)


@dataclass
class Context(DCBase):
    memos: Dict[str, Memo] = dataclasses.field(default_factory=dict)
    state: State = dataclasses.field(default_factory=State.null)

    @classmethod
    def from_dict(cls, obj):
        if obj is None:
            return Context()
        return cls(
            memos={x: Memo.from_dict(m) for x, m in obj.get("memos", {}).items()},
            state=State.from_dict(obj.get("state")),
        )

    def to_dict(self):
        return dataclasses.asdict(self)


@dataclass
class Scene(DCBase):
    event: Event
    context: Context = dataclasses.field(default_factory=Context)

    @classmethod
    def from_dict(cls, obj):
        evt = obj["event"]
        return cls(
            event=Event(evt) if isinstance(evt, str) else Event.from_dict(evt),
            context=Context.from_dict(obj.get("context")),
        )


@dataclass
class Inject:
    """Base class for injectors: special placeholders used to tell harness_ctx
    to inject instances that can't be retrieved in advance in event args or kwargs.
    """

    pass


@dataclass
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


def get_event(name: str, append_args: Tuple[Any] = (), **kwargs) -> Event:
    """This routine will attempt to generate event args for you, based on the event name."""
    return Event(name=name, args=_derive_args(name) + append_args, kwargs=kwargs)
