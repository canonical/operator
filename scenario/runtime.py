import dataclasses
import logging
import marshal
import os
import re
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional, Type, TypeVar, Union

import yaml
from ops.framework import _event_regex
from ops.log import JujuLogHandler
from ops.storage import SQLiteStorage

from scenario.logger import logger as scenario_logger
from scenario.ops_main_mock import NoObserverError

if TYPE_CHECKING:
    from ops.charm import CharmBase
    from ops.framework import EventBase
    from ops.testing import CharmType

    from scenario.state import Event, State, _CharmSpec

    _CT = TypeVar("_CT", bound=Type[CharmType])

logger = scenario_logger.getChild("runtime")
# _stored_state_regex = "(.*)\/(\D+)\[(.*)\]"
_stored_state_regex = "((?P<owner_path>.*)\/)?(?P<data_type_name>\D+)\[(?P<name>.*)\]"

RUNTIME_MODULE = Path(__file__).parent


class UncaughtCharmError(RuntimeError):
    """Error raised if the charm raises while handling the event being dispatched."""


@dataclasses.dataclass
class RuntimeRunResult:
    charm: "CharmBase"
    scene: "Scene"
    event: "EventBase"


class Runtime:
    """Charm runtime wrapper.

    This object bridges a local environment and a charm artifact.
    """

    def __init__(
        self,
        charm_spec: "_CharmSpec",
        juju_version: str = "3.0.0",
    ):
        self._charm_spec = charm_spec
        self._juju_version = juju_version
        # TODO consider cleaning up venv on __delete__, but ideally you should be
        #  running this in a clean venv or a container anyway.

    @staticmethod
    def from_local_file(
        local_charm_src: Path,
        charm_cls_name: str,
    ) -> "Runtime":
        sys.path.extend((str(local_charm_src / "src"), str(local_charm_src / "lib")))

        ldict = {}

        try:
            exec(
                f"from charm import {charm_cls_name} as my_charm_type", globals(), ldict
            )
        except ModuleNotFoundError as e:
            raise RuntimeError(
                f"Failed to load charm {charm_cls_name}. "
                f"Probably some dependency is missing. "
                f"Try `pip install -r {local_charm_src / 'requirements.txt'}`"
            ) from e

        my_charm_type: Type["CharmBase"] = ldict["my_charm_type"]
        return Runtime(_CharmSpec(my_charm_type))  # TODO add meta, options,...

    @staticmethod
    def _cleanup_env(env):
        # cleanup env, in case we'll be firing multiple events, we don't want to accumulate.
        for key in env:
            os.unsetenv(key)

    @property
    def unit_name(self):
        meta = self._charm_spec.meta
        if not meta:
            return "local/0"
        return meta["name"] + "/0"  # todo allow override

    def _get_event_env(self, state: "State", event: "Event", charm_root: Path):
        if event.name.endswith("_action"):
            # todo: do we need some special metadata, or can we assume action names are always dashes?
            action_name = event.name[: -len("_action")].replace("_", "-")
        else:
            action_name = ""

        env = {
            "JUJU_VERSION": self._juju_version,
            "JUJU_UNIT_NAME": self.unit_name,
            "_": "./dispatch",
            "JUJU_DISPATCH_PATH": f"hooks/{event.name}",
            "JUJU_MODEL_NAME": state.model.name,
            "JUJU_ACTION_NAME": action_name,
            "JUJU_MODEL_UUID": state.model.uuid,
            "JUJU_CHARM_DIR": str(charm_root.absolute())
            # todo consider setting pwd, (python)path
        }

        if relation := event.relation:
            env.update(
                {
                    "JUJU_RELATION": relation.endpoint,
                    "JUJU_RELATION_ID": str(relation.relation_id),
                }
            )

        if container := event.container:
            env.update({"JUJU_WORKLOAD_NAME": container.name})

        if secret := event.secret:
            env.update(
                {
                    "JUJU_SECRET_ID": secret.id,
                    "JUJU_SECRET_LABEL": secret.label or "",
                }
            )

        return env

    @staticmethod
    def _wrap(charm_type: "_CT") -> "_CT":
        # dark sorcery to work around framework using class attrs to hold on to event sources
        # todo this should only be needed if we call play multiple times on the same runtime.
        #  can we avoid it?
        class WrappedEvents(charm_type.on.__class__):
            pass

        WrappedEvents.__name__ = charm_type.on.__class__.__name__

        class WrappedCharm(charm_type):  # type: ignore
            on = WrappedEvents()

        WrappedCharm.__name__ = charm_type.__name__
        return WrappedCharm

    @contextmanager
    def virtual_charm_root(self):
        # If we are using runtime on a real charm, we can make some assumptions about the directory structure
        #  we are going to find.
        #  If we're, say, dynamically defining charm types and doing tests on them, we'll have to generate
        #  the metadata files ourselves. To be sure, we ALWAYS use a tempdir. Ground truth is what the user
        #  passed via the CharmSpec
        spec = self._charm_spec
        with tempfile.TemporaryDirectory() as tempdir:
            temppath = Path(tempdir)
            (temppath / "metadata.yaml").write_text(yaml.safe_dump(spec.meta))
            (temppath / "config.yaml").write_text(yaml.safe_dump(spec.config or {}))
            (temppath / "actions.yaml").write_text(yaml.safe_dump(spec.actions or {}))
            yield temppath

    @staticmethod
    def _get_store(temporary_charm_root: Path):
        charm_state_path = temporary_charm_root / ".unit-state.db"
        store = SQLiteStorage(charm_state_path)
        return store

    def _initialize_storage(self, state: "State", temporary_charm_root: Path):
        """Before we start processing this event, expose the relevant parts of State through the storage."""
        store = self._get_store(temporary_charm_root)

        for event in state.deferred:
            store.save_notice(event.handle_path, event.owner, event.observer)
            try:
                marshal.dumps(event.snapshot_data)
            except ValueError as e:
                raise ValueError(
                    f"unable to save the data for {event}, it must contain only simple types."
                ) from e
            store.save_snapshot(event.handle_path, event.snapshot_data)

        for stored_state in state.stored_state:
            store.save_snapshot(stored_state.handle_path, stored_state.content)

        store.close()

    def _close_storage(self, state: "State", temporary_charm_root: Path):
        """Now that we're done processing this event, read the charm state and expose it via State."""
        from scenario.state import DeferredEvent, StoredState  # avoid cyclic import

        store = self._get_store(temporary_charm_root)

        deferred = []
        stored_state = []
        event_regex = re.compile(_event_regex)
        sst_regex = re.compile(_stored_state_regex)
        for handle_path in store.list_snapshots():
            if event_regex.match(handle_path):
                notices = store.notices(handle_path)
                for handle, owner, observer in notices:
                    event = DeferredEvent(
                        handle_path=handle, owner=owner, observer=observer
                    )
                    deferred.append(event)

            else:
                # it's a StoredState. TODO: No other option, right?
                stored_state_snapshot = store.load_snapshot(handle_path)
                match = sst_regex.match(handle_path)
                if not match:
                    logger.warning(
                        f"could not parse handle path {handle_path!r} as stored state"
                    )
                    continue

                kwargs = match.groupdict()
                sst = StoredState(content=stored_state_snapshot, **kwargs)
                stored_state.append(sst)

        store.close()
        return state.replace(deferred=deferred, stored_state=stored_state)

    def exec(
        self,
        state: "State",
        event: "Event",
        pre_event: Optional[Callable[["CharmType"], None]] = None,
        post_event: Optional[Callable[["CharmType"], None]] = None,
    ) -> "State":
        """Runs an event with this state as initial state on a charm.

        Returns the 'output state', that is, the state as mutated by the charm during the event handling.

        This will set the environment up and call ops.main.main().
        After that it's up to ops.
        """
        charm_type = self._charm_spec.charm_type
        logger.info(f"Preparing to fire {event.name} on {charm_type.__name__}")

        # we make a copy to avoid mutating the input state
        output_state = state.copy()

        logger.info(" - generating virtual charm root")
        with self.virtual_charm_root() as temporary_charm_root:
            # todo consider forking out a real subprocess and do the mocking by
            #  generating hook tool executables

            logger.info(" - initializing storage")
            self._initialize_storage(state, temporary_charm_root)

            logger.info(" - preparing env")
            env = self._get_event_env(
                state=state, event=event, charm_root=temporary_charm_root
            )
            os.environ.update(env)

            logger.info(" - Entering ops.main (mocked).")
            # we don't import from ops.main because we need some extras, such as the pre/post_event hooks
            from scenario.ops_main_mock import main as mocked_main

            try:
                mocked_main(
                    pre_event=pre_event,
                    post_event=post_event,
                    state=output_state,
                    event=event,
                    charm_spec=self._charm_spec.replace(
                        charm_type=self._wrap(charm_type)
                    ),
                )
            except NoObserverError:
                raise  # propagate along
            except Exception as e:
                raise UncaughtCharmError(
                    f"Uncaught error in operator/charm code: {e}."
                ) from e
            finally:
                logger.info(" - Exited ops.main.")

            logger.info(" - clearing env")
            self._cleanup_env(env)

            logger.info(" - closing storage")
            output_state = self._close_storage(output_state, temporary_charm_root)

        logger.info("event dispatched. done.")
        return output_state


def trigger(
    state: "State",
    event: Union["Event", str],
    charm_type: Type["CharmType"],
    pre_event: Optional[Callable[["CharmType"], None]] = None,
    post_event: Optional[Callable[["CharmType"], None]] = None,
    # if not provided, will be autoloaded from charm_type.
    meta: Optional[Dict[str, Any]] = None,
    actions: Optional[Dict[str, Any]] = None,
    config: Optional[Dict[str, Any]] = None,
) -> "State":
    from scenario.state import Event, _CharmSpec

    if isinstance(event, str):
        event = Event(event)

    if not any((meta, actions, config)):
        logger.debug("Autoloading charmspec...")
        spec = _CharmSpec.autoload(charm_type)
    else:
        if not meta:
            meta = {"name": str(charm_type.__name__)}
        spec = _CharmSpec(
            charm_type=charm_type, meta=meta, actions=actions, config=config
        )

    runtime = Runtime(charm_spec=spec, juju_version=state.juju_version)

    return runtime.exec(
        state=state,
        event=event,
        pre_event=pre_event,
        post_event=post_event,
    )
