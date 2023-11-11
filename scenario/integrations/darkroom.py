"""Darkroom."""


import logging
import os
from typing import TYPE_CHECKING, Callable, List, Literal, Sequence, Tuple, Union

import yaml
from ops import CharmBase, EventBase
from ops.model import ModelError, SecretRotate, StatusBase, _ModelBackend
from ops.testing import _TestingModelBackend

from scenario import Container, Event, Model, Network, Port, Relation, Secret, State
from scenario.mocking import _MockModelBackend
from scenario.state import _CharmSpec

if TYPE_CHECKING:
    from ops import Framework

_Trace = Sequence[Tuple[Event, State]]
_SupportedBackends = Union[_TestingModelBackend, _ModelBackend, _MockModelBackend]

logger = logging.getLogger("darkroom")

# todo move those to Scenario.State and add an Event._is_framework_event() method.
FRAMEWORK_EVENT_NAMES = {"pre_commit", "commit"}


class _Unknown:
    def __repr__(self):
        return "<Unknown>"


UNKNOWN = _Unknown()
# Singleton representing missing information that cannot be retrieved,
# because of e.g. lack of leadership.
del _Unknown


class Darkroom:
    """Darkroom.

    Can be used to "capture" the current State of a charm, given its backend
    (testing, mocked, or live).

    Designed to work with multiple backends.
    - "Live model backend": live charm with real juju and pebble backends
    - "Harness testing backend": simulated backend provided by ops.testing.
    - "Scenario backend": simulated backend provided by ops.scenario

    Usage::
    >>> harness = Harness(MyCharm)
    >>> harness.begin_with_initial_hooks()
    >>> state: State = Darkroom().capture(harness.model._backend)


    Can be "attached" to a testing harness or scenario.Context to automatically capture
    state and triggering event whenever an event is emitted. Result is a "Trace", i.e. a sequence
    of events (and custom events), if the charm emits any.

    Can be "installed" in a testing suite or live charm. This will autoattach it to the
    current context.

    >>> l = []
    >>> def register_trace(t):  # this will be called with each generated trace
    >>>     l.append(t)
    >>> Darkroom.install(register_trace)
    >>> harness = Harness(MyCharm)
    >>> h.begin_with_initial_hooks()
    >>> assert l[0][0][0].name == "leader_settings_changed"
    >>> assert l[0][0][1].unit_status == ActiveStatus("foo")
    >>> # now that Darkroom is installed, regardless of the testing backend we use to emit
    >>> #  events, they will be captured
    >>> scenario.Context(MyCharm).run("start")
    >>> assert l[1][0][0].name == "start"
    >>> assert l[1][0][1].unit_status == WaitingStatus("bar")

    Usage in live charms:
    Edit charm.py to read:
    >>> if __name__ == '__main__':
    >>>     from darkroom import Darkroom
    >>>     Darkroom.install(print, live=True)
    >>>     ops.main(MyCharm)
    """

    def __init__(
        self,
        skip_framework_events: bool = True,
        skip_custom_events: bool = False,
    ):
        self._skip_framework_events = skip_framework_events
        self._skip_custom_events = skip_custom_events

    def _listen_to(self, event: Event, framework: "Framework") -> bool:
        """Whether this event should be captured or not.

        Depends on the init-provided skip config.
        """
        if self._skip_framework_events and event.name in FRAMEWORK_EVENT_NAMES:
            return False
        if not self._skip_custom_events:
            return True

        # derive the charmspec from the framework.
        # Framework contains pointers to all observers.
        # attempt to autoload:
        try:
            charm_type = next(
                filter(lambda o: isinstance(o, CharmBase), framework._objects.values()),
            )
        except StopIteration as e:
            raise RuntimeError("unable to find charm in framework objects") from e

        try:
            charm_root = framework.charm_dir
            meta = charm_root / "metadata.yaml"
            if not meta.exists():
                raise RuntimeError("metadata.yaml not found")
            actions = charm_root / "actions.yaml"
            config = charm_root / "config.yaml"
            charm_spec = _CharmSpec(
                charm_type,
                meta=yaml.safe_load(meta.read_text()),
                actions=yaml.safe_load(actions.read_text())
                if actions.exists()
                else None,
                config=yaml.safe_load(config.read_text()) if config.exists() else None,
            )
        except Exception as e:
            # todo: fall back to generating from framework._meta
            raise RuntimeError("cannot autoload charm spec") from e

        if not event._is_builtin_event(charm_spec):
            return False

        return True

    @staticmethod
    def _get_mode(
        backend: _SupportedBackends,
    ) -> Literal["harness", "scenario", "live"]:
        if isinstance(backend, _TestingModelBackend):
            return "harness"
        elif isinstance(backend, _MockModelBackend):
            return "scenario"
        elif isinstance(backend, _TestingModelBackend):
            return "live"
        else:
            raise TypeError(backend)

    def capture(self, backend: _SupportedBackends) -> State:
        mode = self._get_mode(backend)
        logger.info(f"capturing in mode = `{mode}`.")

        if isinstance(backend, _MockModelBackend):
            return backend._state

        state = State(
            config=dict(backend.config_get()),
            relations=self._get_relations(backend),
            containers=self._get_containers(backend),
            networks=self._get_networks(backend),
            secrets=self._get_secrets(backend),
            opened_ports=self._get_opened_ports(backend),
            leader=self._get_leader(backend),
            unit_id=self._get_unit_id(backend),
            app_status=self._get_app_status(backend),
            unit_status=self._get_unit_status(backend),
            workload_version=self._get_workload_version(backend),
            model=self._get_model(backend),
        )

        return state

    @staticmethod
    def _get_unit_id(backend: _SupportedBackends) -> int:
        return int(backend.unit_name.split("/")[1])

    @staticmethod
    def _get_workload_version(backend: _SupportedBackends) -> int:
        # only available in testing: a live charm can't get its own workload version.
        return getattr(backend, "_workload_version", UNKNOWN)

    @staticmethod
    def _get_unit_status(backend: _SupportedBackends) -> StatusBase:
        raw = backend.status_get()
        return StatusBase.from_name(message=raw["message"], name=raw["status"])

    @staticmethod
    def _get_app_status(backend: _SupportedBackends) -> StatusBase:
        try:
            raw = backend.status_get(is_app=True)
            return StatusBase.from_name(message=raw["message"], name=raw["status"])
        except ModelError:
            return UNKNOWN

    @staticmethod
    def _get_model(backend: _SupportedBackends) -> Model:
        if backend._meta.containers:
            # if we have containers we're definitely k8s.
            model_type = "kubernetes"
        else:
            # guess k8s|lxd from envvars
            model_type = "kubernetes" if "KUBERNETES" in os.environ else "lxd"
        return Model(name=backend.model_name, uuid=backend.model_uuid, type=model_type)

    @staticmethod
    def _get_leader(backend: _SupportedBackends):
        return backend.is_leader()

    @staticmethod
    def _get_opened_ports(backend: _SupportedBackends) -> List[Port]:
        return [Port(p.protocol, p.port) for p in backend.opened_ports()]

    def _get_relations(self, backend: _SupportedBackends) -> List[Relation]:
        relations = []

        local_unit_name = backend.unit_name
        local_app_name = backend.unit_name.split("/")[0]

        for endpoint, ids in backend._relation_ids_map.items():
            for r_id in ids:
                relations.append(
                    self._get_relation(
                        backend,
                        r_id,
                        endpoint,
                        local_app_name,
                        local_unit_name,
                    ),
                )

        return relations

    def _get_relation(
        self,
        backend: _SupportedBackends,
        r_id: int,
        endpoint: str,
        local_app_name: str,
        local_unit_name: str,
    ):
        def get_interface_name(endpoint: str):
            return backend._meta.relations[endpoint].interface_name

        def try_get(databag, owner):
            try:
                return databag[owner]
            except ModelError:
                return UNKNOWN

        # todo switch between peer and sub
        rel_data = backend._relation_data_raw[r_id]

        app_and_units = backend._relation_app_and_units[r_id]
        remote_app_name = app_and_units["app"]
        return Relation(
            endpoint=endpoint,
            interface=get_interface_name(endpoint),
            relation_id=r_id,
            local_app_data=try_get(rel_data, local_app_name),
            local_unit_data=try_get(rel_data, local_unit_name),
            remote_app_data=try_get(rel_data, remote_app_name),
            remote_units_data={
                int(remote_unit_id.split("/")[1]): try_get(rel_data, remote_unit_id)
                for remote_unit_id in app_and_units["units"]
            },
            remote_app_name=remote_app_name,
        )

    def _get_containers(self, backend: _SupportedBackends) -> List[Container]:
        containers = []
        mode = self._get_mode(backend)

        for name, c in backend._meta.containers.items():
            if mode == "live":
                # todo: real pebble socket address
                pebble = backend.get_pebble("<todo>")
            else:
                # testing backends get the 3rd elem:
                path = ["a", "b", "c", name, "bar.socket"]
                pebble = backend.get_pebble("/".join(path))
            assert pebble
            # todo: complete container snapshot
            containers.append(Container(name=name, mounts=c.mounts))
        return containers

    def _get_networks(self, backend: _SupportedBackends) -> List[Network]:
        networks = [
            Network(name=nw_name, **nw) for nw_name, nw in backend._networks.items()
        ]
        return networks

    def _get_secrets(self, backend: _SupportedBackends) -> List[Secret]:
        secrets = []
        for s in backend._secrets:
            owner_app = s.owner_name.split("/")[0]
            relation_id = backend._relation_id_to(owner_app)
            grants = s.grants.get(relation_id, set())

            remote_grants = set()
            granted = False
            for grant in grants:
                if grant in (backend.unit_name, backend.app_name):
                    granted = grant
                else:
                    remote_grants.add(grant)

            secrets.append(
                Secret(
                    id=s.id,
                    label=s.label,
                    contents=backend.secret_get(s.id),
                    granted=granted,
                    remote_grants={relation_id: remote_grants},
                    description=s.description,
                    owner=s.owner_name,
                    rotate=s.rotate_policy or SecretRotate.NEVER,
                    expire=s.expire_time,
                ),
            )
        return secrets

    def _get_event(self, event: EventBase) -> Event:
        return Event(event.handle.kind)

    def attach(self, listener: Callable[[Event, State], None]):
        """Every time an event is emitted, record the event and capture the state after execution."""
        from ops import Framework

        if not getattr(Framework, "__orig_emit__", None):
            Framework.__orig_emit__ = Framework._emit  # noqa
            # do not simply use Framework._emit because if we apply this patch multiple times
            # the previous listeners will keep being called.

        def _darkroom_emit(instance: Framework, ops_event):
            # proceed with framework._emit()
            Framework.__orig_emit__(instance, ops_event)
            event: Event = self._get_event(ops_event)

            if not self._listen_to(event, instance):
                logger.debug(f"skipping event {ops_event}")
                return

            backend = instance.model._backend  # noqa
            # todo should we automagically event.bind(state)?
            state = self.capture(backend)
            listener(event, state)

        Framework._emit = _darkroom_emit

    @staticmethod
    def install(listener: Callable[[_Trace], None], live: bool = False):
        """Patch Harness so that every time a new instance is created, a Darkroom is attached to it.

        Note that the trace will be initially empty and will be filled up as the harness emits events.
        So only access the traces when you're sure the harness is done emitting.
        """
        Darkroom._install_on_harness(listener)
        Darkroom._install_on_scenario(listener)

        if live:
            # if we are in a live event context, we attach and register a single trace
            trace = []
            listener(trace)

            # we don't do this automatically, but instead do it on an explicit live=True,
            # because otherwise listener will be called with an empty trace at the
            # beginning of every run.
            Darkroom().attach(lambda e, s: trace.append((e, s)))

    @staticmethod
    def _install_on_scenario(listener: Callable[[_Trace], None]):
        from scenario import Context

        if not getattr(Context, "__orig_init__", None):
            Context.__orig__init__ = Context.__init__
            # do not simply use Context.__init__ because
            # if we instantiate multiple Contexts we'll keep adding to the older harnesses' traces.

        def patch(context: Context, *args, **kwargs):
            trace = []
            listener(trace)
            Context.__orig__init__(context, *args, **kwargs)
            dr = Darkroom()
            dr.attach(listener=lambda event, state: trace.append((event, state)))

        Context.__init__ = patch

    @staticmethod
    def _install_on_harness(listener: Callable[[_Trace], None]):
        from ops.testing import Harness

        if not getattr(Harness, "__orig_init__", None):
            Harness.__orig_init__ = Harness.__init__
            # do not simply use Harness.__init__ because
            # if we instantiate multiple harnesses we'll keep adding to the older harnesses' traces.

        def patch(harness: Harness, *args, **kwargs):
            trace = []
            listener(trace)
            Harness.__orig_init__(harness, *args, **kwargs)
            dr = Darkroom()
            dr.attach(listener=lambda event, state: trace.append((event, state)))

        Harness.__init__ = patch
