import dataclasses
import inspect
import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional, Type, TypeVar

import yaml

from scenario.logger import logger as scenario_logger
from scenario.mocking import patch_module, DecorateSpec

if TYPE_CHECKING:
    from ops.charm import CharmBase
    from ops.framework import EventBase
    from ops.testing import CharmType

    from scenario.structs import CharmSpec, Scene, State

    _CT = TypeVar("_CT", bound=Type[CharmType])

logger = scenario_logger.getChild("runtime")

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
    ):
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

    @contextmanager
    def patching(self, scene: "Scene"):
        """Install the runtime: patch all required backend calls.
        """

        # copy input state to act as blueprint for output state
        logger.info(f"Installing {self}... ")
        from ops import pebble
        logger.info("patching ops.pebble")
        pebble_decorator_specs = {
            "Client": {
                # todo: we could be more fine-grained and decorate individual Container methods,
                #  e.g. can_connect, ... just like in _ModelBackend we don't just memo `_run`.
                "_request": DecorateSpec(),
                # some methods such as pebble.pull use _request_raw directly,
                # and deal in objects that cannot be json-serialized
                "pull": DecorateSpec(),
                "push": DecorateSpec(),
            }
        }
        patch_module(pebble, decorate=pebble_decorator_specs,
                     scene=scene)

        from ops import model
        logger.info("patching ops.model")
        model_decorator_specs = {
            "_ModelBackend": {
                "relation_get": DecorateSpec(),
                "relation_set": DecorateSpec(),
                "is_leader": DecorateSpec(),
                "application_version_set": DecorateSpec(),
                "status_get": DecorateSpec(),
                "action_get": DecorateSpec(),
                "add_metrics": DecorateSpec(),  # deprecated, I guess
                "action_set": DecorateSpec(),
                "action_fail": DecorateSpec(),
                "action_log": DecorateSpec(),
                "relation_ids": DecorateSpec(),
                "relation_list": DecorateSpec(),
                "relation_remote_app_name": DecorateSpec(),
                "config_get": DecorateSpec(),
                "resource_get": DecorateSpec(),
                "storage_list": DecorateSpec(),
                "storage_get": DecorateSpec(),
                "network_get": DecorateSpec(),
                "status_set": DecorateSpec(),
                "storage_add": DecorateSpec(),
                "juju_log": DecorateSpec(),
                "planned_units": DecorateSpec(),

                # todo different ops version support?
                # "secret_get": DecorateSpec(),
                # "secret_set": DecorateSpec(),
                # "secret_grant": DecorateSpec(),
                # "secret_remove": DecorateSpec(),
            }
        }
        patch_module(model, decorate=model_decorator_specs,
                     scene=scene)

        yield

    @staticmethod
    def _redirect_root_logger():
        # the root logger set up by ops calls a hook tool: `juju-log`.
        # that is a problem for us because `juju-log` is itself memoized, which leads to recursion.
        def _patch_logger(*args, **kwargs):
            logger.debug("Hijacked root logger.")
            pass

        from scenario import ops_main_mock
        ops_main_mock.setup_root_logging = _patch_logger

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

    def _get_event_env(self, scene: "Scene", charm_root: Path):
        env = {
            "JUJU_VERSION": self._juju_version,
            "JUJU_UNIT_NAME": self.unit_name,
            "_": "./dispatch",
            "JUJU_DISPATCH_PATH": f"hooks/{scene.event.name}",
            "JUJU_MODEL_NAME": scene.state.model.name,
            "JUJU_MODEL_UUID": scene.state.model.uuid,
            "JUJU_CHARM_DIR": str(charm_root.absolute())
            # todo consider setting pwd, (python)path
        }

        if scene.event.meta and scene.event.meta.relation:
            relation = scene.event.meta.relation
            env.update(
                {
                    "JUJU_RELATION": relation.endpoint,
                    "JUJU_RELATION_ID": str(relation.relation_id),
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
            (temppath / 'metadata.yaml').write_text(yaml.safe_dump(spec.meta))
            (temppath / 'config.yaml').write_text(yaml.safe_dump(spec.config or {}))
            (temppath / 'actions.yaml').write_text(yaml.safe_dump(spec.actions or {}))
            yield temppath

    def play(
            self,
            scene: "Scene",
            pre_event: Optional[Callable[["CharmType"], None]] = None,
            post_event: Optional[Callable[["CharmType"], None]] = None,
    ) -> 'State':
        """Plays a scene on the charm.

        This will set the environment up and call ops.main.main().
        After that it's up to ops.
        """
        logger.info(
            f"Preparing to fire {scene.event.name} on {self._charm_type.__name__}"
        )

        # we make a copy to avoid mutating the input scene
        scene = scene.copy()

        logger.info(" - generating virtual charm root")
        with self.virtual_charm_root() as temporary_charm_root:
            with self.patching(scene):
                # todo consider forking out a real subprocess and do the mocking by
                #  generating hook tool callables

                logger.info(" - redirecting root logging")
                self._redirect_root_logger()

                logger.info(" - preparing env")
                env = self._get_event_env(scene,
                                          charm_root=temporary_charm_root)
                os.environ.update(env)

                logger.info(" - Entering ops.main (mocked).")
                # we don't import from ops.main because we need some extras, such as the pre/post_event hooks
                from scenario.ops_main_mock import main as mocked_main
                try:
                    mocked_main(
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

            logger.info('event fired; done.')
            return scene.state
