#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import os
from collections import Counter
from collections.abc import Sequence
from itertools import chain
from numbers import Number
from typing import TYPE_CHECKING, Iterable, List, NamedTuple, Tuple

from scenario.runtime import InconsistentScenarioError
from scenario.runtime import logger as scenario_logger
from scenario.state import (
    Action,
    PeerRelation,
    SubordinateRelation,
    _CharmSpec,
    normalize_name,
)

if TYPE_CHECKING:
    from scenario.state import Event, State

logger = scenario_logger.getChild("consistency_checker")


class Results(NamedTuple):
    """Consistency checkers return type."""

    errors: Iterable[str]
    warnings: Iterable[str]


def check_consistency(
    state: "State",
    event: "Event",
    charm_spec: "_CharmSpec",
    juju_version: str,
):
    """Validate the combination of a state, an event, a charm spec, and a juju version.

    When invoked, it performs a series of checks that validate that the state is consistent with
    itself, with the event being emitted, the charm metadata, etc...

    This function performs some basic validation of the combination of inputs that goes into a
    scenario test and determines if the scenario is a realistic/plausible/consistent one.

    A scenario is inconsistent if it can practically never occur because it contradicts
    the juju model.
    For example: juju guarantees that upon calling config-get, a charm will only ever get the keys
    it declared in its config.yaml.
    So a State declaring some config keys that are not in the charm's config.yaml is nonsense,
    and the combination of the two is inconsistent.
    """
    juju_version: Tuple[int, ...] = tuple(map(int, juju_version.split(".")))

    if os.getenv("SCENARIO_SKIP_CONSISTENCY_CHECKS"):
        logger.info("skipping consistency checks.")
        return

    errors = []
    warnings = []

    for check in (
        check_containers_consistency,
        check_config_consistency,
        check_event_consistency,
        check_secrets_consistency,
        check_relation_consistency,
    ):
        results = check(
            state=state,
            event=event,
            charm_spec=charm_spec,
            juju_version=juju_version,
        )
        errors.extend(results.errors)
        warnings.extend(results.warnings)

    if errors:
        err_fmt = "\n".join(errors)
        raise InconsistentScenarioError(
            f"Inconsistent scenario. The following errors were found: {err_fmt}",
        )
    if warnings:
        err_fmt = "\n".join(warnings)
        logger.warning(
            f"This scenario is probably inconsistent. Double check, and ignore this "
            f"warning if you're sure. "
            f"The following warnings were found: {err_fmt}",
        )


def check_event_consistency(
    *,
    event: "Event",
    charm_spec: "_CharmSpec",
    **_kwargs,  # noqa: U101
) -> Results:
    """Check the internal consistency of the Event data structure.

    For example, it checks that a relation event has a relation instance, and that
    the relation endpoint name matches the event prefix.
    """
    errors = []
    warnings = []

    # custom event: can't make assumptions about its name and its semantics
    # todo: should we then just skip the other checks?
    if not event._is_builtin_event(charm_spec):
        warnings.append(
            "this is a custom event; if its name makes it look like a builtin one "
            "(e.g. a relation event, or a workload event), you might get some false-negative "
            "consistency checks.",
        )

    if event._is_relation_event:
        _check_relation_event(charm_spec, event, errors, warnings)

    if event._is_workload_event:
        _check_workload_event(charm_spec, event, errors, warnings)

    if event._is_action_event:
        _check_action_event(charm_spec, event, errors, warnings)

    return Results(errors, warnings)


def _check_relation_event(
    charm_spec: _CharmSpec,  # noqa: U100
    event: "Event",
    errors: List[str],
    warnings: List[str],  # noqa: U100
):
    if not event.relation:
        errors.append(
            "cannot construct a relation event without the relation instance. "
            "Please pass one.",
        )
    else:
        if not event.name.startswith(normalize_name(event.relation.endpoint)):
            errors.append(
                f"relation event should start with relation endpoint name. {event.name} does "
                f"not start with {event.relation.endpoint}.",
            )


def _check_workload_event(
    charm_spec: _CharmSpec,  # noqa: U100
    event: "Event",
    errors: List[str],
    warnings: List[str],  # noqa: U100
):
    if not event.container:
        errors.append(
            "cannot construct a workload event without the container instance. "
            "Please pass one.",
        )
    elif not event.name.startswith(normalize_name(event.container.name)):
        errors.append(
            f"workload event should start with container name. {event.name} does "
            f"not start with {event.container.name}.",
        )


def _check_action_event(
    charm_spec: _CharmSpec,
    event: "Event",
    errors: List[str],
    warnings: List[str],
):
    action = event.action
    if not action:
        errors.append(
            "cannot construct a workload event without the container instance. "
            "Please pass one.",
        )
    elif not event.name.startswith(normalize_name(action.name)):
        errors.append(
            f"action event should start with action name. {event.name} does "
            f"not start with {action.name}.",
        )
    if action.name not in charm_spec.actions:
        errors.append(
            f"action event {event.name} refers to action {action.name} "
            f"which is not declared in the charm metadata (actions.yaml).",
        )

    _check_action_param_types(charm_spec, action, errors, warnings)


def _check_action_param_types(
    charm_spec: _CharmSpec,
    action: Action,
    errors: List[str],
    warnings: List[str],
):
    to_python_type = {
        "string": str,
        "boolean": bool,
        "number": Number,
        "array": Sequence,
        "object": dict,
    }
    expected_param_type = {}
    for par_name, par_spec in charm_spec.actions[action.name].get("params", {}).items():
        value = par_spec.get("type")
        if not value:
            errors.append(
                f"action parameter {par_name} has no type. "
                f"Charmcraft will be unhappy about this. ",
            )
            continue

        try:
            expected_param_type[par_name] = to_python_type[value]
        except KeyError:
            warnings.append(
                f"unknown data type declared for parameter {par_name}: type={value}. "
                f"Cannot consistency-check.",
            )

    for provided_param_name, provided_param_value in action.params.items():
        expected_type = expected_param_type.get(provided_param_name)
        if not expected_type:
            errors.append(
                f"param {provided_param_name} is not a valid parameter for {action.name}: "
                "missing from action specification",
            )
            continue
        if not isinstance(provided_param_value, expected_type):
            errors.append(
                f"param {provided_param_name} is of type {type(provided_param_value)}: "
                f"expecting {expected_type}",
            )


def check_config_consistency(
    *,
    state: "State",
    charm_spec: "_CharmSpec",
    **_kwargs,  # noqa: U101
) -> Results:
    """Check the consistency of the state.config with the charm_spec.config (config.yaml)."""
    state_config = state.config
    meta_config = (charm_spec.config or {}).get("options", {})
    errors = []

    for key, value in state_config.items():
        if key not in meta_config:
            errors.append(
                f"config option {key!r} in state.config but not specified in config.yaml.",
            )
            continue

        # todo unify with snapshot's when merged.
        converters = {
            "string": str,
            "int": int,
            "integer": int,  # fixme: which one is it?
            "number": float,
            "boolean": bool,
            "attrs": NotImplemented,  # fixme: wot?
        }

        expected_type_name = meta_config[key].get("type", None)
        if not expected_type_name:
            errors.append(f"config.yaml invalid; option {key!r} has no 'type'.")
            continue

        expected_type = converters.get(expected_type_name)
        if not isinstance(value, expected_type):
            errors.append(
                f"config invalid; option {key!r} should be of type {expected_type} "
                f"but is of type {type(value)}.",
            )

    return Results(errors, [])


def check_secrets_consistency(
    *,
    event: "Event",
    state: "State",
    juju_version: Tuple[int, ...],
    **_kwargs,  # noqa: U101
) -> Results:
    """Check the consistency of Secret-related stuff."""
    errors = []
    if not event._is_secret_event:
        return Results(errors, [])

    if not state.secrets:
        errors.append(
            "the event being processed is a secret event; but the state has no secrets.",
        )
    elif juju_version < (3,):
        errors.append(
            f"secrets are not supported in the specified juju version {juju_version}. "
            f"Should be at least 3.0.",
        )

    return Results(errors, [])


def check_relation_consistency(
    *,
    state: "State",
    event: "Event",  # noqa: U100
    charm_spec: "_CharmSpec",
    **_kwargs,  # noqa: U101
) -> Results:
    errors = []
    nonpeer_relations_meta = chain(
        charm_spec.meta.get("requires", {}).items(),
        charm_spec.meta.get("provides", {}).items(),
    )
    peer_relations_meta = charm_spec.meta.get("peers", {}).items()
    all_relations_meta = list(chain(nonpeer_relations_meta, peer_relations_meta))

    def _get_relations(r):
        try:
            return state.get_relations(r)
        except ValueError:
            return ()

    # check relation types
    for endpoint, _ in peer_relations_meta:
        for relation in _get_relations(endpoint):
            if not isinstance(relation, PeerRelation):
                errors.append(
                    f"endpoint {endpoint} is a peer relation; "
                    f"expecting relation to be of type PeerRelation, got {type(relation)}",
                )

    known_endpoints = [a[0] for a in all_relations_meta]
    for relation in state.relations:
        if not (ep := relation.endpoint) in known_endpoints:
            errors.append(f"relation endpoint {ep} is not declared in metadata.")

    seen_ids = set()
    for endpoint, relation_meta in all_relations_meta:
        expected_sub = relation_meta.get("scope", "") == "container"
        relations = _get_relations(endpoint)
        for relation in relations:
            if relation.relation_id in seen_ids:
                errors.append(
                    f"duplicate relation ID: {relation.relation_id} is claimed "
                    f"by multiple Relation instances",
                )

            seen_ids.add(relation.relation_id)
            is_sub = isinstance(relation, SubordinateRelation)
            if is_sub and not expected_sub:
                errors.append(
                    f"endpoint {endpoint} is not a subordinate relation; "
                    f"expecting relation to be of type Relation, "
                    f"got {type(relation)}",
                )
            if expected_sub and not is_sub:
                errors.append(
                    f"endpoint {endpoint} is not a subordinate relation; "
                    f"expecting relation to be of type SubordinateRelation, "
                    f"got {type(relation)}",
                )

    # check for duplicate endpoint names
    seen_endpoints = set()
    for endpoint, _ in all_relations_meta:
        if endpoint in seen_endpoints:
            errors.append("duplicate endpoint name in metadata.")
            break
        seen_endpoints.add(endpoint)

    return Results(errors, [])


def check_containers_consistency(
    *,
    state: "State",
    event: "Event",
    charm_spec: "_CharmSpec",
    **_kwargs,  # noqa: U101
) -> Results:
    """Check the consistency of `state.containers` vs. `charm_spec.meta`."""

    # event names will be normalized; need to compare against normalized container names.
    meta_containers = list(map(normalize_name, charm_spec.meta.get("containers", {})))
    state_containers = [normalize_name(c.name) for c in state.containers]
    errors = []

    # it's fine if you have containers in meta that are not in state.containers (yet), but it's
    # not fine if:
    # - you're processing a pebble-ready event and that container is not in state.containers or
    #   meta.containers
    if event._is_workload_event:
        evt_container_name = event.name[: -len("-pebble-ready")]
        if evt_container_name not in meta_containers:
            errors.append(
                f"the event being processed concerns container {evt_container_name!r}, but a "
                f"container with that name is not declared in the charm metadata",
            )
        if evt_container_name not in state_containers:
            errors.append(
                f"the event being processed concerns container {evt_container_name!r}, but a "
                f"container with that name is not present in the state. It's odd, but consistent, "
                f"if it cannot connect; but it should at least be there.",
            )

    # - a container in state.containers is not in meta.containers
    if diff := (set(state_containers).difference(set(meta_containers))):
        errors.append(
            f"some containers declared in the state are not specified in metadata. "
            f"That's not possible. "
            f"Missing from metadata: {diff}.",
        )

    # guard against duplicate container names
    names = Counter(state_containers)
    if dupes := [n for n in names if names[n] > 1]:
        errors.append(f"Duplicate container name(s): {dupes}.")

    return Results(errors, [])
