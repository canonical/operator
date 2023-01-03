import json
import typing
from dataclasses import asdict
from typing import Any, Callable, Dict, Iterable, List, Optional, TextIO, Union

from scenario import Runtime
from scenario.consts import (
    ATTACH_ALL_STORAGES,
    BREAK_ALL_RELATIONS,
    CREATE_ALL_RELATIONS,
    DETACH_ALL_STORAGES,
    META_EVENTS,
)
from scenario.logger import logger as pkg_logger
from scenario.structs import CharmSpec, Context, Event, InjectRelation, Scene

if typing.TYPE_CHECKING:
    from ops.charm import CharmBase
    from ops.framework import BoundEvent, EventBase


CharmMeta = Optional[Union[str, TextIO, dict]]
AssertionType = Callable[["BoundEvent", "Context", "Emitter"], Optional[bool]]

logger = pkg_logger.getChild("scenario")


class Emitter:
    """Event emitter."""

    def __init__(self, emit: Callable[[], "BoundEvent"]):
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


def sort_patch(patch: List[Dict], key=lambda obj: obj["path"] + obj["op"]):
    return sorted(patch, key=key)


class PlayResult:
    def __init__(
        self,
        charm: "CharmBase",
        scene_in: "Scene",
        event: "EventBase",
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

        patch = jsonpatch.make_patch(
            asdict(self.scene_in.context), asdict(self.context_out)
        ).patch
        return sort_patch(patch)


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
    def __init__(
        self,
        charm_spec: CharmSpec,
        playbook: Playbook = Playbook(()),
        juju_version: str = "3.0.0",
    ):
        self._playbook = playbook
        self._charm_spec = charm_spec
        self._charm_type = charm_spec.charm_type
        self._runtime = Runtime(charm_spec, juju_version=juju_version)

    @property
    def playbook(self) -> Playbook:
        return self._playbook

    def reset(self):
        self._playbook.restart()

    def _play_meta(self, event: Event, context: Context, add_to_playbook: bool = False):
        # decompose the meta event
        events = []

        if event.name in [ATTACH_ALL_STORAGES, DETACH_ALL_STORAGES]:
            logger.warning(f"meta-event {event.name} not supported yet")
            return

        if event.name in [CREATE_ALL_RELATIONS, BREAK_ALL_RELATIONS]:
            for relation in context.state.relations:
                evt = Event(
                    relation.meta.endpoint + META_EVENTS[event.name],
                    args=(
                        # right now, the Relation object hasn't been created by ops yet, so we can't pass it down.
                        # this will be replaced by a Relation instance before the event is fired.
                        InjectRelation(
                            relation.meta.endpoint, relation.meta.relation_id
                        ),
                    ),
                )
                events.append(evt)
        else:
            raise RuntimeError(f"unknown meta-event {event.name}")

        logger.debug(f"decomposed meta {event.name} into {events}")
        last = None

        for event in events:
            scene = Scene(event, context)
            last = self.play(scene, add_to_playbook=add_to_playbook)

        return last

    def play(
        self,
        scene: Scene,
        add_to_playbook: bool = False,
    ) -> PlayResult:
        result = self._runtime.play(scene)
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

    def play_until_complete(self) -> List[PlayResult]:
        """Plays every scene in the Playbook and returns a list of results."""
        if not self._playbook:
            raise RuntimeError("playbook is empty")

        results = []
        for scene in self._playbook:
            result = self.play(scene)
            results.append(result)

        return results


def events_to_scenes(events: typing.Sequence[Union[str, Event]]):
    def _to_event(obj):
        if isinstance(obj, str):
            return Event(obj)
        elif isinstance(obj, Event):
            return obj
        else:
            raise TypeError(obj)

    scenes = map(Scene, map(_to_event, events))
    for i, scene in enumerate(scenes):
        scene.name = f"<Scene {i}: {scene.event.name}>"
        yield scene


class StartupScenario(Scenario):
    def __init__(
        self, charm_spec: CharmSpec, leader: bool = True, juju_version: str = "3.0.0"
    ):
        playbook: Playbook = Playbook(
            events_to_scenes(
                (
                    ATTACH_ALL_STORAGES,
                    "start",
                    CREATE_ALL_RELATIONS,
                    "leader-elected" if leader else "leader-settings-changed",
                    "config-changed",
                    "install",
                )
            )
        )
        super().__init__(charm_spec, playbook, juju_version)


class TeardownScenario(Scenario):
    def __init__(self, charm_spec: CharmSpec, juju_version: str = "3.0.0"):
        playbook: Playbook = Playbook(
            events_to_scenes(
                (BREAK_ALL_RELATIONS, DETACH_ALL_STORAGES, "stop", "remove")
            )
        )
        super().__init__(charm_spec, playbook, juju_version)
