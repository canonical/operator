### This file contains stuff that ideally should be in ops.
# see https://github.com/canonical/operator/pull/862

import inspect
import logging
import os
import warnings
from typing import TYPE_CHECKING, Any, Optional, Tuple, Type

import ops.charm
import ops.framework
import ops.model
import ops.storage
from ops.charm import CharmMeta
from ops.jujuversion import JujuVersion
from ops.log import setup_root_logging

if TYPE_CHECKING:
    from ops.charm import CharmBase, EventBase

from ops.framework import Handle
from ops.main import (
    _Dispatcher,
    _get_charm_dir,
    _get_event_args,
    _should_use_controller_storage,
)

CHARM_STATE_FILE = ".unit-state.db"

logger = logging.getLogger()


def patched_bound_event_emit(self, *args: Any, **kwargs: Any) -> "EventBase":
    """Emit event to all registered observers.

    The current storage state is committed before and after each observer is notified.
    """
    framework = self.emitter.framework
    key = framework._next_event_key()  # noqa
    event = self.event_type(Handle(self.emitter, self.event_kind, key), *args, **kwargs)
    event.framework = framework
    framework._emit(event)  # noqa
    return event


from ops import framework

framework.BoundEvent.emit = patched_bound_event_emit


def _emit_charm_event(charm: "CharmBase", event_name: str) -> Optional["EventBase"]:
    """Emits a charm event based on a Juju event name.

    Args:
        charm: A charm instance to emit an event from.
        event_name: A Juju event name to emit on a charm.
    """
    event_to_emit = None
    try:
        event_to_emit = getattr(charm.on, event_name)
    except AttributeError:
        logger.debug("Event %s not defined for %s.", event_name, charm)

    # If the event is not supported by the charm implementation, do
    # not error out or try to emit it. This is to support rollbacks.
    if event_to_emit is not None:
        args, kwargs = _get_event_args(charm, event_to_emit)
        logger.debug("Emitting Juju event %s.", event_name)
        return event_to_emit.emit(*args, **kwargs)


def main(
    charm_class: Type[ops.charm.CharmBase],
    use_juju_for_storage: Optional[bool] = None,
    pre_event=None,
    post_event=None,
) -> Optional[Tuple["CharmBase", Optional["EventBase"]]]:
    """Setup the charm and dispatch the observed event.

    The event name is based on the way this executable was called (argv[0]).

    Args:
        charm_class: your charm class.
        use_juju_for_storage: whether to use controller-side storage. If not specified
            then kubernetes charms that haven't previously used local storage and that
            are running on a new enough Juju default to controller-side storage,
            otherwise local storage is used.
    """
    charm_dir = _get_charm_dir()

    model_backend = ops.model._ModelBackend()  # pyright: reportPrivateUsage=false
    debug = "JUJU_DEBUG" in os.environ
    setup_root_logging(model_backend, debug=debug)
    logger.debug(
        "Operator Framework %s up and running.", ops.__version__
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

    if use_juju_for_storage and not ops.storage.juju_backend_available():
        # raise an exception; the charm is broken and needs fixing.
        msg = "charm set use_juju_for_storage=True, but Juju version {} does not support it"
        raise RuntimeError(msg.format(JujuVersion.from_environ()))

    if use_juju_for_storage is None:
        use_juju_for_storage = _should_use_controller_storage(charm_state_path, meta)

    if use_juju_for_storage:
        if dispatcher.is_restricted_context():
            # TODO: jam 2020-06-30 This unconditionally avoids running a collect metrics event
            #  Though we eventually expect that juju will run collect-metrics in a
            #  non-restricted context. Once we can determine that we are running collect-metrics
            #  in a non-restricted context, we should fire the event as normal.
            logger.debug(
                '"%s" is not supported when using Juju for storage\n'
                "see: https://github.com/canonical/operator/issues/348",
                dispatcher.event_name,
            )
            # Note that we don't exit nonzero, because that would cause Juju to rerun the hook
            return
        store = ops.storage.JujuStorage()
    else:
        store = ops.storage.SQLiteStorage(charm_state_path)
    framework = ops.framework.Framework(store, charm_dir, meta, model)
    framework.set_breakpointhook()
    try:
        sig = inspect.signature(charm_class)
        try:
            sig.bind(framework)
        except TypeError:
            msg = (
                "the second argument, 'key', has been deprecated and will be "
                "removed after the 0.7 release"
            )
            warnings.warn(msg, DeprecationWarning)
            charm = charm_class(framework, None)
        else:
            charm = charm_class(framework)
        dispatcher.ensure_event_links(charm)

        # TODO: Remove the collect_metrics check below as soon as the relevant
        #       Juju changes are made. Also adjust the docstring on
        #       EventBase.defer().
        #
        # Skip reemission of deferred events for collect-metrics events because
        # they do not have the full access to all hook tools.
        if not dispatcher.is_restricted_context():
            framework.reemit()

        if pre_event:
            pre_event(charm)

        event = _emit_charm_event(charm, dispatcher.event_name)

        if post_event:
            post_event(charm)

        framework.commit()
    finally:
        framework.close()

    return charm, event
