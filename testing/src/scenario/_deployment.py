# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Drive several charms together with Juju-shaped operations.

A :class:`Juju` holds applications, each with units that have their own
:class:`State`. Operations such as :meth:`Juju.deploy` and :meth:`Juju.config`
change the model straight away, and :meth:`Juju.settle` runs the events that
Juju would run for them, along with whatever the charms' own changes cause on
their peers.
"""

from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import re
import types
import unittest.mock
from collections import deque
from collections.abc import Generator, Mapping, Sequence
from typing import TYPE_CHECKING, Any, Generic, Literal, NamedTuple, Protocol

from ops import JujuVersion

from . import state as _state_module
from ._juju_errors import JujuError
from .context import _DEFAULT_JUJU_VERSION, Context
from .errors import MetadataNotFoundError
from .state import (
    CharmType,
    CloudSpec,
    Container,
    Event,
    Model,
    PeerRelation,
    RelationBase,
    State,
    Storage,
    _CharmSpec,
)

if TYPE_CHECKING:
    from ops.charm import CharmBase

# How many dispatches Juju.settle() allows before it decides the model will
# not converge: this many per unit, plus this many for each ordered pair of
# units in a peer relation. Peer startup alone costs a relation-joined and a
# relation-changed per pair, so a fixed amount per unit would falsely fail a
# large peer application. The rest leaves room for each unit to answer each
# peer's change.
_SETTLE_DISPATCHES_PER_UNIT = 100
_SETTLE_DISPATCHES_PER_PEER_PAIR = 4

# How many dispatches from the end of the trace a settle error shows.
_TRACE_TAIL = 10

# The model identity a Juju has when the test doesn't give one. Fixed, so that
# everything derived from it (such as secret IDs) is the same on every run.
_DEFAULT_MODEL_NAME = 'test-model'
_DEFAULT_MODEL_UUID = '7e57ca5e-c0de-4a11-be57-5e771ed5eed5'
_DEFAULT_CLOUD_SPEC = CloudSpec(type='kubernetes', name='localhost')

# Juju gives Kubernetes charms a cloud spec from this version on.
_K8S_CLOUD_SPEC_JUJU_VERSION = '3.6.10'

# Juju runs leader-settings-changed on non-leaders before this version, and
# not from it on (Juju 4 removed leader settings).
_NO_LEADER_SETTINGS_JUJU_VERSION = '4.0.0'

# Events that only say "look again". One already waiting for a unit, about the
# same thing, covers a second: config-changed, and relation-changed on any
# endpoint.
_COALESCED_EVENT = 'config_changed'
_COALESCED_SUFFIX = '_relation_changed'

# State fields that describe a unit's place in the model. Juju sets these
# itself, so a state_template may not.
_JUJU_OWNED_FIELDS = (
    'leader',
    'planned_units',
    'model',
    'config',
    'relations',
    'secrets',
    'storages',
)

# A storage ``multiple.range`` in charm metadata: 'm', 'm-n', 'm-' or 'm+'.
_STORAGE_RANGE_RE = re.compile(r'^([0-9]+)([-+]|-[0-9]+)$')

# The Python types each config option type accepts, as Context checks them.
_CONFIG_TYPES: dict[str, type | tuple[type, ...]] = {
    'string': str,
    'int': int,
    'float': float,
    'boolean': bool,
    'secret': str,
}

# The alphabet of a Juju secret ID: an xid, 20 characters of base32hex.
_XID_ALPHABET = '0123456789abcdefghijklmnopqrstuv'


@dataclasses.dataclass(frozen=True)
class CharmSpec(Generic[CharmType]):
    """A charm that runs in the test process: its class and its metadata.

    Deploy one with :meth:`Juju.deploy` to run a charm class defined in the
    test::

        spec = CharmSpec(MyCharm, meta={'name': 'myapp'})
        app = juju.deploy(spec)

    A ``CharmSpec`` is frozen, so one can be deployed any number of times.
    """

    charm_type: type[CharmType]
    """The charm class."""

    meta: Mapping[str, Any]
    """The charm's metadata, shaped like ``charmcraft.yaml``.

    Config options go under ``config`` and actions under ``actions``, as they
    do in ``charmcraft.yaml``, rather than in separate mappings.
    """


class _Candidate(NamedTuple):
    """A unit with events pending, and the first of them: one possible next dispatch."""

    app_name: str
    unit_id: int
    event: Event


@dataclasses.dataclass(frozen=True)
class Dispatch:
    """One event dispatched to one unit, as recorded in a settle trace.

    It's a record of the event as it happened, with no handles to the live
    model: it describes the unit as it was at that point, however the model
    has moved on since, and two ``Dispatch`` objects compare by value. The
    only other thing it keeps is the charm and its metadata, which are fixed
    at deploy, for :meth:`to_context`. The application itself is
    ``juju.apps[dispatch.app_name]``, and the model is
    ``dispatch.state_in.model``.
    """

    event: Event
    """The event that was dispatched."""

    app_name: str
    """The name of the application the unit belongs to."""

    unit_id: int
    """The unit's ID, as in ``myapp/2``."""

    state_in: State
    """The :class:`State` the unit was given.

    That's the state after :class:`Juju` wrote in the shared changes from other
    units, so it's what the charm actually saw, rather than the previous
    dispatch's :attr:`state_out`.
    """

    state_out: State
    """The :class:`State` the charm produced."""

    _: dataclasses.KW_ONLY

    _charm: _Charm | None = dataclasses.field(default=None, repr=False, compare=False)

    # The units that had an event pending when this one was chosen, and which
    # of them was chosen.
    _candidates: tuple[_Candidate, ...] = dataclasses.field(default=(), repr=False, compare=False)
    _chosen: int = dataclasses.field(default=0, repr=False, compare=False)

    @property
    def unit_name(self) -> str:
        """The Juju unit name, for example ``myapp/2``."""
        return f'{self.app_name}/{self.unit_id}'

    def to_context(self) -> Context[CharmBase]:
        """A new :class:`~ops.testing.Context` for the unit as it was at this dispatch.

        The ``Context`` has the charm and metadata the test gave
        :meth:`Juju.deploy`, the application's trust, and the unit's ID.
        Config and leadership come from :attr:`state_in`, so running
        :attr:`event` against :attr:`state_in` runs the dispatch again from
        the same starting point::

            ctx = dispatch.to_context()
            state_out = ctx.run(dispatch.event, dispatch.state_in)

        The rerun isn't always identical to the original. A secret the charm
        creates gets a different ID, and the new ``Context`` has none of the
        files the unit wrote to its containers or storage, so a charm that
        reads them back can behave differently.

        Like :meth:`Unit.to_context`, it's new on every call.

        Raises:
            JujuError: if this ``Dispatch`` wasn't recorded by :meth:`Juju.settle`.
        """
        if self._charm is None:
            raise JujuError('Only a Dispatch from Juju.settle() knows its charm.')
        return self._charm.context(self.unit_id)


@dataclasses.dataclass(frozen=True)
class _Charm:
    """What a ``Context`` for one of an application's units needs. Fixed at deploy."""

    charm_type: type[CharmBase]
    app_name: str
    metadata: Mapping[str, Any]
    config: Mapping[str, Any] | None
    actions: Mapping[str, Any] | None
    juju_version: str
    trust: bool

    def context(self, unit_id: int) -> Context[CharmBase]:
        return Context(
            self.charm_type,
            meta=dict(self.metadata),
            config=dict(self.config) if self.config is not None else None,
            actions=dict(self.actions) if self.actions is not None else None,
            app_name=self.app_name,
            unit_id=unit_id,
            juju_version=self.juju_version,
            app_trusted=self.trust,
        )


class Unit:
    """One unit of an :class:`App`.

    Units are created by :meth:`Juju.deploy` and :meth:`Juju.add_unit`; there
    is no reason to construct one directly.
    """

    def __init__(self, app: App, unit_id: int, state: State):
        self._app = app
        self._id = unit_id
        self._state = state
        # How many events this unit has handled; it seeds the IDs of the
        # secrets the next one creates.
        self._dispatches = 0

    @property
    def app(self) -> App:
        """The application this unit belongs to."""
        return self._app

    @property
    def id(self) -> int:
        """The unit number, as in ``myapp/2``."""
        return self._id

    @property
    def name(self) -> str:
        """The Juju unit name, for example ``myapp/2``."""
        return f'{self._app.name}/{self._id}'

    @property
    def is_leader(self) -> bool:
        """Whether this unit holds leadership."""
        return self._id == self._app._leader_id

    @property
    def state(self) -> State:
        """This unit's :class:`State` as of the last event dispatched to it.

        Reading this never runs charm code. Call :meth:`Juju.settle` first to
        run whatever the operations so far have caused, then assert.
        """
        return self._state

    def to_context(self) -> Context[CharmBase]:
        """A new :class:`~ops.testing.Context` for this unit's charm.

        Use it to run an action against the unit at this point in the test, or
        to carry on with a single-charm test from here::

            ctx = web.leader.to_context()
            ctx.run(ctx.on.action('backup'), web.leader.state)

        The ``Context`` has the application's metadata, config options,
        actions, name and trust, and this unit's ID. It is new on every call,
        so its collections, such as the Juju log, start empty. Running it
        doesn't change this unit or anything else under the :class:`Juju`.
        """
        return self._app._charm.context(self._id)

    def __repr__(self) -> str:
        return f'<Unit {self.name}>'


class App:
    """An application under a :class:`Juju`.

    Applications are created by :meth:`Juju.deploy`; there is no reason to
    construct one directly.
    """

    def __init__(
        self,
        juju: Juju,
        charm: _Charm,
        *,
        settings: dict[str, Any],
        storage: dict[str, int],
        state_template: State,
        order: int,
    ):
        self._juju = juju
        self._charm = charm
        # The options set explicitly, with deploy --config or juju config, as
        # Juju stores them. Whether config-changed runs depends on these, not
        # on the defaults merged over them.
        self._settings = settings
        self._config = {**_default_config(charm.config), **settings}
        # How many instances of each store a new unit gets.
        self._storage = storage
        self._state_template = state_template
        # Where the application comes in the round-robin: its place in
        # deploy order.
        self._order = order
        # One Context per unit, kept for the unit's life. Each Context holds
        # its containers' and storage's simulated filesystems in its own
        # temporary directory, so a new one per event would lose any files
        # the charm wrote.
        self._contexts: dict[int, Context[CharmBase]] = {}
        self._leader_id = 0
        self._units: dict[int, Unit] = {}
        self._next_unit_id = 0
        # A peer relation is one relation that every unit is a member of, so
        # its ID is shared, though each unit holds its own view of it.
        self._peer_ids = {endpoint: juju._new_relation_id() for endpoint in self._peer_endpoints}

    @property
    def name(self) -> str:
        """The application name."""
        return self._charm.app_name

    @property
    def meta(self) -> Mapping[str, Any]:
        """The charm metadata, shaped like ``charmcraft.yaml``.

        Config options are under ``config`` and actions under ``actions``.
        """
        meta = dict(self._charm.metadata)
        if self._charm.config is not None:
            meta['config'] = self._charm.config
        if self._charm.actions is not None:
            meta['actions'] = self._charm.actions
        return types.MappingProxyType(meta)

    @property
    def config(self) -> Mapping[str, Any]:
        """The application's current configuration."""
        return types.MappingProxyType(dict(self._config))

    @property
    def units(self) -> Mapping[int, Unit]:
        """This application's units, by unit number."""
        return types.MappingProxyType(self._units)

    @property
    def leader(self) -> Unit:
        """The unit that holds leadership."""
        return self._units[self._leader_id]

    @property
    def _peer_endpoints(self) -> tuple[str, ...]:
        return tuple(self._charm.metadata.get('peers') or {})

    @property
    def _container_names(self) -> tuple[str, ...]:
        return tuple(self._charm.metadata.get('containers') or {})

    def _containers(self) -> list[Container]:
        """Each unit's starting containers: the template's, or a default.

        None can be connected to until its ``pebble-ready``.
        """
        from_template = {c.name: c for c in self._state_template.containers}
        containers = [
            from_template.pop(name, Container(name=name)) for name in self._container_names
        ]
        # Anything left names a container the metadata doesn't declare; keep
        # it, so that Context's consistency check reports it to the test.
        containers.extend(from_template.values())
        return containers

    def _run(self, unit_id: int, event: Event, state: State, secret_seed: str) -> State:
        ctx = self._contexts.get(unit_id)
        if ctx is None:
            ctx = self._contexts[unit_id] = self._charm.context(unit_id)
        with _secret_ids(secret_seed):
            return ctx.run(event, state)

    def __repr__(self) -> str:
        return f'<App {self.name} ({len(self._units)} units)>'


class _Rebind(NamedTuple):
    """Which object in the unit's state an event should be bound to when it's dispatched.

    The consistency checker requires an event's relation or container to
    equal the one in the state it runs against, and the state moves on while
    the event waits.
    """

    kind: Literal['relation', 'container']
    key: int | str
    """The relation ID or the container name."""


class _Queued(NamedTuple):
    """An event waiting in a unit's queue."""

    event: Event
    rebind: _Rebind | None = None


class _Scheduler(Protocol):
    def choose(self, candidates: Sequence[_Candidate]) -> int:
        """Pick the next dispatch: an index into ``candidates``, which is never empty."""
        ...


class _RoundRobin:
    """The default scheduler: each unit in turn.

    ``Juju`` lists the candidates starting from the unit after the last one
    that had a turn, so the next in turn is always the first.
    """

    def choose(self, candidates: Sequence[_Candidate]) -> int:
        return 0


class Juju:
    """A set of applications, driven with Juju-shaped operations.

    Applications are added with :meth:`deploy`, which returns an :class:`App`
    handle::

        juju = Juju()
        web = juju.deploy(CharmSpec(WebCharm, meta=WEB_META), num_units=2)

    Each operation changes the model straight away. Nothing runs until
    :meth:`settle` runs the events Juju would emit for the operations, along
    with whatever the charms' own changes cause on their peers, so most
    tests are a sequence of operations, a ``settle()``, and then assertions::

        juju.config(web, {'log_level': 'debug'})
        juju.settle()
        assert web.leader.state.unit_status == ActiveStatus('ready')
    """

    def __init__(
        self,
        model_name: str | None = None,
        *,
        uuid: str | None = None,
        cloud_spec: CloudSpec | None = None,
    ):
        """Create a simulated Juju model, as ``juju add-model`` would.

        Args:
            model_name: The model name. Defaults to ``test-model``.
            uuid: The model's UUID. Defaults to a fixed UUID, so that it's the
                same on every run.
            cloud_spec: The cloud the model is on. Its ``type`` decides the
                model type: ``kubernetes`` for a Kubernetes model, and a
                machine model otherwise. Defaults to a Kubernetes cloud
                named ``localhost``.
        """
        if cloud_spec is None:
            cloud_spec = _DEFAULT_CLOUD_SPEC
        model_type = 'kubernetes' if cloud_spec.type == 'kubernetes' else 'lxd'
        self._model = Model(
            name=model_name if model_name is not None else _DEFAULT_MODEL_NAME,
            uuid=uuid if uuid is not None else _DEFAULT_MODEL_UUID,
            type=model_type,
            cloud_spec=cloud_spec,
        )
        self._apps: dict[str, App] = {}
        # Each unit's own events, in the order they were caused, by
        # application name and unit ID.
        self._queues: dict[tuple[str, int], deque[_Queued]] = {}
        # The round-robin position, (application order, unit ID), of the last
        # unit that had a turn.
        self._turn: tuple[int, int] | None = None
        self._scheduler: _Scheduler = _RoundRobin()
        # Relation IDs are per model in Juju, so they are per Juju here,
        # rather than from the process-wide counter Relation uses.
        self._next_relation_id = 0
        # The units in scope of each peer relation, as (application name,
        # unit ID, relation ID).
        self._in_scope: set[tuple[str, int, int]] = set()
        self._trace: list[Dispatch] = []
        # Juju numbers storage instances from one sequence across the model.
        self._next_storage_id = 0
        self._closed = False

    @property
    def apps(self) -> Mapping[str, App]:
        """Every application deployed under this ``Juju``, by name."""
        return types.MappingProxyType(self._apps)

    def deploy(
        self,
        charm: type[CharmBase] | CharmSpec[Any],
        app: str | None = None,
        *,
        config: Mapping[str, Any] | None = None,
        storage: Mapping[str, int] | None = None,
        state_template: State | None = None,
        trust: bool = False,
        num_units: int = 1,
        juju_version: str = _DEFAULT_JUJU_VERSION,
    ) -> App:
        """Deploy a charm, as ``juju deploy`` would.

        :meth:`settle` runs each unit's startup events: ``install``,
        ``relation-created`` for each peer relation, ``leader-elected`` on the
        leader and, before Juju 4, ``leader-settings-changed`` on the other
        units, ``config-changed``, ``start``, and, in a Kubernetes model,
        ``pebble-ready`` for each container. Each unit also gets a
        ``storage-attached`` for each storage instance. As in Juju, these
        come before ``install`` in a machine model, and after ``start`` in a
        Kubernetes model.

        A container can be connected to from its ``pebble-ready`` on, as in
        Juju, where that's when the unit agent has seen the container's
        Pebble come up. Before that, and always in a machine model,
        ``can_connect`` is false.

        Args:
            charm: A :class:`CharmSpec`, or a charm class, which is shorthand
                for a ``CharmSpec`` with its metadata loaded from the files
                beside its source, as ``Context`` does.
            app: Application name. Defaults to the charm's name from its
                metadata.
            config: Application configuration, merged over the defaults
                declared in the charm's config options.
            storage: How many instances of each store each unit gets, as
                with ``juju deploy --storage <store>=<count>``. A store that
                isn't listed gets the minimum its metadata allows, which is
                one unless it sets ``multiple``.
            state_template: The starting :class:`State` for every unit of the
                application, including units added later with
                :meth:`add_unit`. Use it for what ``Juju`` can't know, such as
                ``Exec`` mocks and layers on containers, resources and stored
                state. ``Juju`` sets each unit's ``leader``,
                ``planned_units``, ``model``, ``config``, ``relations``,
                ``secrets`` and ``storages`` itself, so the template may not
                set those. ``Juju`` also decides when a container can be
                connected to, so a template container may not set
                ``can_connect``.
            trust: Whether the application has Juju trust, as with
                ``juju deploy --trust``.
            num_units: How many units to deploy. Unit ``0`` is the leader.
            juju_version: The Juju agent version to simulate. From Juju 4
                on, there are no leader settings, so the units that aren't
                the leader get no ``leader-settings-changed``.

        Raises:
            JujuError: if an application of this name already exists,
                ``num_units`` is not positive, the charm has no metadata,
                the template sets a field ``Juju`` owns (including a
                container's ``can_connect``), ``config`` doesn't
                match the charm's config options, or ``storage`` doesn't
                match the charm's stores.
        """
        self._check_open()
        if num_units < 1:
            raise JujuError(f'num_units must be at least 1, not {num_units}.')
        charm_type, metadata, config_schema, actions = _load_charm(charm, app)
        app_name = app or metadata.get('name')
        if not app_name:
            raise JujuError('Could not determine the application name; pass app=.')
        if app_name in self._apps:
            raise JujuError(f'An application named {app_name!r} is already deployed.')
        if state_template is not None:
            _check_state_template(state_template)
        _check_config(app_name, config_schema, config or {})
        storage_counts = _storage_counts(app_name, metadata, storage or {})
        new_app = App(
            self,
            _Charm(charm_type, app_name, metadata, config_schema, actions, juju_version, trust),
            settings=dict(config or {}),
            storage=storage_counts,
            state_template=state_template if state_template is not None else State(),
            order=len(self._apps),
        )
        self._apps[app_name] = new_app
        for _ in range(num_units):
            self._add_unit(new_app)
        return new_app

    def add_unit(self, app: App) -> Unit:
        """Add a unit to an application, as ``juju add-unit`` would.

        :meth:`settle` runs the new unit's startup events, as for
        :meth:`deploy`. Once its ``relation-created`` for a peer relation has
        run, it sees each other unit join that relation, with
        ``relation-joined`` then ``relation-changed``, and they see it join.

        Returns:
            The new :class:`Unit`.
        """
        self._check_open()
        self._check_deployed(app)
        return self._add_unit(app)

    def config(self, app: App, config: Mapping[str, Any]) -> None:
        """Change an application's configuration, as ``juju config`` would.

        The new values are merged over the existing ones and are in every
        unit's :class:`State` straight away. :meth:`settle` runs
        ``config-changed`` on each unit, once however many times this is
        called before it.

        As in Juju, nothing runs if every option is already set to the value
        given. An option that has only its default counts as unset, so
        setting it to the default value explicitly does run
        ``config-changed``.

        Raises:
            JujuError: if an option isn't one of the charm's config options,
                or a value is the wrong type for its option.
        """
        self._check_open()
        self._check_deployed(app)
        _check_config(app.name, app._charm.config, config)
        settings = {**app._settings, **config}
        if settings == app._settings:
            return
        app._settings = settings
        app._config = {**_default_config(app._charm.config), **settings}
        for unit in app._units.values():
            unit._state = dataclasses.replace(unit._state, config=dict(app._config))
            self._enqueue(app, unit.id, Event('config_changed'))

    def settle(self) -> Sequence[Dispatch]:
        """Run events until the model converges.

        The model has converged when no unit has an event left to run: every
        event an operation caused has been dispatched, along with every event
        those dispatches caused in turn.

        The order is fixed, so the same operations on the same starting states
        settle the same way on every run, as long as the charms themselves are
        deterministic. Each unit runs its own events in the order they were
        caused, and the units take turns, one event each.

        The loop check looks at one unit at a time, not the whole model. A
        deterministic charm given the same event and ``State`` again writes
        what it wrote before, so it can't move the model on. In theory, a
        unit could see an earlier view again while other units are still
        making progress, for example if a peer sets a value and then clears
        it. That would be reported as a loop, although waiting
        ``relation-changed`` events are merged, which has so far kept that
        from happening.

        Returns:
            The events dispatched, in order, each with the unit it went to and
            that unit's :class:`State` before and after.

        Raises:
            JujuError: if the model does not converge. The same event reaching
                the same unit with the same :class:`State` twice is a loop,
                and is reported as soon as it happens; otherwise, the limit
                grows with the number of units in the model, and with the
                number of pairs of peers. The message ends with the last
                events dispatched.
        """
        return self._settle()

    def close(self) -> None:
        """Close the model. Safe to call more than once."""
        for app in self._apps.values():
            app._contexts.clear()
        self._apps.clear()
        self._queues.clear()
        self._closed = True

    def __enter__(self) -> Juju:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _settle(self, *, budget: int | None = None) -> list[Dispatch]:
        """Settle, or stop after ``budget`` dispatches, leaving the rest pending."""
        self._check_open()
        # The trace and the loop check start again on every call, so a caller
        # that steps with a small budget never reaches the dispatch limit or
        # sees a loop. Stepping that needs those checks has to keep its own
        # count and history across calls.
        self._trace = []
        seen: dict[tuple[str, int, str], list[tuple[Event, State]]] = {}
        while budget is None or len(self._trace) < budget:
            candidates = self._candidates()
            if not candidates:
                break
            if len(self._trace) >= self._settle_limit():
                raise JujuError(
                    f'Did not converge after {len(self._trace)} events. Check for charms '
                    'that write a new value to a databag on every event.'
                    f'{self._trace_tail()}'
                )
            chosen = self._scheduler.choose(candidates)
            app = self._apps[candidates[chosen].app_name]
            unit = app._units[candidates[chosen].unit_id]
            queued = self._queues[app.name, unit.id].popleft()
            self._turn = (app._order, unit.id)
            event = self._bind(app, unit, queued)
            if event is None:
                continue
            key, compared = _dispatch_key(app, unit, event)
            earlier_dispatches = seen.setdefault(key, [])
            if compared in earlier_dispatches:
                raise JujuError(
                    f'{unit.name} was about to handle {event.name} with the same '
                    'State it had the last time it handled it, so settling would '
                    f'never end.{self._trace_tail()}'
                )
            earlier_dispatches.append(compared)
            self._dispatch(app, unit, event, tuple(candidates), chosen)
        return list(self._trace)

    def _candidates(self) -> list[_Candidate]:
        """The first pending event of each unit, starting from the unit after the last turn."""
        pending = sorted(
            ((self._apps[app_name]._order, unit_id), app_name, unit_id, queue[0].event)
            for (app_name, unit_id), queue in self._queues.items()
            if queue
        )
        after = [
            _Candidate(app_name, unit_id, event)
            for position, app_name, unit_id, event in pending
            if self._turn is None or position > self._turn
        ]
        before = [
            _Candidate(app_name, unit_id, event)
            for position, app_name, unit_id, event in pending
            if self._turn is not None and position <= self._turn
        ]
        return after + before

    def _bind(self, app: App, unit: Unit, queued: _Queued) -> Event | None:
        """The event to dispatch for a queue entry, or ``None`` if it no longer applies."""
        event, rebind = queued
        if rebind is None:
            return event
        if event.name.endswith('_pebble_ready'):
            # Juju runs pebble-ready once it has seen the container's Pebble
            # come up. Pebble may be up a little before that, but a charm
            # can't rely on it, so the model only connects it here.
            unit._state = _with_connectable(unit._state, str(rebind.key))
        if rebind.kind == 'relation' and not self._enter_peer_event(
            app, unit, event, int(rebind.key)
        ):
            return None
        bound = _bound_object(unit._state, rebind)
        # _enter_peer_event has checked the relation is there, and a charm can't
        # remove its own containers.
        assert bound is not None
        return dataclasses.replace(event, **{f'_{rebind.kind}': bound})

    def _enter_peer_event(self, app: App, unit: Unit, event: Event, relation_id: int) -> bool:
        """Bring a unit's view of a peer relation up to the moment of a peer event.

        Returns whether the event should still be dispatched. A unit has the
        relation in its ``State`` from its ``relation-created``, and each peer
        is in its view from that peer's ``relation-joined``.
        """
        view = _relation_by_id(unit._state, relation_id)
        if event.name.endswith('_relation_created'):
            endpoint = next(e for e, i in app._peer_ids.items() if i == relation_id)
            unit._state = _with_relation(unit._state, self._peer_view(app, endpoint))
            return True
        # A unit only has peer events queued once it's in the relation, until
        # units can leave it.
        if not isinstance(view, PeerRelation):
            return False
        peer_id = event._relation_remote_unit_id
        if event.name.endswith('_relation_joined'):
            assert peer_id is not None
            peer_view = _relation_by_id(app._units[peer_id]._state, relation_id)
            data = dict(peer_view.local_unit_data) if peer_view is not None else {}
            peers_data = dict(sorted({**view.peers_data, peer_id: data}.items()))
            unit._state = _with_relation(
                unit._state, dataclasses.replace(view, peers_data=peers_data)
            )
            return True
        # A peer's relation-changed can outlive its place in the unit's view
        # once units can depart; until then it's always queued after the
        # peer's relation-joined.
        return peer_id is None or peer_id in view.peers_data

    def _dispatch(
        self,
        app: App,
        unit: Unit,
        event: Event,
        candidates: tuple[_Candidate, ...],
        chosen: int,
    ) -> None:
        state_in = unit._state
        # Seeded by the unit's own history, so that a secret's ID doesn't
        # depend on what other units ran before it.
        seed = f'{self._model.uuid}/{unit.name}/{unit._dispatches}'
        unit._dispatches += 1
        unit._state = app._run(unit.id, event, state_in, seed)
        self._trace.append(
            Dispatch(
                event,
                app.name,
                unit.id,
                state_in,
                unit._state,
                _charm=app._charm,
                _candidates=candidates,
                _chosen=chosen,
            )
        )
        self._propagate_peers(app, unit)
        if event.name.endswith('_relation_created') and isinstance(event._relation, PeerRelation):
            self._enter_peer_scope(app, unit, event._relation.endpoint)

    def _enter_peer_scope(self, app: App, unit: Unit, endpoint: str) -> None:
        """Put a unit in its peer relation's scope, once its ``relation-created`` has run.

        The entering unit sees each peer already in scope join, and each of
        them sees it join.
        """
        relation_id = app._peer_ids[endpoint]
        self._in_scope.add((app.name, unit.id, relation_id))
        for peer in app._units.values():
            if peer is unit or (app.name, peer.id, relation_id) not in self._in_scope:
                continue
            self._enqueue_peer_joined(app, unit, endpoint, peer.id)
            self._enqueue_peer_joined(app, peer, endpoint, unit.id)

    def _enqueue_peer_joined(self, app: App, unit: Unit, endpoint: str, peer_id: int) -> None:
        relation_id = app._peer_ids[endpoint]
        view = _relation_by_id(unit._state, relation_id) or self._peer_view(app, endpoint)
        for suffix in ('relation_joined', 'relation_changed'):
            self._enqueue(
                app,
                unit.id,
                Event(f'{endpoint}_{suffix}', _relation=view, _relation_remote_unit_id=peer_id),
                _Rebind('relation', relation_id),
            )

    def _propagate_peers(self, app: App, source: Unit) -> None:
        """Carry a unit's peer databag writes to the units that can see them.

        What the unit wrote to its own databag reaches each peer that has seen
        it join, and what the leader wrote to the application databag reaches
        every peer. A peer whose view changed gets ``relation-changed``.
        """
        for endpoint, relation_id in app._peer_ids.items():
            written = _relation_by_id(source._state, relation_id)
            if written is None:
                continue
            for peer in app._units.values():
                view = _relation_by_id(peer._state, relation_id)
                if peer is source or not isinstance(view, PeerRelation):
                    continue
                peers_data = dict(view.peers_data)
                app_data = view.local_app_data
                if source.id in peers_data and peers_data[source.id] != written.local_unit_data:
                    peers_data[source.id] = dict(written.local_unit_data)
                # Only the leader can write the app databag, but a unit that
                # has lost leadership still holds the copy it had.
                if source.is_leader and app_data != written.local_app_data:
                    app_data = dict(written.local_app_data)
                if peers_data == view.peers_data and app_data == view.local_app_data:
                    continue
                peer._state = _with_relation(
                    peer._state,
                    dataclasses.replace(view, peers_data=peers_data, local_app_data=app_data),
                )
                # Not yet what Juju does. Juju runs a separate relation-changed
                # for an app data change, with no remote unit, so the charm
                # sees event.unit as None. Here one event covers both kinds
                # of change and names the writer whenever it's in scope.
                # Splitting them needs a Scenario Event that can be a
                # relation event with no remote unit.
                self._enqueue(
                    app,
                    peer.id,
                    Event(
                        f'{endpoint}_relation_changed',
                        _relation=view,
                        _relation_remote_unit_id=source.id if source.id in peers_data else None,
                    ),
                    _Rebind('relation', relation_id),
                )

    def _add_unit(self, app: App) -> Unit:
        unit_id = app._next_unit_id
        app._next_unit_id += 1
        # A machine charm can declare containers, and Juju deploys it, but
        # only the Kubernetes agent watches containers, so on a machine there
        # is no Pebble to connect to and no pebble-ready.
        is_k8s = self._model.type == 'kubernetes'
        storages: list[Storage] = []
        for name, count in app._storage.items():
            for _ in range(count):
                storages.append(Storage(name, index=self._next_storage_id))
                self._next_storage_id += 1
        state = dataclasses.replace(
            app._state_template,
            config=dict(app._config),
            containers=frozenset(app._containers()),
            storages=frozenset(storages),
            leader=unit_id == app._leader_id,
            model=self._model_for(app._charm.juju_version),
        )
        unit = Unit(app, unit_id, state)
        app._units[unit_id] = unit
        for other in app._units.values():
            other._state = dataclasses.replace(other._state, planned_units=len(app._units))
        self._queues[app.name, unit_id] = deque()
        startup = [_Queued(Event('install'))]
        startup.extend(
            _Queued(
                Event(f'{endpoint}_relation_created', _relation=self._peer_view(app, endpoint)),
                _Rebind('relation', relation_id),
            )
            for endpoint, relation_id in app._peer_ids.items()
        )
        if unit.is_leader:
            leadership = [_Queued(Event('leader_elected'))]
        elif _has_leader_settings(app._charm.juju_version):
            leadership = [_Queued(Event('leader_settings_changed'))]
        else:
            leadership = []
        attached = [
            _Queued(Event(f'{storage.name}_storage_attached', _storage=storage))
            for storage in storages
        ]
        # Juju runs storage-attached before install in a machine model, so
        # the charm can install onto its storage. In a Kubernetes model the
        # storage is provisioned with the pod, and Juju runs storage-attached
        # some time after start. Here it's straight after start, before
        # pebble-ready, every time. Juju can also run pebble-ready any time
        # after install, whenever the workload's Pebble comes up. Putting
        # both after start is deliberate, so that every run is the same.
        if not is_k8s:
            startup[:0] = attached
        startup.extend((
            *leadership,
            _Queued(Event('config_changed')),
            _Queued(Event('start')),
        ))
        if is_k8s:
            startup += attached
            startup.extend(
                _Queued(Event(f'{name}_pebble_ready'), _Rebind('container', name))
                for name in app._container_names
            )
        for event, rebind in startup:
            self._enqueue(app, unit_id, event, rebind)
        return unit

    def _model_for(self, juju_version: str) -> Model:
        """The model as a unit running this Juju version sees it.

        Before 3.6.10, Juju gives a Kubernetes charm no cloud spec.
        """
        if self._model.type == 'kubernetes' and JujuVersion(juju_version) < (
            _K8S_CLOUD_SPEC_JUJU_VERSION
        ):
            return dataclasses.replace(self._model, cloud_spec=None)
        return self._model

    def _peer_view(self, app: App, endpoint: str) -> PeerRelation:
        """A unit's view of a peer relation before any other unit joins it.

        The application databag is already readable, so it starts as the
        leader has it.
        """
        relation_id = app._peer_ids[endpoint]
        leader = app._units.get(app._leader_id)
        existing = _relation_by_id(leader._state, relation_id) if leader is not None else None
        return PeerRelation(
            endpoint=endpoint,
            id=relation_id,
            local_app_data=dict(existing.local_app_data) if existing is not None else {},
        )

    def _enqueue(
        self, app: App, unit_id: int, event: Event, rebind: _Rebind | None = None
    ) -> None:
        """Queue an event for a unit.

        A ``*-changed`` event that is already waiting for the same unit, about
        the same thing, isn't queued twice: the one waiting sees the latest
        data when it runs. Juju coalesces these the same way.
        """
        queue = self._queues[app.name, unit_id]
        coalesced = event.name == _COALESCED_EVENT or event.name.endswith(_COALESCED_SUFFIX)
        if coalesced and any(
            waiting.event.name == event.name
            # The same endpoint can have several relations once apps can be integrated.
            and waiting.rebind == rebind
            and waiting.event._relation_remote_unit_id == event._relation_remote_unit_id
            for waiting in queue
        ):
            return
        queue.append(_Queued(event, rebind))

    def _new_relation_id(self) -> int:
        relation_id = self._next_relation_id
        self._next_relation_id += 1
        return relation_id

    def _check_open(self) -> None:
        if self._closed:
            raise JujuError('This Juju has been closed.')

    def _check_deployed(self, app: App) -> None:
        if self._apps.get(app.name) is not app:
            raise JujuError(f'{app.name} is not deployed in this Juju.')

    def _settle_limit(self) -> int:
        """How many dispatches settle() allows before it reports a model that won't converge."""
        limit = 0
        for app in self._apps.values():
            units = len(app._units)
            pairs = units * (units - 1) * len(app._peer_ids)
            limit += _SETTLE_DISPATCHES_PER_UNIT * units + _SETTLE_DISPATCHES_PER_PEER_PAIR * pairs
        return limit

    def _trace_tail(self) -> str:
        lines = [f'  {d.event.name} on {d.unit_name}' for d in self._trace[-_TRACE_TAIL:]]
        return '\nLast events dispatched:\n' + '\n'.join(lines) if lines else ''


def _dispatch_key(
    app: App, unit: Unit, event: Event
) -> tuple[tuple[str, int, str], tuple[Event, State]]:
    """What identifies a dispatch for loop detection, and what's compared within that."""
    return (app.name, unit.id, event.name), (event, unit._state)


@contextlib.contextmanager
def _secret_ids(seed: str) -> Generator[None]:
    """Make the IDs of secrets created inside the block depend only on ``seed``.

    Scenario gives a new secret a random ID, which would make the final
    ``State`` differ from run to run, so the n-th secret created here gets an
    ID derived from the seed and n.
    """
    count = 0

    def generate() -> str:
        nonlocal count
        digest = hashlib.sha256(f'{seed}/{count}'.encode()).digest()
        count += 1
        value = int.from_bytes(digest[:13], 'big')
        chars: list[str] = []
        for _ in range(20):
            value, index = divmod(value, len(_XID_ALPHABET))
            chars.append(_XID_ALPHABET[index])
        return f'secret:{"".join(chars)}'

    with unittest.mock.patch.object(_state_module, '_generate_secret_id', generate):
        yield


def _load_charm(
    charm: type[CharmBase] | CharmSpec[Any], app: str | None
) -> tuple[type[CharmBase], dict[str, Any], Mapping[str, Any] | None, Mapping[str, Any] | None]:
    """A charm's class, metadata, config options and actions."""
    if isinstance(charm, CharmSpec):
        metadata = dict(charm.meta)
        config = metadata.pop('config', None)
        actions = metadata.pop('actions', None)
        return (
            charm.charm_type,
            metadata,
            dict(config) if config is not None else None,
            dict(actions) if actions is not None else None,
        )
    if not isinstance(charm, type):
        raise JujuError(f'Cannot deploy {charm!r}: pass a charm class or a CharmSpec.')
    try:
        spec = _CharmSpec.autoload(charm)
    except (MetadataNotFoundError, OSError, TypeError):
        name = app or charm.__name__.lower()
        raise JujuError(
            f'{charm.__name__} has no metadata beside its source to load. Wrap it in a '
            f"CharmSpec with the metadata: deploy(CharmSpec({charm.__name__}, meta={{'name': "
            f'{name!r}, ...}})).'
        ) from None
    return charm, dict(spec.meta), spec.config, spec.actions


def _has_leader_settings(juju_version: str) -> bool:
    """Whether a unit running this Juju version gets ``leader-settings-changed``."""
    return JujuVersion(juju_version) < _NO_LEADER_SETTINGS_JUJU_VERSION


def _default_config(config_schema: Mapping[str, Any] | None) -> dict[str, Any]:
    """The defaults declared in a charm's config options, as Juju applies them."""
    options: Mapping[str, Any] = (config_schema or {}).get('options') or {}
    return {name: option['default'] for name, option in options.items() if 'default' in option}


def _check_config(
    app_name: str, config_schema: Mapping[str, Any] | None, config: Mapping[str, Any]
) -> None:
    options: Mapping[str, Any] = (config_schema or {}).get('options') or {}
    for name, value in config.items():
        if name not in options:
            raise JujuError(
                f'{app_name} has no config option {name!r}. '
                f'Its options are: {", ".join(sorted(options)) or "none"}.'
            )
        option_type = options[name].get('type')
        expected = _CONFIG_TYPES.get(option_type)
        if expected is None:
            continue
        # A bool is an int to isinstance(), but not to Juju.
        if not isinstance(value, expected) or (
            option_type != 'boolean' and isinstance(value, bool)
        ):
            raise JujuError(
                f'{app_name} config option {name!r} is a {option_type}, '
                f'not a {type(value).__name__}: {value!r}.'
            )


def _storage_counts(
    app_name: str, metadata: Mapping[str, Any], storage: Mapping[str, int]
) -> dict[str, int]:
    """How many instances of each store a unit gets, checked as Juju checks them."""
    stores: Mapping[str, Any] = metadata.get('storage') or {}
    for name in storage:
        if name not in stores:
            raise JujuError(f'charm {app_name!r} has no store called {name!r}.')
    counts: dict[str, int] = {}
    for name, store in stores.items():
        count_min, count_max = _storage_range(app_name, name, store)
        count = storage.get(name, count_min)
        if count_min == count_max == 1 and count != 1:
            raise JujuError(
                f'charm {app_name!r} store {name!r}: storage is singular, {count} specified.'
            )
        if count < count_min:
            raise JujuError(
                f'charm {app_name!r} store {name!r}: '
                f'{count_min} instances required, {count} specified.'
            )
        if count_max >= 0 and count > count_max:
            raise JujuError(
                f'charm {app_name!r} store {name!r}: '
                f'at most {count_max} instances supported, {count} specified.'
            )
        counts[name] = count
    return counts


def _storage_range(app_name: str, name: str, store: Mapping[str, Any]) -> tuple[int, int]:
    """A store's minimum and maximum instance counts; a maximum of -1 means no limit."""
    multiple = store.get('multiple')
    if not multiple:
        return 1, 1
    count_range = multiple.get('range')
    # Juju reads a plain number, or a string of digits, as both the minimum
    # and the maximum.
    if isinstance(count_range, str) and count_range.isdigit():
        count_range = int(count_range)
    if isinstance(count_range, int) and not isinstance(count_range, bool):
        if count_range <= 0:
            raise JujuError(f'charm {app_name!r} store {name!r}: invalid count {count_range}.')
        return count_range, count_range
    match = _STORAGE_RANGE_RE.match(count_range) if isinstance(count_range, str) else None
    if match is None:
        raise JujuError(
            f"charm {app_name!r} store {name!r}: range {count_range!r} does not match 'm', "
            "'m-n', or 'm+'."
        )
    count_min = int(match.group(1))
    count_max = -1 if len(match.group(2)) == 1 else int(match.group(2)[1:])
    return count_min, count_max


def _check_state_template(template: State) -> None:
    """Reject a ``state_template`` that sets a field :class:`Juju` owns.

    ``State()`` gives every ``Model`` a random name and UUID, so a template's
    model is rejected only when its type or cloud spec isn't the default.
    """
    default = State()
    hints = {
        'model': ' Pass model_name=, uuid= and cloud_spec= to Juju instead.',
        'config': ' Pass config= to deploy() instead.',
        'storages': ' Pass storage= to deploy() instead.',
    }
    for container in template.containers:
        if container.can_connect:
            raise JujuError(
                f'state_template may not set can_connect on container {container.name!r}: '
                'Juju makes a container connectable at its pebble-ready.'
            )
    for name in _JUJU_OWNED_FIELDS:
        value = getattr(template, name)
        if name == 'model':
            if value.type == default.model.type and value.cloud_spec is None:
                continue
        elif value == getattr(default, name):
            continue
        raise JujuError(
            f'state_template may not set {name}: Juju sets it for each unit.{hints.get(name, "")}'
        )


def _bound_object(state: State, rebind: _Rebind) -> RelationBase | Container | None:
    """The object an event should carry, from the state it will run against."""
    if rebind.kind == 'relation':
        return _relation_by_id(state, int(rebind.key))
    return next((c for c in state.containers if c.name == rebind.key), None)


def _relation_by_id(state: State, relation_id: int) -> RelationBase | None:
    return next((r for r in state.relations if r.id == relation_id), None)


def _with_relation(state: State, relation: RelationBase) -> State:
    """A copy of ``state`` with ``relation`` replacing the one with its ID."""
    relations = [r for r in state.relations if r.id != relation.id]
    relations.append(relation)
    return dataclasses.replace(state, relations=frozenset(relations))


def _with_connectable(state: State, container_name: str) -> State:
    """A copy of ``state`` in which the named container can be connected to."""
    containers = [
        dataclasses.replace(c, can_connect=True) if c.name == container_name else c
        for c in state.containers
    ]
    return dataclasses.replace(state, containers=frozenset(containers))
