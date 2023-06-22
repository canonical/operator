import logging
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional, Type, TypeVar, Union

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
    # if not provided, will be autoloaded from charm_type.
    meta: Optional[Dict[str, Any]] = None,
    actions: Optional[Dict[str, Any]] = None,
    config: Optional[Dict[str, Any]] = None,
    charm_root: Optional[Dict["PathLike", "PathLike"]] = None,
    juju_version: str = "3.0",
) -> "State":
    """Trigger a charm execution with an Event and a State.

    Calling this function will call ops' main() and set up the context according to the specified
    State, then emit the event on the charm.

    :arg event: the Event that the charm will respond to. Can be a string or an Event instance.
    :arg state: the State instance to use as data source for the hook tool calls that the charm will
        invoke when handling the Event.
    :arg charm_type: the CharmBase subclass to call ``ops.main()`` on.
    :arg pre_event: callback to be invoked right before emitting the event on the newly
        instantiated charm. Will receive the charm instance as only positional argument.
    :arg post_event: callback to be invoked right after emitting the event on the charm instance.
        Will receive the charm instance as only positional argument.
    :arg meta: charm metadata to use. Needs to be a valid metadata.yaml format (as a python dict).
        If none is provided, we will search for a ``metadata.yaml`` file in the charm root.
    :arg actions: charm actions to use. Needs to be a valid actions.yaml format (as a python dict).
        If none is provided, we will search for a ``actions.yaml`` file in the charm root.
    :arg config: charm config to use. Needs to be a valid config.yaml format (as a python dict).
        If none is provided, we will search for a ``config.yaml`` file in the charm root.
    :arg juju_version: Juju agent version to simulate.
    :arg charm_root: virtual charm root the charm will be executed with.
        If the charm, say, expects a `./src/foo/bar.yaml` file present relative to the
        execution cwd, you need to use this. E.g.:

        >>> virtual_root = tempfile.TemporaryDirectory()
        >>> local_path = Path(local_path.name)
        >>> (local_path / 'foo').mkdir()
        >>> (local_path / 'foo' / 'bar.yaml').write_text('foo: bar')
        >>> scenario, State(), (... charm_root=virtual_root)

    """
    ctx = Context(
        charm_type=charm_type,
        meta=meta,
        actions=actions,
        config=config,
        charm_root=charm_root,
        juju_version=juju_version,
    )
    return ctx.run(event, state=state, pre_event=pre_event, post_event=post_event)
