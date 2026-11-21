# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Drive several charms together with Juju-shaped operations.

A :class:`Juju` holds applications, each with units that have their own
:class:`State`. Operations such as :meth:`Juju.deploy` change the model
straight away, and :meth:`Juju.settle` runs the events that Juju would run
for them.
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
from typing import TYPE_CHECKING, Any, Generic, Literal, NamedTuple

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
    State,
    Storage,
    _CharmSpec,
)

if TYPE_CHECKING:
    from ops.charm import CharmBase

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


@dataclasses.dataclass(frozen=True)
class Dispatch:
    """One event dispatched to one unit, as recorded in a settle trace.

    It's a record of the event as it happened, with no live handles: it
    describes the unit as it was at that point, however the model has moved
    on since, and two ``Dispatch`` objects compare by value. The application
    itself is ``juju.apps[dispatch.app_name]``, and the model is
    ``dispatch.state_in.model``.
    """

    event: Event
    """The event that was dispatched."""

    app_name: str
    """The name of the application the unit belongs to."""

    unit_id: int
    """The unit's ID, as in ``myapp/2``."""

    state_in: State
    """The :class:`State` the unit was given."""

    state_out: State
    """The :class:`State` the charm produced."""

    @property
    def unit_name(self) -> str:
        """The Juju unit name, for example ``myapp/2``."""
        return f'{self.app_name}/{self.unit_id}'


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

    def __repr__(self) -> str:
        return f'<Unit {self.name}>'


class App:
    """An application under a :class:`Juju`.

    Applications are created by :meth:`Juju.deploy`; there is no reason to
    construct one directly.
    """

    def __init__(
        self,
        charm: _Charm,
        *,
        config: dict[str, Any],
        storage: dict[str, int],
        state_template: State,
        order: int,
    ):
        self._charm = charm
        self._config = config
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

    The consistency checker requires an event's container to equal the one in
    the state it runs against, and the state moves on while the event waits.
    """

    kind: Literal['container']
    key: str
    """The container name."""


class _Queued(NamedTuple):
    """An event waiting in a unit's queue."""

    event: Event
    rebind: _Rebind | None = None


class Juju:
    """A set of applications, driven with Juju-shaped operations.

    Applications are added with :meth:`deploy`, which returns an :class:`App`
    handle::

        juju = Juju()
        web = juju.deploy(CharmSpec(WebCharm, meta=WEB_META), num_units=2)

    Each operation changes the model straight away. Nothing runs until
    :meth:`settle` runs the events Juju would emit for the operations, so
    most tests are a sequence of operations, a ``settle()``, and then
    assertions::

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
        ``leader-elected`` on the leader and, before Juju 4,
        ``leader-settings-changed`` on the other units, ``config-changed``,
        ``start``, and, in a Kubernetes
        model, ``pebble-ready`` for each container. Each unit also gets a
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
            _Charm(charm_type, app_name, metadata, config_schema, actions, juju_version, trust),
            config={**_default_config(config_schema), **(config or {})},
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
        :meth:`deploy`.

        Returns:
            The new :class:`Unit`.
        """
        self._check_open()
        self._check_deployed(app)
        return self._add_unit(app)

    def settle(self) -> Sequence[Dispatch]:
        """Run events until the model converges.

        The model has converged when no unit has an event left to run: every
        event an operation caused has been dispatched.

        The order is fixed, so the same operations on the same starting states
        settle the same way on every run, as long as the charms themselves are
        deterministic. Each unit runs its own events in the order they were
        caused, and the units take turns, one event each.

        Returns:
            The events dispatched, in order, each with the unit it went to and
            that unit's :class:`State` before and after.
        """
        self._check_open()
        self._trace = []
        while (next_unit := self._next_unit()) is not None:
            app = self._apps[next_unit[0]]
            unit = app._units[next_unit[1]]
            queued = self._queues[app.name, unit.id].popleft()
            self._turn = (app._order, unit.id)
            self._dispatch(app, unit, self._bind(unit, queued))
        return list(self._trace)

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

    def _next_unit(self) -> tuple[str, int] | None:
        """The next unit with an event pending, starting from the unit after the last turn."""
        pending = sorted(
            ((self._apps[app_name]._order, unit_id), app_name, unit_id)
            for (app_name, unit_id), queue in self._queues.items()
            if queue
        )
        if not pending:
            return None
        _, app_name, unit_id = next(
            (p for p in pending if self._turn is None or p[0] > self._turn), pending[0]
        )
        return app_name, unit_id

    def _bind(self, unit: Unit, queued: _Queued) -> Event:
        """The event to dispatch for a queue entry, bound to the unit's current state."""
        event, rebind = queued
        if rebind is None:
            return event
        if event.name.endswith('_pebble_ready'):
            # Juju runs pebble-ready once it has seen the container's Pebble
            # come up. Pebble may be up a little before that, but a charm
            # can't rely on it, so the model only connects it here.
            unit._state = _with_connectable(unit._state, rebind.key)
        bound = _bound_object(unit._state, rebind)
        assert bound is not None  # A charm can't remove its own containers.
        return dataclasses.replace(event, **{f'_{rebind.kind}': bound})

    def _dispatch(self, app: App, unit: Unit, event: Event) -> None:
        state_in = unit._state
        # Seeded by the unit's own history, so that a secret's ID doesn't
        # depend on what other units ran before it.
        seed = f'{self._model.uuid}/{unit.name}/{unit._dispatches}'
        unit._dispatches += 1
        unit._state = app._run(unit.id, event, state_in, seed)
        self._trace.append(Dispatch(event, app.name, unit.id, state_in, unit._state))

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
        startup = [] if is_k8s else attached
        startup += [
            _Queued(Event('install')),
            *leadership,
            _Queued(Event('config_changed')),
            _Queued(Event('start')),
        ]
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

    def _enqueue(
        self, app: App, unit_id: int, event: Event, rebind: _Rebind | None = None
    ) -> None:
        """Queue an event for a unit."""
        self._queues[app.name, unit_id].append(_Queued(event, rebind))

    def _check_open(self) -> None:
        if self._closed:
            raise JujuError('This Juju has been closed.')

    def _check_deployed(self, app: App) -> None:
        if self._apps.get(app.name) is not app:
            raise JujuError(f'{app.name} is not deployed in this Juju.')


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


def _bound_object(state: State, rebind: _Rebind) -> Container | None:
    """The object an event should carry, from the state it will run against."""
    return next((c for c in state.containers if c.name == rebind.key), None)


def _with_connectable(state: State, container_name: str) -> State:
    """A copy of ``state`` in which the named container can be connected to."""
    containers = [
        dataclasses.replace(c, can_connect=True) if c.name == container_name else c
        for c in state.containers
    ]
    return dataclasses.replace(state, containers=frozenset(containers))
