import os
from collections import Counter
from itertools import chain
from typing import TYPE_CHECKING, Iterable, NamedTuple, Tuple

from scenario.runtime import InconsistentScenarioError
from scenario.runtime import logger as scenario_logger
from scenario.state import PeerRelation, SubordinateRelation, _CharmSpec, normalize_name

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
    if not event._is_builtin_event(charm_spec):
        warnings.append(
            "this is a custom event; if its name makes it look like a builtin one "
            "(e.g. a relation event, or a workload event), you might get some false-negative "
            "consistency checks.",
        )

    if event._is_relation_event:
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

    if event._is_workload_event:
        if not event.container:
            errors.append(
                "cannot construct a workload event without the container instance. "
                "Please pass one.",
            )
        else:
            if not event.name.startswith(normalize_name(event.container.name)):
                errors.append(
                    f"workload event should start with container name. {event.name} does "
                    f"not start with {event.container.name}.",
                )
    return Results(errors, warnings)


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

    for endpoint, relation_meta in all_relations_meta:
        expected_sub = relation_meta.get("scope", "") == "container"
        relations = _get_relations(endpoint)
        for relation in relations:
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
