# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

from __future__ import annotations

import dataclasses
import logging
import marshal
import re
import sys
import warnings
from typing import (
    TYPE_CHECKING,
    Any,
    Generic,
    Sequence,
    cast,
)

import ops
import ops.jujucontext
import ops.storage

from ops.framework import _event_regex
from ops._main import _Manager
from ops._main import logger as ops_logger

from .context import Context
from .errors import BadOwnerPath, NoObserverError
from .logger import logger as scenario_logger
from .mocking import _MockModelBackend
from .state import (
    CharmType,
    Container,
    DeferredEvent,
    RelationBase,
    Secret,
    Storage,
    StoredState,
)

if TYPE_CHECKING:  # pragma: no cover
    from .context import Context
    from .state import State, _CharmSpec, _Event

EVENT_REGEX = re.compile(_event_regex)
STORED_STATE_REGEX = re.compile(
    r'((?P<owner_path>.*)\/)?(?P<_data_type_name>\D+)\[(?P<name>.*)\]',
)

logger = scenario_logger.getChild('ops_main_mock')

# pyright: reportPrivateUsage=false


class UnitStateDB:
    """Wraps the unit-state database with convenience methods for adjusting the state."""

    def __init__(self, underlying_store: ops.storage.SQLiteStorage):
        self._db = underlying_store

    def get_stored_states(self) -> frozenset[StoredState]:
        """Load any StoredState data structures from the db."""
        db = self._db
        stored_states: set[StoredState] = set()
        for handle_path in db.list_snapshots():
            if not EVENT_REGEX.match(handle_path) and (
                match := STORED_STATE_REGEX.match(handle_path)
            ):
                stored_state_snapshot = db.load_snapshot(handle_path)
                kwargs = match.groupdict()
                sst = StoredState(content=stored_state_snapshot, **kwargs)
                stored_states.add(sst)

        return frozenset(stored_states)

    def get_deferred_events(self) -> list[DeferredEvent]:
        """Load any DeferredEvent data structures from the db."""
        db = self._db
        deferred: list[DeferredEvent] = []
        for handle_path in db.list_snapshots():
            if EVENT_REGEX.match(handle_path):
                notices = db.notices(handle_path)
                for handle, owner, observer in notices:
                    try:
                        snapshot_data = db.load_snapshot(handle)
                    except ops.storage.NoSnapshotError:
                        snapshot_data: dict[str, Any] = {}

                    event = DeferredEvent(
                        handle_path=handle,
                        owner=owner,
                        observer=observer,
                        snapshot_data=snapshot_data,
                    )
                    deferred.append(event)

        return deferred

    def apply_state(self, state: State):
        """Add DeferredEvent and StoredState from this State instance to the storage."""
        db = self._db
        for event in state.deferred:
            db.save_notice(event.handle_path, event.owner, event.observer)
            try:
                marshal.dumps(event.snapshot_data)
            except ValueError as e:
                raise ValueError(
                    f'unable to save the data for {event}, it must contain only simple types.',
                ) from e
            db.save_snapshot(event.handle_path, event.snapshot_data)

        for stored_state in state.stored_states:
            db.save_snapshot(stored_state._handle_path, stored_state.content)


class Ops(_Manager, Generic[CharmType]):
    """Class to manage stepping through ops setup, event emission and framework commit."""

    def __init__(
        self,
        state: State,
        event: _Event,
        context: Context[CharmType],
        charm_spec: _CharmSpec[CharmType],
        juju_context: ops.jujucontext._JujuContext,
    ):
        self.state = state
        # This is the event passed to `run`, corresponding to the event that
        # caused Juju to start the framework.
        self.event = event
        self.context = context
        self.charm_spec = charm_spec
        self.store = None
        self._juju_context = juju_context
        self.captured_events: list[ops.EventBase] = []

        try:
            import ops_tracing._mock  # break circular import

            self._tracing_mock = ops_tracing._mock.patch_tracing()
            self._tracing_mock.__enter__()
        except ImportError:
            self._tracing_mock = None

        super().__init__(charm_class=self.charm_spec.charm_type, juju_context=juju_context)

    def _load_charm_meta(self):
        metadata = (self._charm_root / 'metadata.yaml').read_text()
        actions_meta = self._charm_root / 'actions.yaml'
        if actions_meta.exists():
            actions_metadata = actions_meta.read_text()
        else:
            actions_metadata = None
        config_meta = self._charm_root / 'config.yaml'
        if config_meta.exists():
            config_metadata = config_meta.read_text()
        else:
            config_metadata = None

        return ops.CharmMeta.from_yaml(metadata, actions_metadata, config_metadata)

    def _make_framework(self, *args: Any, **kwargs: Any):
        return CapturingFramework(*args, context=self.context, **kwargs)

    def _make_model_backend(self):
        # The event here is used in the context of the Juju event that caused
        # the framework to start, so we pass in the original one, even though
        # this backend might be used for a deferred event.
        return _MockModelBackend(
            state=self.state,
            event=self.event,
            context=self.context,
            charm_spec=self.charm_spec,
            juju_context=self._juju_context,
        )

    def _setup_root_logging(self):
        # The warnings module captures this in _showwarning_orig, but we
        # shouldn't really be using a private method, so capture it ourselves as
        # well.
        original_showwarning = warnings.showwarning
        super()._setup_root_logging()
        # Ops also sets up logging to capture warnings, but we want the normal
        # output.
        logging.captureWarnings(False)
        warnings.showwarning = original_showwarning
        # Ops sets sys.excepthook to go to Juju's debug-log, but that's not
        # useful in a testing context, so we reset it here.
        sys.excepthook = sys.__excepthook__

    def _make_storage(self):
        # TODO: add use_juju_for_storage support
        storage = ops.storage.SQLiteStorage(':memory:')
        logger.info('Copying input state to storage.')
        self.store = UnitStateDB(storage)
        self.store.apply_state(self.state)
        return storage

    def _get_event_to_emit(self, charm: ops.CharmBase, event_name: str):
        if self.event._is_custom_event:
            assert self.event.custom_event is not None
            emitter_type = type(self.event.custom_event.emitter)
            # We require the event source to be an attribute on the charm object.
            # Essentially, we are replacing the unbound event with a bound one.
            for attr_name in dir(self.charm):
                attr = getattr(self.charm, attr_name)
                if not isinstance(attr, ops.Object):
                    continue
                for sub_attr_name in dir(attr):
                    sub_attr = getattr(attr, sub_attr_name)
                    if not isinstance(sub_attr, ops.ObjectEvents):
                        continue
                    if type(sub_attr) is not emitter_type:
                        continue
                    return getattr(sub_attr, self.event.custom_event.event_kind)

        owner = self._get_owner(charm, self.event.owner_path) if self.event else charm.on

        try:
            event_to_emit = getattr(owner, event_name)
        except AttributeError:
            ops_logger.debug('Event %s not defined for %s.', event_name, charm)
            raise NoObserverError(
                f'Cannot fire {event_name!r} on {owner}: invalid event (not on charm.on).',
            )
        return event_to_emit

    def _object_to_ops_object(self, obj: Any) -> Any:
        if hasattr(obj, '_to_ops'):
            return obj._to_ops()
        if isinstance(obj, Secret):
            return self.charm.model.get_secret(id=obj.id, label=obj.label)
        if isinstance(obj, RelationBase):
            return self.charm.model.get_relation(obj.endpoint, obj.id)
        if isinstance(obj, Container):
            return self.charm.unit.get_container(obj.name)
        elif isinstance(obj, Storage):
            for storage in self.charm.model.storages[obj.name]:
                if storage.index == obj.index:
                    return storage
        return obj

    def _get_event_args(
        self, charm: ops.CharmBase, bound_event: ops.framework.BoundEvent
    ) -> tuple[list[Any], dict[str, Any]]:
        # For custom events, if the caller provided us with explicit args, we
        # merge them with the Juju ones (to handle libraries subclassing the
        # Juju events). We also handle converting from Scenario to ops types,
        # since the test code typically won't be able to create the ops objects,
        # as a model is required for many.
        args, kwargs = super()._get_event_args(charm, bound_event)
        if self.event.custom_event_args is not None:
            for arg in self.event.custom_event_args:
                args.append(self._object_to_ops_object(arg))
        if self.event.custom_event_kwargs is not None:
            for key, value in self.event.custom_event_kwargs.items():
                kwargs[key] = self._object_to_ops_object(value)
        return args, kwargs

    @staticmethod
    def _get_owner(root: Any, path: Sequence[str]) -> ops.ObjectEvents:
        """Walk path on root to an ObjectEvents instance."""
        obj = root
        for step in path:
            try:
                obj = getattr(obj, step)
            except AttributeError:
                raise BadOwnerPath(
                    f'event_owner_path {path!r} invalid: {step!r} leads to nowhere.',
                )
        if not isinstance(obj, ops.ObjectEvents):
            raise BadOwnerPath(
                f'event_owner_path {path!r} invalid: does not lead to an ObjectEvents instance.',
            )
        return obj

    def _close(self):
        """Now that we're done processing this event, read the charm state and expose it."""
        logger.info('Copying storage to output state.')
        assert self.store is not None
        deferred = self.store.get_deferred_events()
        stored_state = self.store.get_stored_states()
        self.state = dataclasses.replace(self.state, deferred=deferred, stored_states=stored_state)

    def _destroy(self):
        super()._destroy()
        if self._tracing_mock:
            self._tracing_mock.__exit__(None, None, None)


class CapturingFramework(ops.Framework):
    def __init__(self, *args: Any, context: Context[CharmType], **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._context = context

    def _emit(self, event: ops.EventBase):
        if self._context.capture_framework_events or not isinstance(
            event,
            (ops.PreCommitEvent, ops.CommitEvent, ops.CollectStatusEvent),
        ):
            # Dump/undump the event to ensure any custom attributes are (re)set by restore().
            event.restore(event.snapshot())
            self._context.emitted_events.append(event)

        return super()._emit(event)

    def _reemit_single_path(self, single_event_path: str):
        if not self._context.capture_deferred_events:
            return super()._reemit_single_path(single_event_path)

        # Load all notices from storage as events.
        for event_path, _, _ in self._storage.notices(single_event_path):
            event_handle = ops.Handle.from_path(event_path)
            try:
                event = self.load_snapshot(event_handle)
            except ops.NoTypeError:
                continue
            event = cast('ops.EventBase', event)
            event.deferred = False
            self._forget(event)  # prevent tracking conflicts

            # Dump/undump the event to ensure any custom attributes are (re)set by restore().
            event.restore(event.snapshot())
            self._context.emitted_events.append(event)

        return super()._reemit_single_path(single_event_path)
