import json
from dataclasses import asdict
from typing import Callable, Iterable, TextIO, List, Optional, Union, Dict, Any

from ops.charm import CharmBase
from ops.framework import BoundEvent, EventBase

from logger import logger as pkg_logger
from scenario import Runtime
from scenario.consts import (ATTACH_ALL_STORAGES, BREAK_ALL_RELATIONS, DETACH_ALL_STORAGES, CREATE_ALL_RELATIONS,)
from scenario.structs import Event, Scene, Context, InjectRelation, CharmSpec

CharmMeta = Optional[Union[str, TextIO, dict]]
AssertionType = Callable[["BoundEvent", "Context", "Emitter"], Optional[bool]]

logger = pkg_logger.getChild("scenario")


class Emitter:
    """Event emitter."""

    def __init__(self, emit: Callable[[], BoundEvent]):
        self._emit = emit
        self.event = None
        self._emitted = False

    @property
    def emitted(self):
        """Has the event been emitted already?"""  # noqa
        return self._emitted

    def emit(self):
        """Emit the event.

        Will get called automatically when the context exits if you didn't call it already.
        """
        if self._emitted:
            raise RuntimeError("already emitted; should not emit twice")

        self._emitted = True
        self.event = self._emit()
        return self.event


class PlayResult:
    # TODO: expose the 'final context' or a Delta object from the PlayResult.
    def __init__(
        self,
        charm: CharmBase,
        scene_in: "Scene",
        event: EventBase,
        context_out: "Context",
    ):
        self.charm = charm
        self.scene_in = scene_in
        self.context_out = context_out
        self.event = event

    def delta(self):
        try:
            import jsonpatch
        except ModuleNotFoundError:
            raise ImportError(
                "cannot import jsonpatch: using the .delta() "
                "extension requires jsonpatch to be installed."
                "Fetch it with pip install jsonpatch."
            )
        if self.scene_in.context == self.context_out:
            return None

        return jsonpatch.make_patch(
            asdict(self.scene_in.context), asdict(self.context_out)
        )


class _Builtins:
    @staticmethod
    def startup(leader=True):
        return Scenario.from_events(
            (
                ATTACH_ALL_STORAGES,
                "start",
                CREATE_ALL_RELATIONS,
                "leader-elected" if leader else "leader-settings-changed",
                "config-changed",
                "install",
            )
        )

    @staticmethod
    def teardown():
        return Scenario.from_events(
            (BREAK_ALL_RELATIONS, DETACH_ALL_STORAGES, "stop", "remove")
        )


class Playbook:
    def __init__(self, scenes: Iterable[Scene]):
        self._scenes = list(scenes)
        self._cursor = 0

    def __bool__(self):
        return bool(self._scenes)

    @property
    def is_done(self):
        return self._cursor < (len(self._scenes) - 1)

    def add(self, scene: Scene):
        self._scenes.append(scene)

    def next(self):
        self.scroll(1)
        return self._scenes[self._cursor]

    def scroll(self, n):
        if not 0 <= self._cursor + n <= len(self._scenes):
            raise RuntimeError(f"Cursor out of bounds: can't scroll ({self}) by {n}.")
        self._cursor += n

    def restart(self):
        self._cursor = 0

    def __repr__(self):
        return f"<Playbook {self._cursor}/{len(self._scenes)}>"

    def __iter__(self):
        yield from self._scenes

    def __next__(self):
        return self.next()

    def to_dict(self) -> Dict[str, List[Any]]:
        """Serialize."""
        return {"scenes": [asdict(scene) for scene in self._scenes]}

    def to_json(self) -> str:
        """Dump as json dict."""
        return json.dumps(self.to_dict(), indent=2)

    @staticmethod
    def load(s: str) -> "Playbook":
        obj = json.loads(s)
        scenes = tuple(Scene.from_dict(raw_scene) for raw_scene in obj["scenes"])
        return Playbook(scenes=scenes)


class Scenario:
    builtins = _Builtins()

    def __init__(self, charm_spec: CharmSpec, playbook: Playbook = Playbook(())):
        self._playbook = playbook
        self._charm_spec = charm_spec
        self._charm_type = charm_spec.charm_type
        self._runtime = Runtime(charm_spec)

    @property
    def playbook(self) -> Playbook:
        return self._playbook

    def reset(self):
        self._playbook.restart()

    def _play_meta(
        self, event: Event, context: Context = None, add_to_playbook: bool = False
    ):
        # decompose the meta event
        events = []

        if event.name == ATTACH_ALL_STORAGES:
            logger.warning(f"meta-event {event.name} not supported yet")
            return

        elif event.name == DETACH_ALL_STORAGES:
            logger.warning(f"meta-event {event.name} not supported yet")
            return

        elif event.name == CREATE_ALL_RELATIONS:
            if context:
                for relation in context.relations:
                    # RELATION_OBJ is to indicate to the harness_ctx that
                    # it should retrieve the
                    evt = Event(
                        f"{relation.meta.endpoint}-relation-created",
                        args=(
                            InjectRelation(
                                relation.meta.endpoint, relation.meta.relation_id
                            ),
                        ),
                    )
                    events.append(evt)

        elif event.name == BREAK_ALL_RELATIONS:
            if context:
                for relation in context.relations:
                    evt = Event(
                        f"{relation.meta.endpoint}-relation-broken",
                        args=(
                            InjectRelation(
                                relation.meta.endpoint, relation.meta.relation_id
                            ),
                        ),
                    )
                    events.append(evt)
                    # todo should we ensure there's no relation data in this context?

        else:
            raise RuntimeError(f"unknown meta-event {event.name}")

        logger.debug(f"decomposed meta {event.name} into {events}")
        last = None
        for event in events:
            last = self.play(event, context, add_to_playbook=add_to_playbook)
        return last

    def run(self, scene: Scene, add_to_playbook: bool = False):
        return self.play(scene, add_to_playbook=add_to_playbook)

    def play(
        self,
        obj: Union[Scene, str],
        context: Context = None,
        add_to_playbook: bool = False,
    ) -> PlayResult:

        if isinstance(obj, str):
            _event = Event(obj)
            if _event.is_meta:
                return self._play_meta(_event, context, add_to_playbook=add_to_playbook)
            scene = Scene(_event, context)
        else:
            scene = obj

        runtime = self._runtime
        result = runtime.run(scene)
        # todo verify that if state was mutated, it was mutated
        #  in a way that makes sense:
        #  e.g. - charm cannot modify leadership status, etc...

        if add_to_playbook:
            # so we can later export it
            self._playbook.add(scene)

        return PlayResult(
            charm=result.charm,
            scene_in=scene,
            context_out=result.scene.context,
            event=result.event,
        )

    def play_until_complete(self):
        if not self._playbook:
            raise RuntimeError("playbook is empty")

        with self:
            for context, event in self._playbook:
                ctx = self.play(event=event, context=context)
        return ctx
