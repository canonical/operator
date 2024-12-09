#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""
The :meth:`check_consistency` function is the primary entry point for the
consistency checks. Calling it ensures that the :class:`State` and the event,
in combination with the ``Context``, is viable in Juju. For example, Juju can't
emit a ``foo-relation-changed`` event on your charm unless your charm has
declared a ``foo`` relation endpoint in its metadata.

Normally, there is no need to explicitly call this function; that happens
automatically behind the scenes whenever you trigger an event.

If you have a clear false negative, are explicitly testing 'edge',
inconsistent situations, or for whatever reason the checker is in your way, you
can set the ``SCENARIO_SKIP_CONSISTENCY_CHECKS`` environment variable and skip
it altogether.
"""

import marshal
import os
import re
from collections import Counter, defaultdict
from collections.abc import Sequence
from numbers import Number
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    Iterable,
    List,
    NamedTuple,
    Optional,
    Set,
    Tuple,
    Union,
)

from .errors import InconsistentScenarioError
from ._runtime import logger as scenario_logger
from .state import (
    CharmType,
    PeerRelation,
    SubordinateRelation,
    _Action,
    _CharmSpec,
    _normalise_name,
)

if TYPE_CHECKING:  # pragma: no cover
    from .state import State, _Event

logger = scenario_logger.getChild("consistency_checker")


class Results(NamedTuple):
    """Consistency checker return type.

    Each consistency check function returns a ``Results`` instance with the
    warnings and errors found during the check.
    """

    errors: Iterable[str]
    warnings: Iterable[str]


def check_consistency(
    state: "State",
    event: "_Event",
    charm_spec: "_CharmSpec[Any]",
    juju_version: str,
):
    """Validate the combination of a state, an event, a charm spec, and a Juju version.

    When invoked, it performs a series of checks that validate that the state is
    consistent with itself, with the event being emitted, the charm metadata,
    and so on.

    This function performs some basic validation of the combination of inputs
    that goes into a test and determines if the scenario is a
    realistic/plausible/consistent one.

    A scenario is inconsistent if it can practically never occur because it
    contradicts the Juju model. For example: Juju guarantees that upon calling
    ``config-get``, a charm will only ever get the keys it declared in its
    config metadata, so a :class:`scenario.State` declaring some config keys
    that are not in the charm's ``charmcraft.yaml`` is nonsense, and the
    combination of the two is inconsistent.
    """
    juju_version_: Tuple[int, ...] = tuple(map(int, juju_version.split(".")))

    if os.getenv("SCENARIO_SKIP_CONSISTENCY_CHECKS"):
        logger.info("skipping consistency checks.")
        return

    errors: List[str] = []
    warnings: List[str] = []

    checks: Tuple[Callable[..., Results]] = (
        check_containers_consistency,
        check_config_consistency,
        check_resource_consistency,
        check_event_consistency,
        check_secrets_consistency,
        check_storages_consistency,
        check_relation_consistency,
        check_network_consistency,
        check_cloudspec_consistency,
        check_storedstate_consistency,
    )  # type: ignore
    for check in checks:
        results = check(
            state=state,
            event=event,
            charm_spec=charm_spec,
            juju_version=juju_version_,
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


def check_resource_consistency(
    *,
    state: "State",
    charm_spec: "_CharmSpec[CharmType]",
    **_kwargs: Any,  # noqa: U101
) -> Results:
    """Check the internal consistency of the resources from metadata and in :class:`scenario.State`."""
    errors: List[str] = []
    warnings: List[str] = []

    resources_from_meta = set(charm_spec.meta.get("resources", {}))
    resources_from_state = {resource.name for resource in state.resources}
    if not resources_from_meta.issuperset(resources_from_state):
        errors.append(
            f"any and all resources passed to State.resources need to have been defined in "
            f"metadata.yaml. Metadata resources: {resources_from_meta}; "
            f"State.resources: {resources_from_state}.",
        )
    return Results(errors, warnings)


def check_event_consistency(
    *,
    event: "_Event",
    charm_spec: "_CharmSpec[CharmType]",
    state: "State",
    **_kwargs: Any,  # noqa: U101
) -> Results:
    """Check the internal consistency of the ``_Event`` data structure.

    For example, it checks that a relation event has a relation instance, and that
    the relation endpoint name matches the event prefix.
    """
    errors: List[str] = []
    warnings: List[str] = []

    if not event._is_builtin_event(charm_spec):
        # This is a custom event - we can't make assumptions about its name and
        # semantics. It doesn't really make sense to do checks that are designed
        # for relations, workloads, and so on - most likely those will end up
        # with false positives. Realistically, we can't know about what the
        # requirements for the custom event are (in terms of the state), so we
        # skip everything here. Perhaps in the future, custom events could
        # optionally include some sort of state metadata that made testing
        # consistency possible?
        warnings.append(
            "this is a custom event; if its name makes it look like a builtin one "
            "(for example, a relation event, or a workload event), you might get some false-negative "
            "consistency checks.",
        )
        return Results(errors, warnings)

    if event._is_relation_event:
        _check_relation_event(charm_spec, event, state, errors, warnings)

    if event._is_workload_event:
        _check_workload_event(charm_spec, event, state, errors, warnings)

    if event._is_action_event:
        _check_action_event(charm_spec, event, state, errors, warnings)

    if event._is_storage_event:
        _check_storage_event(charm_spec, event, state, errors, warnings)

    return Results(errors, warnings)


def _check_relation_event(
    charm_spec: _CharmSpec[CharmType],  # noqa: U100
    event: "_Event",
    state: "State",
    errors: List[str],
    warnings: List[str],  # noqa: U100
):
    if not event.relation:
        errors.append(
            "cannot construct a relation event without the relation instance. "
            "Please pass one.",
        )
    else:
        if not event.name.startswith(_normalise_name(event.relation.endpoint)):
            errors.append(
                f"relation event should start with relation endpoint name. {event.name} does "
                f"not start with {event.relation.endpoint}.",
            )
        if event.relation not in state.relations:
            errors.append(
                f"cannot emit {event.name} because relation {event.relation.id} is not in the "
                f"state (a relation with the same ID is not sufficient - you must "
                f"pass the object in the state to the event).",
            )


def _check_workload_event(
    charm_spec: _CharmSpec[CharmType],  # noqa: U100
    event: "_Event",
    state: "State",
    errors: List[str],
    warnings: List[str],
):
    if not event.container:
        errors.append(
            "cannot construct a workload event without the container instance. "
            "Please pass one.",
        )
    else:
        if not event.name.startswith(_normalise_name(event.container.name)):
            errors.append(
                f"workload event should start with container name. {event.name} does "
                f"not start with {event.container.name}.",
            )
            if event.container not in state.containers:
                errors.append(
                    f"cannot emit {event.name} because container {event.container.name} "
                    f"is not in the state (a container with the same name is not "
                    f"sufficient - you must pass the object in the state to the event).",
                )
            if not event.container.can_connect:
                warnings.append(
                    "you **can** fire fire pebble-ready while the container cannot connect, "
                    "but that's most likely not what you want.",
                )
        names = Counter(exec.command_prefix for exec in event.container.execs)
        if dupes := [n for n in names if names[n] > 1]:
            errors.append(
                f"container {event.container.name} has duplicate command prefixes: {dupes}",
            )


def _check_action_event(
    charm_spec: _CharmSpec[CharmType],
    event: "_Event",
    state: "State",  # noqa: U100
    errors: List[str],
    warnings: List[str],
):
    action = event.action
    if not action:
        errors.append(
            "cannot construct a workload event without the container instance. "
            "Please pass one.",
        )
        return

    elif not event.name.startswith(_normalise_name(action.name)):
        errors.append(
            f"action event should start with action name. {event.name} does "
            f"not start with {action.name}.",
        )
    if action.name not in (charm_spec.actions or ()):
        errors.append(
            f"action event {event.name} refers to action {action.name} "
            f"which is not declared in the charm metadata (actions.yaml).",
        )
        return

    _check_action_param_types(charm_spec, action, errors, warnings)


def _check_storage_event(
    charm_spec: _CharmSpec[CharmType],
    event: "_Event",
    state: "State",
    errors: List[str],
    warnings: List[str],  # noqa: U100
):
    storage = event.storage
    meta = charm_spec.meta

    if not storage:
        errors.append(
            "cannot construct a storage event without the Storage instance. "
            "Please pass one.",
        )
    elif not event.name.startswith(_normalise_name(storage.name)):
        errors.append(
            f"storage event should start with storage name. {event.name} does "
            f"not start with {storage.name}.",
        )
    elif storage.name not in meta["storage"]:
        errors.append(
            f"storage event {event.name} refers to storage {storage.name} "
            f"which is not declared in the charm metadata (metadata.yaml) under 'storage'.",
        )
    elif storage not in state.storages:
        errors.append(
            f"cannot emit {event.name} because storage {storage.name} "
            f"is not in the state (an object with the same name and index is not "
            f"sufficient - you must pass the object in the state to the event).",
        )


def _check_action_param_types(
    charm_spec: _CharmSpec[CharmType],
    action: _Action,
    errors: List[str],
    warnings: List[str],
):
    actions = charm_spec.actions
    if not actions:
        return

    to_python_type = {
        "string": str,
        "boolean": bool,
        "integer": int,
        "number": Number,
        "array": Sequence,
        "object": dict,
    }
    expected_param_type: Dict[str, Any] = {}
    for par_name, par_spec in actions[action.name].get("params", {}).items():
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


def check_storages_consistency(
    *,
    state: "State",
    charm_spec: "_CharmSpec[CharmType]",
    **_kwargs: Any,  # noqa: U101
) -> Results:
    """Check the consistency of the :class:`scenario.State` storages with the charm_spec metadata."""
    state_storage = state.storages
    meta_storage = (charm_spec.meta or {}).get("storage", {})
    errors: List[str] = []

    if missing := {s.name for s in state_storage}.difference(
        set(meta_storage.keys()),
    ):
        errors.append(
            f"some storages passed to State were not defined in metadata.yaml: {missing}",
        )

    seen: List[Tuple[str, int]] = []
    for s in state_storage:
        tag = (s.name, s.index)
        if tag in seen:
            errors.append(
                f"duplicate storage in State: storage {s.name} with index {s.index} "
                f"occurs multiple times in State.storages.",
            )
        seen.append(tag)

    return Results(errors, [])


def _is_secret_identifier(value: Union[str, int, float, bool]) -> bool:
    """Return true iff the value is in the form `secret:{secret id}`."""
    # cf. https://github.com/juju/juju/blob/13eb9df3df16a84fd471af8a3c95ddbd04389b71/core/secrets/secret.go#L48
    return bool(re.match(r"secret:[0-9a-z]{20}$", str(value)))


def check_config_consistency(
    *,
    state: "State",
    charm_spec: "_CharmSpec[CharmType]",
    juju_version: Tuple[int, ...],
    **_kwargs: Any,  # noqa: U101
) -> Results:
    """Check the consistency of the :class:`scenario.State` config with the charm_spec config."""
    state_config = state.config
    meta_config = (charm_spec.config or {}).get("options", {})
    errors: List[str] = []

    for key, value in state_config.items():
        if key not in meta_config:
            errors.append(
                f"config option {key!r} in state.config but not specified in config.yaml or "
                f"charmcraft.yaml.",
            )
            continue

        converters = {
            "string": str,
            "int": int,
            "float": float,
            "boolean": bool,
        }
        if juju_version >= (3, 4):
            converters["secret"] = str

        validators = {
            "secret": _is_secret_identifier,
        }

        expected_type_name = meta_config[key].get("type", None)
        if not expected_type_name:
            errors.append(f"config.yaml invalid; option {key!r} has no 'type'.")
            continue
        validator = validators.get(expected_type_name)

        expected_type = converters.get(expected_type_name)
        if not expected_type:
            errors.append(
                f"config invalid for option {key!r}: 'type' {expected_type_name} unknown",
            )

        elif not isinstance(value, expected_type):
            errors.append(
                f"config invalid; option {key!r} should be of type {expected_type} "
                f"but is of type {type(value)}.",
            )

        elif validator and not validator(value):
            errors.append(
                f"config invalid: option {key!r} value {value!r} is not valid.",
            )

    return Results(errors, [])


def check_secrets_consistency(
    *,
    event: "_Event",
    state: "State",
    juju_version: Tuple[int, ...],
    **_kwargs: Any,  # noqa: U101
) -> Results:
    """Check the consistency of any :class:`scenario.Secret` in the :class:`scenario.State`."""
    errors: List[str] = []
    if not event._is_secret_event:
        return Results(errors, [])

    assert event.secret is not None
    if event.secret not in state.secrets:
        secret_key = event.secret.id if event.secret.id else event.secret.label
        errors.append(
            f"cannot emit {event.name} because secret {secret_key} is not in the state "
            f"(a secret with the same ID is not sufficient - you must pass the object "
            f"in the state to the event).",
        )
    elif juju_version < (3,):
        errors.append(
            f"secrets are not supported in the specified juju version {juju_version}. "
            f"Should be at least 3.0.",
        )

    return Results(errors, [])


def check_network_consistency(
    *,
    state: "State",
    event: "_Event",  # noqa: U100
    charm_spec: "_CharmSpec[CharmType]",
    **_kwargs: Any,  # noqa: U101
) -> Results:
    """Check the consistency of any :class:`scenario.Network` in the :class:`scenario.State`."""
    errors: List[str] = []

    meta_bindings = set(charm_spec.meta.get("extra-bindings", ()))
    # add the implicit juju-info binding so we can override its network without
    # having to declare a relation for it in metadata
    implicit_bindings = {"juju-info"}
    all_relations = charm_spec.get_all_relations()
    non_sub_relations = {
        endpoint
        for endpoint, metadata in all_relations
        if metadata.get("scope") != "container"  # mark of a sub
    }

    state_bindings = {network.binding_name for network in state.networks}
    if diff := state_bindings.difference(
        meta_bindings.union(non_sub_relations).union(implicit_bindings),
    ):
        errors.append(
            f"Some network bindings defined in State are not in the metadata: {diff}.",
        )

    endpoints = {endpoint for endpoint, _ in all_relations}
    if collisions := endpoints.intersection(meta_bindings):
        errors.append(
            f"Extra bindings and integration endpoints cannot share the same name: {collisions}.",
        )

    return Results(errors, [])


def check_relation_consistency(
    *,
    state: "State",
    event: "_Event",  # noqa: U100
    charm_spec: "_CharmSpec[CharmType]",
    **_kwargs: Any,  # noqa: U101
) -> Results:
    """Check the consistency of any relations in the :class:`scenario.State`."""
    errors: List[str] = []

    peer_relations_meta = charm_spec.meta.get("peers", {}).items()
    all_relations_meta = charm_spec.get_all_relations()

    def _get_relations(r: str):
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
        if (ep := relation.endpoint) not in known_endpoints:
            errors.append(f"relation endpoint {ep} is not declared in metadata.")

    seen_ids: Set[int] = set()
    for endpoint, relation_meta in all_relations_meta:
        expected_sub = relation_meta.get("scope", "") == "container"
        relations = _get_relations(endpoint)
        for relation in relations:
            if relation.id in seen_ids:
                errors.append(
                    f"duplicate relation ID: {relation.id} is claimed "
                    f"by multiple Relation instances",
                )

            seen_ids.add(relation.id)
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
    seen_endpoints: Set[str] = set()
    for endpoint, _ in all_relations_meta:
        if endpoint in seen_endpoints:
            errors.append("duplicate endpoint name in metadata.")
            break
        seen_endpoints.add(endpoint)

    return Results(errors, [])


def check_containers_consistency(
    *,
    state: "State",
    event: "_Event",
    charm_spec: "_CharmSpec[CharmType]",
    **_kwargs: Any,  # noqa: U101
) -> Results:
    """Check the consistency of :class:`scenario.State` containers with the charm_spec metadata."""

    # event names will be normalized; need to compare against normalized container names.
    meta = charm_spec.meta
    meta_containers = list(map(_normalise_name, meta.get("containers", {})))
    state_containers = [_normalise_name(c.name) for c in state.containers]
    all_notices = {notice.id for c in state.containers for notice in c.notices}
    all_checks = {
        (c.name, check.name) for c in state.containers for check in c.check_infos
    }
    errors: List[str] = []

    # it's fine if you have containers in meta that are not in state.containers (yet), but it's
    # not fine if:
    # - you're processing a Pebble event and that container is not in state.containers or
    #   meta.containers
    if event._is_workload_event:
        evt_container_name = event.name.split("_pebble_")[0]
        if evt_container_name not in meta_containers:
            errors.append(
                f"the event being processed concerns container {evt_container_name!r}, but a "
                f"container with that name is not declared in the charm metadata",
            )
        if evt_container_name not in state_containers:
            errors.append(
                f"the event being processed concerns container {evt_container_name!r}, but a "
                f"container with that name is not present in the state. It's odd, but "
                f"consistent, if it cannot connect; but it should at least be there.",
            )
        # - you're processing a Notice event and that notice is not in any of the containers
        if event.notice and event.notice.id not in all_notices:
            errors.append(
                f"the event being processed concerns notice {event.notice!r}, but that "
                "notice is not in any of the containers present in the state.",
            )
        # - you're processing a Check event and that check is not in the check's container
        if (
            event.check_info
            and (evt_container_name, event.check_info.name) not in all_checks
        ):
            errors.append(
                f"the event being processed concerns check {event.check_info.name}, but that "
                f"check is not in the {evt_container_name} container.",
            )

    # - a container in state.containers is not in meta.containers
    if diff := (set(state_containers).difference(set(meta_containers))):
        errors.append(
            f"some containers declared in the state are not specified in metadata. "
            f"That's not possible. "
            f"Missing from metadata: {diff}.",
        )

    return Results(errors, [])


def check_cloudspec_consistency(
    *,
    state: "State",
    event: "_Event",
    charm_spec: "_CharmSpec[CharmType]",
    **_kwargs: Any,  # noqa: U101
) -> Results:
    """Check that Kubernetes models don't have :attr:`scenario.State.cloud_spec` set."""

    errors: List[str] = []
    warnings: List[str] = []

    if state.model.type == "kubernetes" and state.model.cloud_spec:
        errors.append(
            "CloudSpec is only available for machine charms, not Kubernetes charms. "
            "Simulate a machine substrate with: `State(..., model=Model(type='lxd'))`.",
        )

    return Results(errors, warnings)


def check_storedstate_consistency(
    *,
    state: "State",
    **_kwargs: Any,  # noqa: U101
) -> Results:
    """Check the internal consistency of any :class:`scenario.StoredState` in the :class:`scenario.State`."""
    errors: List[str] = []

    # Attribute names must be unique on each object.
    names: defaultdict[Optional[str], List[str]] = defaultdict(list)
    for ss in state.stored_states:
        names[ss.owner_path].append(ss.name)
    for owner, owner_names in names.items():
        if len(owner_names) != len(set(owner_names)):
            errors.append(
                f"{owner} has multiple StoredState objects with the same name.",
            )

    # The content must be marshallable.
    for ss in state.stored_states:
        # We don't need the marshalled state, just to know that it can be.
        # This is the same "only simple types" check that ops does.
        try:
            marshal.dumps(ss.content)
        except ValueError:
            errors.append(
                f"The StoredState object {ss.owner_path}.{ss.name} should contain only simple types.",
            )
    return Results(errors, [])
