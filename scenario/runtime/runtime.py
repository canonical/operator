import dataclasses
import os
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional, Type, TypeVar, Union

import yaml

from scenario.event_db import TemporaryEventDB
from scenario.logger import logger as pkg_logger
from scenario.runtime.memo import (
    MEMO_DATABASE_NAME_KEY,
    MEMO_MODE_KEY,
    MEMO_REPLAY_INDEX_KEY,
    USE_STATE_KEY,
)
from scenario.runtime.memo import Event as MemoEvent
from scenario.runtime.memo import MemoModes
from scenario.runtime.memo import Scene as MemoScene
from scenario.runtime.memo import _reset_replay_cursors, event_db
from scenario.runtime.memo_tools import (
    DECORATE_MODEL,
    DECORATE_PEBBLE,
    IMPORT_BLOCK,
    inject_memoizer,
)

if TYPE_CHECKING:
    from ops.charm import CharmBase
    from ops.framework import EventBase
    from ops.testing import CharmType

    from scenario.structs import CharmSpec, Scene

    _CT = TypeVar("_CT", bound=Type[CharmType])

logger = pkg_logger.getChild("runtime")

RUNTIME_MODULE = Path(__file__).parent


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
        charm_spec: "CharmSpec",
        juju_version: str = "3.0.0",
        event_db_path: Optional[Union[Path, str]] = None,
    ):
        self._event_db_path = Path(event_db_path) if event_db_path else None
        self._charm_spec = charm_spec
        self._juju_version = juju_version
        self._charm_type = charm_spec.charm_type
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
        return Runtime(CharmSpec(my_charm_type))  # TODO add meta, options,...

    @staticmethod
    def install(force=False):
        """Install the runtime LOCALLY.

        Fine prints:
          - this will **REWRITE** your local ops.model module to include a @memo decorator
            in front of all hook-tool calls.
          - this will mess with your os.environ.
          - These operations might not be reversible, so consider your environment corrupted.
            You should be calling this in a throwaway venv, and probably a container sandbox.

            Nobody will help you fix your borked env.
            Have fun!
        """

        if not force and Runtime._is_installed():
            logger.warning(
                "Runtime is already installed. "
                "Pass `force=True` if you wish to proceed anyway. "
                "Skipping..."
            )
            return

        logger.warning(
            "Installing Runtime... "
            "DISCLAIMER: this **might** (aka: most definitely will) corrupt your venv."
        )

        from ops import pebble

        ops_pebble_module = Path(pebble.__file__)
        logger.info(f"rewriting ops.pebble ({ops_pebble_module})")
        inject_memoizer(ops_pebble_module, decorate=DECORATE_PEBBLE)

        from ops import model

        ops_model_module = Path(model.__file__)
        logger.info(f"rewriting ops.model ({ops_model_module})")
        inject_memoizer(ops_model_module, decorate=DECORATE_MODEL)

    @staticmethod
    def _is_installed():
        try:
            from ops import model
        except RuntimeError as e:
            # we rewrite ops.model to import memo.
            # We try to import ops from here --> circular import.
            if e.args[0].startswith("scenario not installed"):
                return True
            raise e

        model_path = Path(model.__file__)

        if IMPORT_BLOCK not in model_path.read_text():
            logger.error(
                f"ops.model ({model_path} does not seem to import runtime.memo.memo"
            )
            return False

        try:
            from scenario import memo
        except ModuleNotFoundError:
            logger.error("Could not `import memo`.")
            return False

        logger.info(f"Recorder is installed at {model_path}")
        return True

    def _redirect_root_logger(self):
        # the root logger set up by ops calls a hook tool: `juju-log`.
        # that is a problem for us because `juju-log` is itself memoized, which leads to recursion.
        def _patch_logger(*args, **kwargs):
            logger.debug("Hijacked root logger.")
            pass

        from scenario import ops_main_mock

        ops_main_mock.setup_root_logging = _patch_logger

    def _cleanup_env(self, env):
        # cleanup env, in case we'll be firing multiple events, we don't want to accumulate.
        for key in env:
            del os.environ[key]

    @property
    def unit_name(self):
        meta = self._charm_spec.meta
        if not meta:
            return "foo/0"
        return meta["name"] + "/0"  # todo allow override

    def _get_event_env(self, scene: "Scene", charm_root: Path):
        env = {
            "JUJU_VERSION": self._juju_version,
            "JUJU_UNIT_NAME": self.unit_name,
            "_": "./dispatch",
            "JUJU_DISPATCH_PATH": f"hooks/{scene.event.name}",
            "JUJU_MODEL_NAME": scene.context.state.model.name,
            "JUJU_MODEL_UUID": scene.context.state.model.uuid,
            "JUJU_CHARM_DIR": str(charm_root.absolute())
            # todo consider setting pwd, (python)path
        }

        if scene.event.meta and scene.event.meta.relation:
            relation = scene.event.meta.relation
            env.update(
                {
                    'JUJU_RELATION': relation.endpoint,
                    'JUJU_RELATION_ID': str(relation.relation_id),
                 }
            )
        return env

    def _drop_meta(self, charm_root: Path):
        logger.debug("Dropping metadata.yaml, config.yaml, actions.yaml...")
        (charm_root / "metadata.yaml").write_text(yaml.safe_dump(self._charm_spec.meta))
        if self._charm_spec.actions:
            (charm_root / "actions.yaml").write_text(
                yaml.safe_dump(self._charm_spec.actions)
            )
        if self._charm_spec.config:
            (charm_root / "config.yaml").write_text(
                yaml.safe_dump(self._charm_spec.config)
            )

    def _get_runtime_env(
        self, scene_idx: int, db_path: Path, mode: MemoModes = "replay"
    ):
        env = {}
        env.update(
            {
                USE_STATE_KEY: "1",
                MEMO_REPLAY_INDEX_KEY: str(scene_idx),
                MEMO_DATABASE_NAME_KEY: str(db_path),
            }
        )
        sys.path.append(str(RUNTIME_MODULE.absolute()))
        env[MEMO_MODE_KEY] = mode

        os.environ.update(env)  # todo consider subprocess
        return env

    def _scene_to_memo_scene(self, scene: "Scene", env: dict) -> MemoScene:
        """Convert scenario.structs.Scene to Memo.Scene."""
        return MemoScene(event=MemoEvent(env=env), context=scene.context)

    def _wrap(self, charm_type: "_CT") -> "_CT":
        # dark sorcery to work around framework using class attrs to hold on to event sources
        class WrappedEvents(charm_type.on.__class__):
            pass

        WrappedEvents.__name__ = charm_type.on.__class__.__name__

        class WrappedCharm(charm_type):  # type: ignore
            on = WrappedEvents()

        WrappedCharm.__name__ = charm_type.__name__
        return WrappedCharm

    def play(
        self,
        scene: "Scene",
        pre_event: Optional[Callable[["_CT"], None]] = None,
        post_event: Optional[Callable[["_CT"], None]] = None,
    ) -> RuntimeRunResult:
        """Plays a scene on the charm.

        This will set the environment up and call ops.main.main().
        After that it's up to ops.
        """
        if not Runtime._is_installed():
            raise RuntimeError(
                "Runtime is not installed. Call `runtime.install()` (and read the fine prints)."
            )

        logger.info(
            f"Preparing to fire {scene.event.name} on {self._charm_type.__name__}"
        )

        logger.info(" - preparing env")
        with tempfile.TemporaryDirectory() as charm_root:
            charm_root_path = Path(charm_root)
            env = self._get_event_env(scene, charm_root_path)
            self._drop_meta(charm_root_path)

            memo_scene = self._scene_to_memo_scene(scene, env)
            with TemporaryEventDB(memo_scene, charm_root) as db_path:
                env.update(self._get_runtime_env(0, db_path))

                logger.info(" - redirecting root logging")
                self._redirect_root_logger()

                # logger.info("Resetting scene {} replay cursor.")
                # _reset_replay_cursors(self._local_db_path, 0)
                os.environ.update(env)

                # we don't import from ops because we need some extra return statements.
                # see https://github.com/canonical/operator/pull/862
                # from ops.main import main
                from scenario.ops_main_mock import main

                logger.info(" - Entering ops.main (mocked).")

                try:
                    charm, event = main(
                        self._wrap(self._charm_type),
                        pre_event=pre_event,
                        post_event=post_event,
                    )
                except Exception as e:
                    raise RuntimeError(
                        f"Uncaught error in operator/charm code: {e}."
                    ) from e
                finally:
                    logger.info(" - Exited ops.main.")

                logger.info(" - clearing env")
                self._cleanup_env(env)

                with event_db(db_path) as data:
                    scene_out = data.scenes[0]

        return RuntimeRunResult(charm, scene_out, event)

    def replay(
        self,
        index: int,
        pre_event: Optional[Callable[["_CT"], None]] = None,
        post_event: Optional[Callable[["_CT"], None]] = None,
    ) -> RuntimeRunResult:
        """Replays a stored scene by index.

        This requires having a statically defined event DB.
        """
        if not Runtime._is_installed():
            raise RuntimeError(
                "Runtime is not installed. Call `runtime.install()` (and read the fine prints)."
            )
        if not self._event_db_path:
            raise ValueError(
                "No event_db_path set. Pass one to the Runtime constructor."
            )

        logger.info(f"Preparing to fire scene #{index} on {self._charm_type.__name__}")
        logger.info(" - redirecting root logging")
        self._redirect_root_logger()

        logger.info(" - setting up temporary charm root")
        with tempfile.TemporaryDirectory() as charm_root:
            charm_root_path = Path(charm_root).absolute()
            self._drop_meta(charm_root_path)

            # extract the env from the scene
            with event_db(self._event_db_path) as data:
                logger.info(
                    f" - resetting scene {index} replay cursor."
                )  # just in case
                _reset_replay_cursors(self._event_db_path, index)

                logger.info(" - preparing env")
                scene = data.scenes[index]
                env = dict(scene.event.env)
                # declare the charm root for ops to pick up
                env["JUJU_CHARM_DIR"] = str(charm_root_path)

            # inject the memo envvars
            env.update(
                self._get_runtime_env(
                    index,
                    self._event_db_path,
                    # set memo to isolated mode so that we raise
                    # instead of propagating: it'd be useless
                    # anyway in most cases TODO generalize?
                    mode="isolated",
                )
            )
            os.environ.update(env)

            # we don't import from ops because we need some extra return statements.
            # see https://github.com/canonical/operator/pull/862
            # from ops.main import main
            from scenario.ops_main_mock import main

            logger.info(" - Entering ops.main (mocked).")

            try:
                charm, event = main(
                    self._wrap(self._charm_type),
                    pre_event=pre_event,
                    post_event=post_event,
                )
            except Exception as e:
                raise RuntimeError(
                    f"Uncaught error in operator/charm code: {e}."
                ) from e
            finally:
                logger.info(" - Exited ops.main.")

            logger.info(" - cleaning up env")
            self._cleanup_env(env)

        return RuntimeRunResult(charm, scene, event)


if __name__ == "__main__":
    # install Runtime **in your current venv** so that all
    # relevant pebble.Client | model._ModelBackend juju/container-facing calls are
    # @memo-decorated and can be used in "replay" mode to reproduce a remote run.
    Runtime.install(force=False)
