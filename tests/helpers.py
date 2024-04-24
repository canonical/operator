import dataclasses
import logging
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Type,
    TypeVar,
    Union,
)

import jsonpatch

from scenario.context import DEFAULT_JUJU_VERSION, Context

if TYPE_CHECKING:  # pragma: no cover
    from ops.testing import CharmType

    from scenario.state import State, _Event

    _CT = TypeVar("_CT", bound=Type[CharmType])

    PathLike = Union[str, Path]

logger = logging.getLogger()


def trigger(
    state: "State",
    event: Union[str, "_Event"],
    charm_type: Type["CharmType"],
    pre_event: Optional[Callable[["CharmType"], None]] = None,
    post_event: Optional[Callable[["CharmType"], None]] = None,
    meta: Optional[Dict[str, Any]] = None,
    actions: Optional[Dict[str, Any]] = None,
    config: Optional[Dict[str, Any]] = None,
    charm_root: Optional["PathLike"] = None,
    juju_version: str = DEFAULT_JUJU_VERSION,
) -> "State":
    ctx = Context(
        charm_type=charm_type,
        meta=meta,
        actions=actions,
        config=config,
        charm_root=charm_root,
        juju_version=juju_version,
    )
    if isinstance(event, str):
        if event.startswith("relation_"):
            assert len(state.relations) == 1, "shortcut only works with one relation"
            event = getattr(ctx.on, event)(state.relations[0])
        elif event.startswith("pebble_"):
            assert len(state.containers) == 1, "shortcut only works with one container"
            event = getattr(ctx.on, event)(state.containers[0])
        else:
            event = getattr(ctx.on, event)()
    with ctx.manager(event, state=state) as mgr:
        if pre_event:
            pre_event(mgr.charm)
        state_out = mgr.run()
        if post_event:
            post_event(mgr.charm)
    return state_out


def jsonpatch_delta(input: "State", output: "State"):
    patch = jsonpatch.make_patch(
        dataclasses.asdict(output),
        dataclasses.asdict(input),
    ).patch
    return sort_patch(patch)


def sort_patch(patch: List[Dict], key=lambda obj: obj["path"] + obj["op"]):
    return sorted(patch, key=key)
