#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import typing
from itertools import chain
from typing import Any, Callable, Dict, Iterable, Optional, TextIO, Type, Union

from scenario import Context
from scenario.logger import logger as scenario_logger
from scenario.state import (
    ATTACH_ALL_STORAGES,
    BREAK_ALL_RELATIONS,
    CREATE_ALL_RELATIONS,
    DETACH_ALL_STORAGES,
    META_EVENTS,
    Event,
    InjectRelation,
    State,
)

if typing.TYPE_CHECKING:
    from ops.testing import CharmType

CharmMeta = Optional[Union[str, TextIO, dict]]

logger = scenario_logger.getChild("scenario")


def decompose_meta_event(meta_event: Event, state: State):
    # decompose the meta event

    if meta_event.name in [ATTACH_ALL_STORAGES, DETACH_ALL_STORAGES]:
        logger.warning(f"meta-event {meta_event.name} not supported yet")
        return

    if meta_event.name in [CREATE_ALL_RELATIONS, BREAK_ALL_RELATIONS]:
        for relation in state.relations:
            event = Event(
                relation.endpoint + META_EVENTS[meta_event.name],
                args=(
                    # right now, the Relation object hasn't been created by ops yet, so we
                    # can't pass it down.
                    # this will be replaced by a Relation instance before the event is fired.
                    InjectRelation(relation.endpoint, relation.relation_id),
                ),
            )
            logger.debug(f"decomposed meta {meta_event.name}: {event}")
            yield event, state.copy()

    else:
        raise RuntimeError(f"unknown meta-event {meta_event.name}")


def generate_startup_sequence(state_template: State):
    yield from chain(
        decompose_meta_event(Event(ATTACH_ALL_STORAGES), state_template.copy()),
        ((Event("start"), state_template.copy()),),
        decompose_meta_event(Event(CREATE_ALL_RELATIONS), state_template.copy()),
        (
            (
                Event(
                    "leader_elected"
                    if state_template.leader
                    else "leader_settings_changed",
                ),
                state_template.copy(),
            ),
            (Event("config_changed"), state_template.copy()),
            (Event("install"), state_template.copy()),
        ),
    )


def generate_teardown_sequence(state_template: State):
    yield from chain(
        decompose_meta_event(Event(BREAK_ALL_RELATIONS), state_template.copy()),
        decompose_meta_event(Event(DETACH_ALL_STORAGES), state_template.copy()),
        (
            (Event("stop"), state_template.copy()),
            (Event("remove"), state_template.copy()),
        ),
    )


def generate_builtin_sequences(template_states: Iterable[State]):
    for template_state in template_states:
        yield from chain(
            generate_startup_sequence(template_state),
            generate_teardown_sequence(template_state),
        )


def check_builtin_sequences(
    charm_type: Type["CharmType"],
    meta: Optional[Dict[str, Any]] = None,
    actions: Optional[Dict[str, Any]] = None,
    config: Optional[Dict[str, Any]] = None,
    template_state: State = None,
    pre_event: Optional[Callable[["CharmType"], None]] = None,
    post_event: Optional[Callable[["CharmType"], None]] = None,
) -> object:
    """Test that all the builtin startup and teardown events can fire without errors.

    This will play both scenarios with and without leadership, and raise any exceptions.

    This is a baseline check that in principle all charms (except specific use-cases perhaps),
    should pass out of the box.

    If you want to, you can inject more stringent state checks using the
    pre_event and post_event hooks.
    """

    template = template_state if template_state else State()
    out = []

    for event, state in generate_builtin_sequences(
        (
            template.replace(leader=True),
            template.replace(leader=False),
        ),
    ):
        ctx = Context(charm_type=charm_type, meta=meta, actions=actions, config=config)
        out.append(
            ctx.run(
                event,
                state=state,
                pre_event=pre_event,
                post_event=post_event,
            ),
        )
    return out
