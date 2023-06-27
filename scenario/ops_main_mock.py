#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import inspect
import os
from typing import TYPE_CHECKING, Any, Callable, Optional, Sequence

import ops.charm
import ops.framework
import ops.model
import ops.storage
from ops import CharmBase
from ops.charm import CharmMeta
from ops.log import setup_root_logging

# use logger from ops.main so that juju_log will be triggered
from ops.main import CHARM_STATE_FILE, _Dispatcher, _get_charm_dir, _get_event_args
from ops.main import logger as ops_logger

if TYPE_CHECKING:
    from ops.testing import CharmType

    from scenario.context import Context
    from scenario.state import Event, State, _CharmSpec


class NoObserverError(RuntimeError):
    """Error raised when the event being dispatched has no registered observers."""


class BadOwnerPath(RuntimeError):
    """Error raised when the owner path does not lead to a valid ObjectEvents instance."""


def _get_owner(root: Any, path: Sequence[str]) -> ops.ObjectEvents:
    """Walk path on root to an ObjectEvents instance."""
    obj = root
    for step in path:
        try:
            obj = getattr(obj, step)
        except AttributeError:
            raise BadOwnerPath(
                f"event_owner_path {path!r} invalid: {step!r} leads to nowhere.",
            )
    if not isinstance(obj, ops.ObjectEvents):
        raise BadOwnerPath(
            f"event_owner_path {path!r} invalid: does not lead to "
            f"an ObjectEvents instance.",
        )
    return obj


def _emit_charm_event(
    charm: "CharmBase",
    event_name: str,
    event: "Event" = None,
):
    """Emits a charm event based on a Juju event name.

    Args:
        charm: A charm instance to emit an event from.
        event_name: A Juju event name to emit on a charm.
        event_owner_path: Event source lookup path.
    """
    owner = _get_owner(charm, event.owner_path) if event else charm.on

    try:
        event_to_emit = getattr(owner, event_name)
    except AttributeError:
        ops_logger.debug("Event %s not defined for %s.", event_name, charm)
        raise NoObserverError(
            f"Cannot fire {event_name!r} on {owner}: "
            f"invalid event (not on charm.on). "
            f"Use Context.run_custom instead.",
        )

    args, kwargs = _get_event_args(charm, event_to_emit)
    ops_logger.debug("Emitting Juju event %s.", event_name)
    event_to_emit.emit(*args, **kwargs)


def main(
    pre_event: Optional[Callable[["CharmType"], None]] = None,
    post_event: Optional[Callable[["CharmType"], None]] = None,
    state: "State" = None,
    event: "Event" = None,
    context: "Context" = None,
    charm_spec: "_CharmSpec" = None,
):
    """Set up the charm and dispatch the observed event."""
    charm_class = charm_spec.charm_type
    charm_dir = _get_charm_dir()

    from scenario.mocking import _MockModelBackend

    model_backend = _MockModelBackend(  # pyright: reportPrivateUsage=false
        state=state,
        event=event,
        context=context,
        charm_spec=charm_spec,
    )
    debug = "JUJU_DEBUG" in os.environ
    setup_root_logging(model_backend, debug=debug)
    ops_logger.debug(
        "Operator Framework %s up and running.",
        ops.__version__,
    )  # type:ignore

    dispatcher = _Dispatcher(charm_dir)
    dispatcher.run_any_legacy_hook()

    metadata = (charm_dir / "metadata.yaml").read_text()
    actions_meta = charm_dir / "actions.yaml"
    if actions_meta.exists():
        actions_metadata = actions_meta.read_text()
    else:
        actions_metadata = None

    meta = CharmMeta.from_yaml(metadata, actions_metadata)
    model = ops.model.Model(meta, model_backend)

    charm_state_path = charm_dir / CHARM_STATE_FILE

    # TODO: add use_juju_for_storage support
    store = ops.storage.SQLiteStorage(charm_state_path)
    framework = ops.framework.Framework(store, charm_dir, meta, model)
    framework.set_breakpointhook()
    try:
        sig = inspect.signature(charm_class)
        sig.bind(framework)  # signature check

        charm = charm_class(framework)
        dispatcher.ensure_event_links(charm)

        # Skip reemission of deferred events for collect-metrics events because
        # they do not have the full access to all hook tools.
        if not dispatcher.is_restricted_context():
            framework.reemit()

        if pre_event:
            pre_event(charm)

        _emit_charm_event(charm, dispatcher.event_name, event)

        if post_event:
            post_event(charm)

        framework.commit()
    finally:
        framework.close()
