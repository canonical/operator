import logging
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    Optional,
    Sequence,
    Type,
    TypeVar,
    Union,
)

from scenario.context import Context

if TYPE_CHECKING:
    from ops.testing import CharmType

    from scenario.state import Event, State

    _CT = TypeVar("_CT", bound=Type[CharmType])

    PathLike = Union[str, Path]

logger = logging.getLogger()


def trigger(
    state: "State",
    event: Union["Event", str],
    charm_type: Type["CharmType"],
    pre_event: Optional[Callable[["CharmType"], None]] = None,
    post_event: Optional[Callable[["CharmType"], None]] = None,
    meta: Optional[Dict[str, Any]] = None,
    actions: Optional[Dict[str, Any]] = None,
    config: Optional[Dict[str, Any]] = None,
    charm_root: Optional[Dict["PathLike", "PathLike"]] = None,
    juju_version: str = "3.0",
) -> "State":
    ctx = Context(
        charm_type=charm_type,
        meta=meta,
        actions=actions,
        config=config,
        charm_root=charm_root,
        juju_version=juju_version,
    )
    return ctx.run(
        event,
        state=state,
        pre_event=pre_event,
        post_event=post_event,
    )
