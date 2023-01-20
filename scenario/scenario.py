import typing
from itertools import chain
from typing import Callable, Iterable, Optional, TextIO, Type, Union

from scenario.logger import logger as scenario_logger
from scenario.runtime import Runtime
from scenario.structs import (
    ATTACH_ALL_STORAGES,
    BREAK_ALL_RELATIONS,
    CREATE_ALL_RELATIONS,
    DETACH_ALL_STORAGES,
    META_EVENTS,
    CharmSpec,
    Event,
    InjectRelation,
    Scene,
    State,
)

if typing.TYPE_CHECKING:
    from ops.testing import CharmType

CharmMeta = Optional[Union[str, TextIO, dict]]

logger = scenario_logger.getChild("scenario")


class Scenario:
    def __init__(
        self,
        charm_spec: CharmSpec,
        juju_version: str = "3.0.0",
    ):
        self._runtime = Runtime(charm_spec, juju_version=juju_version)

    @staticmethod
    def decompose_meta_event(meta_event: Event, state: State):
        # decompose the meta event

        if meta_event.name in [ATTACH_ALL_STORAGES, DETACH_ALL_STORAGES]:
            logger.warning(f"meta-event {meta_event.name} not supported yet")
            return

        if meta_event.name in [CREATE_ALL_RELATIONS, BREAK_ALL_RELATIONS]:
            for relation in state.relations:
                event = Event(
                    relation.meta.endpoint + META_EVENTS[meta_event.name],
                    args=(
                        # right now, the Relation object hasn't been created by ops yet, so we can't pass it down.
                        # this will be replaced by a Relation instance before the event is fired.
                        InjectRelation(
                            relation.meta.endpoint, relation.meta.relation_id
                        ),
                    ),
                )
                logger.debug(f"decomposed meta {meta_event.name}: {event}")
                yield event

        else:
            raise RuntimeError(f"unknown meta-event {meta_event.name}")

    def play(
        self,
        scene: Scene,
        pre_event: Optional[Callable[["CharmType"], None]] = None,
        post_event: Optional[Callable[["CharmType"], None]] = None,
    ) -> "State":
        # TODO check state transition consistency: verify that if state was mutated, it was
        #  in a way that makes sense:
        #  e.g. - charm cannot modify leadership status, etc...

        return self._runtime.play(
            scene,
            pre_event=pre_event,
            post_event=post_event,
        )


def generate_startup_scenes(state_template: State):
    yield from (
        Scene(event=Event(ATTACH_ALL_STORAGES), state=state_template.copy()),
        Scene(event=Event("start"), state=state_template.copy()),
        Scene(event=Event(CREATE_ALL_RELATIONS), state=state_template.copy()),
        Scene(
            event=Event(
                "leader-elected" if state_template.leader else "leader-settings-changed"
            ),
            state=state_template.copy(),
        ),
        Scene(event=Event("config-changed"), state=state_template.copy()),
        Scene(event=Event("install"), state=state_template.copy()),
    )


def generate_teardown_scenes(state_template: State):
    yield from (
        Scene(event=Event(BREAK_ALL_RELATIONS), state=state_template.copy()),
        Scene(event=Event(DETACH_ALL_STORAGES), state=state_template.copy()),
        Scene(event=Event("stop"), state=state_template.copy()),
        Scene(event=Event("remove"), state=state_template.copy()),
    )


def generate_builtin_scenes(template_states: Iterable[State]):
    for template_state in template_states:
        yield from chain(
            generate_startup_scenes(template_state),
            generate_teardown_scenes(template_state),
        )


def check_builtin_sequences(
    charm_spec: CharmSpec,
    pre_event: Optional[Callable[["CharmType"], None]] = None,
    post_event: Optional[Callable[["CharmType"], None]] = None,
):
    """Test that all the builtin startup and teardown events can fire without errors.

    This will play both scenarios with and without leadership, and raise any exceptions.
    If leader is True, it will exclude the non-leader cases, and vice-versa.

    This is a baseline check that in principle all charms (except specific use-cases perhaps),
    should pass out of the box.

    If you want to, you can inject more stringent state checks using the
    pre_event and post_event hooks.
    """
    scenario = Scenario(charm_spec)

    for scene in generate_builtin_scenes(
        (
            State(leader=True),
            State(leader=False),
        )
    ):
        scenario.play(scene, pre_event=pre_event, post_event=post_event)
