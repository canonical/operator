#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import logging
import os
import sys
from pathlib import Path
from subprocess import CalledProcessError, run
from typing import Dict, Iterable, List, Optional

import typer

from scenario.scripts.errors import InvalidTargetUnitName, StateApplyError
from scenario.scripts.utils import JujuUnitName
from scenario.state import (
    Container,
    DeferredEvent,
    Relation,
    Secret,
    State,
    Status,
    StoredState,
)

SNAPSHOT_DATA_DIR = (Path(os.getcwd()).parent / "snapshot_storage").absolute()

logger = logging.getLogger("snapshot")


def set_relations(relations: Iterable[Relation]) -> List[str]:  # noqa: U100
    logger.info("preparing relations...")
    logger.warning("set_relations not implemented yet")
    return []


def set_status(status: Status) -> List[str]:
    logger.info("preparing status...")
    cmds = []

    cmds.append(f"status-set {status.unit.name} {status.unit.message}")
    cmds.append(f"status-set --application {status.app.name} {status.app.message}")
    cmds.append(f"application-version-set {status.app_version}")

    return cmds


def set_config(config: Dict[str, str]) -> List[str]:  # noqa: U100
    logger.info("preparing config...")
    logger.warning("set_config not implemented yet")
    return []


def set_containers(containers: Iterable[Container]) -> List[str]:  # noqa: U100
    logger.info("preparing containers...")
    logger.warning("set_containers not implemented yet")
    return []


def set_secrets(secrets: Iterable[Secret]) -> List[str]:  # noqa: U100
    logger.info("preparing secrets...")
    logger.warning("set_secrets not implemented yet")
    return []


def set_deferred_events(
    deferred_events: Iterable[DeferredEvent],  # noqa: U100
) -> List[str]:
    logger.info("preparing deferred_events...")
    logger.warning("set_deferred_events not implemented yet")
    return []


def set_stored_state(stored_state: Iterable[StoredState]) -> List[str]:  # noqa: U100
    logger.info("preparing stored_state...")
    logger.warning("set_stored_state not implemented yet")
    return []


def exec_in_unit(target: JujuUnitName, model: str, cmds: List[str]):
    logger.info("Running juju exec...")

    _model = f" -m {model}" if model else ""
    cmd_fmt = "; ".join(cmds)
    try:
        run(f'juju exec -u {target}{_model} -- "{cmd_fmt}"')
    except CalledProcessError as e:
        raise StateApplyError(
            f"Failed to apply state: process exited with {e.returncode}; "
            f"stdout = {e.stdout}; "
            f"stderr = {e.stderr}.",
        )


def run_commands(cmds: List[str]):
    logger.info("Applying remaining state...")
    for cmd in cmds:
        try:
            run(cmd)
        except CalledProcessError as e:
            # todo: should we log and continue instead?
            raise StateApplyError(
                f"Failed to apply state: process exited with {e.returncode}; "
                f"stdout = {e.stdout}; "
                f"stderr = {e.stderr}.",
            )


def _state_apply(
    target: str,
    state: State,
    model: Optional[str] = None,
    include: str = None,
    include_juju_relation_data=False,  # noqa: U100
    push_files: Dict[str, List[Path]] = None,  # noqa: U100
    snapshot_data_dir: Path = SNAPSHOT_DATA_DIR,  # noqa: U100
):
    """see state_apply's docstring"""
    logger.info("Starting state-apply...")

    try:
        target = JujuUnitName(target)
    except InvalidTargetUnitName:
        logger.critical(
            f"invalid target: {target!r} is not a valid unit name. Should be formatted like so:"
            f"`foo/1`, or `database/0`, or `myapp-foo-bar/42`.",
        )
        sys.exit(1)

    logger.info(f'beginning snapshot of {target} in model {model or "<current>"}...')

    def if_include(key, fn):
        if include is None or key in include:
            return fn()
        return []

    j_exec_cmds: List[str] = []

    j_exec_cmds += if_include("s", lambda: set_status(state.status))
    j_exec_cmds += if_include("r", lambda: set_relations(state.relations))
    j_exec_cmds += if_include("S", lambda: set_secrets(state.secrets))

    cmds: List[str] = []

    # todo: config is a bit special because it's not owned by the unit but by the cloud admin.
    #  should it be included in state-apply?
    # if_include("c", lambda: set_config(state.config))
    cmds += if_include("k", lambda: set_containers(state.containers))
    cmds += if_include("d", lambda: set_deferred_events(state.deferred))
    cmds += if_include("t", lambda: set_stored_state(state.stored_state))

    # we gather juju-exec commands to run them all at once in the unit.
    exec_in_unit(target, model, j_exec_cmds)
    # non-juju-exec commands are ran one by one, individually
    run_commands(cmds)

    logger.info("Done!")


def state_apply(
    target: str = typer.Argument(..., help="Target unit."),
    state: Path = typer.Argument(
        ...,
        help="Source State to apply. Json file containing a State data structure; "
        "the same you would obtain by running snapshot.",
    ),
    model: Optional[str] = typer.Option(
        None,
        "-m",
        "--model",
        help="Which model to look at.",
    ),
    include: str = typer.Option(
        "scrkSdt",
        "--include",
        "-i",
        help="What parts of the state to apply. Defaults to: all of them. "
        "``r``: relation, ``c``: config, ``k``: containers, "
        "``s``: status, ``S``: secrets(!), "
        "``d``: deferred events, ``t``: stored state.",
    ),
    include_juju_relation_data: bool = typer.Option(
        False,
        "--include-juju-relation-data",
        help="Whether to include in the relation data the default juju keys (egress-subnets,"
        "ingress-address, private-address).",
        is_flag=True,
    ),
    push_files: Path = typer.Option(
        None,
        "--push-files",
        help="Path to a local file containing a json spec of files to be fetched from the unit. "
        "For k8s units, it's supposed to be a {container_name: List[Path]} mapping listing "
        "the files that need to be pushed to the each container.",
    ),
    # TODO: generalize "push_files" to allow passing '.' for the 'charm' container or 'the machine'.
    data_dir: Path = typer.Option(
        SNAPSHOT_DATA_DIR,
        "--data-dir",
        help="Directory in which to any files associated with the state are stored. In the case "
        "of k8s charms, this might mean files obtained through Mounts,",
    ),
):
    """Gather and output the State of a remote target unit.

    If black is available, the output will be piped through it for formatting.

    Usage: state-apply myapp/0 > ./tests/scenario/case1.py
    """
    push_files_ = json.loads(push_files.read_text()) if push_files else None
    state_ = json.loads(state.read_text())

    return _state_apply(
        target=target,
        state=state_,
        model=model,
        include=include,
        include_juju_relation_data=include_juju_relation_data,
        snapshot_data_dir=data_dir,
        push_files=push_files_,
    )


# for the benefit of scripted usage
_state_apply.__doc__ = state_apply.__doc__

if __name__ == "__main__":
    from scenario import State

    _state_apply("zookeeper/0", model="foo", state=State())
