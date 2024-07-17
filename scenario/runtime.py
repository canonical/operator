#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import marshal
import os
import re
import tempfile
import typing
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional, Type, Union

import yaml
from ops import pebble
from ops.framework import _event_regex
from ops.storage import NoSnapshotError, SQLiteStorage

from scenario.capture_events import capture_events
from scenario.logger import logger as scenario_logger
from scenario.ops_main_mock import NoObserverError
from scenario.state import DeferredEvent, PeerRelation, StoredState

if TYPE_CHECKING:  # pragma: no cover
    from ops.testing import CharmType

    from scenario.context import Context
    from scenario.state import Event, State, _CharmSpec

    PathLike = Union[str, Path]

logger = scenario_logger.getChild("runtime")
STORED_STATE_REGEX = re.compile(
    r"((?P<owner_path>.*)\/)?(?P<data_type_name>\D+)\[(?P<name>.*)\]",
)
EVENT_REGEX = re.compile(_event_regex)

RUNTIME_MODULE = Path(__file__).parent


class ScenarioRuntimeError(RuntimeError):
    """Base class for exceptions raised by scenario.runtime."""


class UncaughtCharmError(ScenarioRuntimeError):
    """Error raised if the charm raises while handling the event being dispatched."""


class InconsistentScenarioError(ScenarioRuntimeError):
    """Error raised when the combination of state and event is inconsistent."""


class UnitStateDB:
    """Represents the unit-state.db."""

    def __init__(self, db_path: Union[Path, str]):
        self._db_path = db_path
        self._state_file = Path(self._db_path)

    def _open_db(self) -> SQLiteStorage:
        """Open the db."""
        return SQLiteStorage(self._state_file)

    def get_stored_state(self) -> List["StoredState"]:
        """Load any StoredState data structures from the db."""

        db = self._open_db()

        stored_state = []
        for handle_path in db.list_snapshots():
            if not EVENT_REGEX.match(handle_path) and (
                match := STORED_STATE_REGEX.match(handle_path)
            ):
                stored_state_snapshot = db.load_snapshot(handle_path)
                kwargs = match.groupdict()
                sst = StoredState(content=stored_state_snapshot, **kwargs)
                stored_state.append(sst)

        db.close()
        return stored_state

    def get_deferred_events(self) -> List["DeferredEvent"]:
        """Load any DeferredEvent data structures from the db."""

        db = self._open_db()

        deferred = []
        for handle_path in db.list_snapshots():
            if EVENT_REGEX.match(handle_path):
                notices = db.notices(handle_path)
                for handle, owner, observer in notices:
                    try:
                        snapshot_data = db.load_snapshot(handle)
                    except NoSnapshotError:
                        snapshot_data = {}

                    event = DeferredEvent(
                        handle_path=handle,
                        owner=owner,
                        observer=observer,
                        snapshot_data=snapshot_data,
                    )
                    deferred.append(event)

        db.close()
        return deferred

    def apply_state(self, state: "State"):
        """Add DeferredEvent and StoredState from this State instance to the storage."""
        db = self._open_db()
        for event in state.deferred:
            db.save_notice(event.handle_path, event.owner, event.observer)
            try:
                marshal.dumps(event.snapshot_data)
            except ValueError as e:
                raise ValueError(
                    f"unable to save the data for {event}, it must contain only simple types.",
                ) from e
            db.save_snapshot(event.handle_path, event.snapshot_data)

        for stored_state in state.stored_state:
            db.save_snapshot(stored_state.handle_path, stored_state.content)

        db.close()


class _OpsMainContext:
    """Context manager representing ops.main execution context.

    When entered, ops.main sets up everything up until the charm.
    When .emit() is called, ops.main proceeds with emitting the event.
    When exited, if .emit has not been called manually, it is called automatically.
    """

    def __init__(self):
        self._has_emitted = False

    def __enter__(self):
        pass

    def emit(self):
        self._has_emitted = True

    def __exit__(self, exc_type, exc_val, exc_tb):  # noqa: U100
        if not self._has_emitted:
            self.emit()


class Runtime:
    """Charm runtime wrapper.

    This object bridges a local environment and a charm artifact.
    """

    def __init__(
        self,
        charm_spec: "_CharmSpec",
        charm_root: Optional["PathLike"] = None,
        juju_version: str = "3.0.0",
        app_name: Optional[str] = None,
        unit_id: Optional[int] = 0,
    ):
        self._charm_spec = charm_spec
        self._juju_version = juju_version
        self._charm_root = charm_root

        app_name = app_name or self._charm_spec.meta.get("name")
        if not app_name:
            raise ValueError('invalid metadata: mandatory "name" field is missing.')

        self._app_name = app_name
        self._unit_id = unit_id

    @staticmethod
    def _cleanup_env(env):
        # TODO consider cleaning up env on __delete__, but ideally you should be
        #  running this in a clean env or a container anyway.
        # cleanup the env, in case we'll be firing multiple events, we don't want to pollute it.
        for key in env:
            # os.unsetenv does not always seem to work !?
            del os.environ[key]

    def _get_event_env(self, state: "State", event: "Event", charm_root: Path):
        """Build the simulated environment the operator framework expects."""
        env = {
            "JUJU_VERSION": self._juju_version,
            "JUJU_UNIT_NAME": f"{self._app_name}/{self._unit_id}",
            "_": "./dispatch",
            "JUJU_DISPATCH_PATH": f"hooks/{event.name}",
            "JUJU_MODEL_NAME": state.model.name,
            "JUJU_MODEL_UUID": state.model.uuid,
            "JUJU_CHARM_DIR": str(charm_root.absolute()),
            # todo consider setting pwd, (python)path
        }

        if event._is_action_event and (action := event.action):
            env.update(
                {
                    # TODO: we should check we're doing the right thing here.
                    "JUJU_ACTION_NAME": action.name.replace("_", "-"),
                    "JUJU_ACTION_UUID": action.id,
                },
            )

        if event._is_relation_event and (relation := event.relation):
            if isinstance(relation, PeerRelation):
                remote_app_name = self._app_name
            else:
                remote_app_name = relation.remote_app_name
            env.update(
                {
                    "JUJU_RELATION": relation.endpoint,
                    "JUJU_RELATION_ID": str(relation.relation_id),
                    "JUJU_REMOTE_APP": remote_app_name,
                },
            )

            remote_unit_id = event.relation_remote_unit_id

            # don't check truthiness because remote_unit_id could be 0
            if remote_unit_id is None:
                remote_unit_ids = relation._remote_unit_ids  # pyright: ignore

                if len(remote_unit_ids) == 1:
                    remote_unit_id = remote_unit_ids[0]
                    logger.info(
                        "there's only one remote unit, so we set JUJU_REMOTE_UNIT to it, "
                        "but you probably should be parametrizing the event with `remote_unit_id` "
                        "to be explicit.",
                    )
                elif len(remote_unit_ids) > 1:
                    remote_unit_id = remote_unit_ids[0]
                    logger.warning(
                        "remote unit ID unset, and multiple remote unit IDs are present; "
                        "We will pick the first one and hope for the best. You should be passing "
                        "`remote_unit_id` to the Event constructor.",
                    )
                else:
                    logger.warning(
                        "remote unit ID unset; no remote unit data present. "
                        "Is this a realistic scenario?",  # TODO: is it?
                    )

            if remote_unit_id is not None:
                remote_unit = f"{remote_app_name}/{remote_unit_id}"
                env["JUJU_REMOTE_UNIT"] = remote_unit
                if event.name.endswith("_relation_departed"):
                    env["JUJU_DEPARTING_UNIT"] = remote_unit

        if container := event.container:
            env.update({"JUJU_WORKLOAD_NAME": container.name})

        if notice := event.notice:
            if hasattr(notice.type, "value"):
                notice_type = typing.cast(pebble.NoticeType, notice.type).value
            else:
                notice_type = str(notice.type)
            env.update(
                {
                    "JUJU_NOTICE_ID": notice.id,
                    "JUJU_NOTICE_TYPE": notice_type,
                    "JUJU_NOTICE_KEY": notice.key,
                },
            )

        if storage := event.storage:
            env.update({"JUJU_STORAGE_ID": f"{storage.name}/{storage.index}"})

        if secret := event.secret:
            env.update(
                {
                    "JUJU_SECRET_ID": secret.id,
                    "JUJU_SECRET_LABEL": secret.label or "",
                },
            )
            if event.name in ("secret_remove", "secret_expired"):
                env["JUJU_SECRET_REVISION"] = str(secret.revision)

        return env

    @staticmethod
    def _wrap(charm_type: Type["CharmType"]) -> Type["CharmType"]:
        # dark sorcery to work around framework using class attrs to hold on to event sources
        # todo this should only be needed if we call play multiple times on the same runtime.
        #  can we avoid it?
        class WrappedEvents(charm_type.on.__class__):
            pass

        WrappedEvents.__name__ = charm_type.on.__class__.__name__

        class WrappedCharm(charm_type):  # type: ignore
            on = WrappedEvents()

        WrappedCharm.__name__ = charm_type.__name__
        return typing.cast(Type["CharmType"], WrappedCharm)

    @contextmanager
    def _virtual_charm_root(self):
        # If we are using runtime on a real charm, we can make some assumptions about the
        # directory structure we are going to find.
        # If we're, say, dynamically defining charm types and doing tests on them, we'll have to
        # generate the metadata files ourselves. To be sure, we ALWAYS use a tempdir. Ground truth
        # is what the user passed via the CharmSpec
        spec = self._charm_spec

        if charm_virtual_root := self._charm_root:
            charm_virtual_root_is_custom = True
            virtual_charm_root = Path(charm_virtual_root)
        else:
            charm_virtual_root = tempfile.TemporaryDirectory()
            virtual_charm_root = Path(charm_virtual_root.name)
            charm_virtual_root_is_custom = False

        metadata_yaml = virtual_charm_root / "metadata.yaml"
        config_yaml = virtual_charm_root / "config.yaml"
        actions_yaml = virtual_charm_root / "actions.yaml"

        metadata_files_present: Dict[Path, Optional[str]] = {
            file: file.read_text() if file.exists() else None
            for file in (metadata_yaml, config_yaml, actions_yaml)
        }

        any_metadata_files_present_in_charm_virtual_root = any(
            v is not None for v in metadata_files_present.values()
        )

        if spec.is_autoloaded and charm_virtual_root_is_custom:
            # since the spec is autoloaded, in theory the metadata contents won't differ, so we can
            # overwrite away even if the custom vroot is the real charm root (the local repo).
            # Still, log it for clarity.
            if any_metadata_files_present_in_charm_virtual_root:
                logger.debug(
                    f"metadata files found in custom charm_root {charm_virtual_root}. "
                    f"The spec was autoloaded so the contents should be identical. "
                    f"Proceeding...",
                )

        elif (
            not spec.is_autoloaded and any_metadata_files_present_in_charm_virtual_root
        ):
            logger.warn(
                f"Some metadata files found in custom user-provided charm_root "
                f"{charm_virtual_root} while you have passed meta, config or actions to "
                f"Context.run(). "
                "Single source of truth are the arguments passed to Context.run(). "
                "charm_root metadata files will be overwritten for the "
                "duration of this test, and restored afterwards. "
                "To avoid this, clean any metadata files from the charm_root before calling run.",
            )

        metadata_yaml.write_text(yaml.safe_dump(spec.meta))
        config_yaml.write_text(yaml.safe_dump(spec.config or {}))
        actions_yaml.write_text(yaml.safe_dump(spec.actions or {}))

        yield virtual_charm_root

        if charm_virtual_root_is_custom:
            for file, previous_content in metadata_files_present.items():
                if previous_content is None:  # None == file did not exist before
                    file.unlink()
                else:
                    file.write_text(previous_content)

        else:
            # charm_virtual_root is a tempdir
            typing.cast(tempfile.TemporaryDirectory, charm_virtual_root).cleanup()

    @staticmethod
    def _get_state_db(temporary_charm_root: Path):
        charm_state_path = temporary_charm_root / ".unit-state.db"
        return UnitStateDB(charm_state_path)

    def _initialize_storage(self, state: "State", temporary_charm_root: Path):
        """Before we start processing this event, store the relevant parts of State."""
        store = self._get_state_db(temporary_charm_root)
        store.apply_state(state)

    def _close_storage(self, state: "State", temporary_charm_root: Path):
        """Now that we're done processing this event, read the charm state and expose it."""
        store = self._get_state_db(temporary_charm_root)
        deferred = store.get_deferred_events()
        stored_state = store.get_stored_state()
        return state.replace(deferred=deferred, stored_state=stored_state)

    @contextmanager
    def _exec_ctx(self, ctx: "Context"):
        """python 3.8 compatibility shim"""
        with self._virtual_charm_root() as temporary_charm_root:
            # todo allow customizing capture_events
            with capture_events(
                include_deferred=ctx.capture_deferred_events,
                include_framework=ctx.capture_framework_events,
            ) as captured:
                yield (temporary_charm_root, captured)

    @contextmanager
    def exec(
        self,
        state: "State",
        event: "Event",
        context: "Context",
    ):
        """Runs an event with this state as initial state on a charm.

        Returns the 'output state', that is, the state as mutated by the charm during the
        event handling.

        This will set the environment up and call ops.main.main().
        After that it's up to ops.
        """
        # todo consider forking out a real subprocess and do the mocking by
        #  mocking hook tool executables

        from scenario.consistency_checker import check_consistency  # avoid cycles

        check_consistency(state, event, self._charm_spec, self._juju_version)

        charm_type = self._charm_spec.charm_type
        logger.info(f"Preparing to fire {event.name} on {charm_type.__name__}")

        # we make a copy to avoid mutating the input state
        output_state = state.copy()

        logger.info(" - generating virtual charm root")
        with self._exec_ctx(context) as (temporary_charm_root, captured):
            logger.info(" - initializing storage")
            self._initialize_storage(state, temporary_charm_root)

            logger.info(" - preparing env")
            env = self._get_event_env(
                state=state,
                event=event,
                charm_root=temporary_charm_root,
            )
            os.environ.update(env)

            logger.info(" - Entering ops.main (mocked).")
            from scenario.ops_main_mock import Ops  # noqa: F811

            try:
                ops = Ops(
                    state=output_state,
                    event=event,
                    context=context,
                    charm_spec=self._charm_spec.replace(
                        charm_type=self._wrap(charm_type),
                    ),
                )
                ops.setup()

                yield ops

                # if the caller did not manually emit or commit: do that.
                ops.finalize()

            except NoObserverError:
                raise  # propagate along
            except Exception as e:
                raise UncaughtCharmError(
                    f"Uncaught exception ({type(e)}) in operator/charm code: {e!r}",
                ) from e

            finally:
                logger.info(" - Exited ops.main.")

                logger.info(" - Clearing env")
                self._cleanup_env(env)

            logger.info(" - closing storage")
            output_state = self._close_storage(output_state, temporary_charm_root)

        context.emitted_events.extend(captured)
        logger.info("event dispatched. done.")
        context._set_output_state(output_state)
