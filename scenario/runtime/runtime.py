import dataclasses
import os
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Type

import yaml

from logger import logger as pkg_logger
from scenario.event_db import TemporaryEventDB
from scenario.runtime.memo import (
    MEMO_DATABASE_NAME_KEY,
    MEMO_MODE_KEY,
    MEMO_REPLAY_INDEX_KEY,
    USE_STATE_KEY,
)
from scenario.runtime.memo import Event as MemoEvent
from scenario.runtime.memo import Scene as MemoScene
from scenario.runtime.memo import event_db
from scenario.runtime.memo_tools import DECORATE_MODEL, DECORATE_PEBBLE, inject_memoizer

if TYPE_CHECKING:
    from ops.charm import CharmBase
    from ops.framework import EventBase
    from ops.testing import CharmType
    from ops.charm import CharmBase
    from ops.framework import EventBase
    from scenario.structs import CharmSpec, Scene

logger = pkg_logger.getChild("runtime")

RUNTIME_MODULE = Path(__file__).parent
logger = logger.getChild("event_recorder.runtime")


@dataclasses.dataclass
class RuntimeRunResult:
    charm: "CharmBase"
    scene: "Scene"
    event: "EventBase"


class Runtime:
    """Charm runtime wrapper.

    This object bridges a local environment and a charm artifact.
    """

    def __init__(self, charm_spec: "CharmSpec", juju_version: str = "3.0.0"):
        self._charm_spec = charm_spec
        self._juju_version = juju_version
        self._charm_type = charm_spec.charm_type
        # todo consider cleaning up venv on __delete__, but ideally you should be
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
        return Runtime(my_charm_type)

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
        from ops import model

        model_path = Path(model.__file__)

        if "from memo import memo" not in model_path.read_text():
            logger.error(
                f"ops.model ({model_path} does not seem to import runtime.memo.memo"
            )
            return False

        try:
            import memo
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

        import ops.main

        ops.main.setup_root_logging = _patch_logger

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
        return {
            "JUJU_VERSION": self._juju_version,
            "JUJU_UNIT_NAME": self.unit_name,
            "_": "./dispatch",
            "JUJU_DISPATCH_PATH": f"hooks/{scene.event.name}",
            "JUJU_MODEL_NAME": scene.context.state.model.name,
            "JUJU_MODEL_UUID": scene.context.state.model.uuid,
            "JUJU_CHARM_DIR": str(charm_root.absolute())
            # todo consider setting pwd, (python)path
        }

    def _drop_meta(self, charm_root: Path):
        logger.debug("Dropping metadata.yaml and actions.yaml...")
        (charm_root / "metadata.yaml").write_text(yaml.safe_dump(self._charm_spec.meta))
        if self._charm_spec.actions:
            (charm_root / "actions.yaml").write_text(
                yaml.safe_dump(self._charm_spec.actions)
            )
        if self._charm_spec.config:
            (charm_root / "config.yaml").write_text(
                yaml.safe_dump(self._charm_spec.config)
            )

    def _get_runtime_env(self, scene_idx: int, db_path: Path):
        env = {}
        env.update(
            {
                USE_STATE_KEY: "1",
                MEMO_REPLAY_INDEX_KEY: str(scene_idx),
                MEMO_DATABASE_NAME_KEY: str(db_path),
            }
        )
        sys.path.append(str(RUNTIME_MODULE.absolute()))
        env[MEMO_MODE_KEY] = "replay"

        os.environ.update(env)  # todo consider subprocess
        return env

    def _scene_to_memo_scene(self, scene: "Scene", env: dict) -> MemoScene:
        """Convert scenario.structs.Scene to Memo.Scene."""
        return MemoScene(event=MemoEvent(env=env), context=scene.context)

    def run(self, scene: "Scene") -> RuntimeRunResult:
        """Executes a scene on the charm.

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

        logger.info(" - clearing env")

        logger.info(" - preparing env")
        with tempfile.TemporaryDirectory() as charm_root:
            charm_root_path = Path(charm_root)
            env = self._get_event_env(scene, charm_root_path)

            memo_scene = self._scene_to_memo_scene(scene, env)
            with TemporaryEventDB(memo_scene, charm_root) as db_path:
                self._drop_meta(charm_root_path)
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
                    charm, event = main(self._charm_type)
                except Exception as e:
                    raise RuntimeError(
                        f"Uncaught error in operator/charm code: {e}."
                    ) from e
                finally:
                    logger.info(" - Exited ops.main.")

                self._cleanup_env(env)

                with event_db(db_path) as data:
                    scene_out = data.scenes[0]

        return RuntimeRunResult(charm, scene_out, event)


if __name__ == "__main__":
    # install Runtime **in your current venv** so that all
    # relevant pebble.Client | model._ModelBackend juju/container-facing calls are
    # @memo-decorated and can be used in "replay" mode to reproduce a remote run.
    Runtime.install(force=False)

    # IRL one would probably manually @memo the annoying ksp calls.
    def _patch_traefik_charm(charm: Type["CharmType"]):
        from charms.observability_libs.v0 import kubernetes_service_patch  # noqa

        def _do_nothing(*args, **kwargs):
            print("KubernetesServicePatch call skipped")

        def _null_evt_handler(self, event):
            print(f"event {event} received and skipped")

        kubernetes_service_patch.KubernetesServicePatch._service_object = _do_nothing
        kubernetes_service_patch.KubernetesServicePatch._patch = _null_evt_handler
        return charm

    # here's the magic:
    # this env grabs the event db from the "trfk/0" unit (assuming the unit is available
    # in the currently switched-to juju model/controller).
    runtime = Runtime.from_local_file(
        local_charm_src=Path("/home/pietro/canonical/traefik-k8s-operator"),
        charm_cls_name="TraefikIngressCharm",
    )
    # then it will grab the TraefikIngressCharm from that local path and simulate the whole
    # remote runtime env by calling `ops.main.main()` on it.
    # this tells the runtime which event to replay. Right now, #X of the
    # `jhack replay list trfk/0` queue. Switch it to whatever number you like to
    # locally replay that event.
    runtime._charm_type = _patch_traefik_charm(runtime._charm_type)
    runtime.run(2)
