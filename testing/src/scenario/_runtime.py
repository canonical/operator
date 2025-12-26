# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Test framework runtime."""

from __future__ import annotations

import copy
import dataclasses
import os
import tempfile
import typing
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from ops import JujuContext, pebble
from ops._main import _Abort
from ops._private.harness import ActionFailed

from .errors import NoObserverError, UncaughtCharmError
from .logger import logger as scenario_logger
from .state import (
    PeerRelation,
    Relation,
    SubordinateRelation,
)

if TYPE_CHECKING:  # pragma: no cover
    from .context import Context
    from .state import CharmType, State, _CharmSpec, _Event

logger = scenario_logger.getChild('runtime')

RUNTIME_MODULE = Path(__file__).parent


class Runtime:
    """Charm runtime wrapper.

    This object bridges a local environment and a charm artifact.
    """

    def __init__(
        self,
        app_name: str,
        charm_spec: _CharmSpec[CharmType],
        charm_root: str | Path | None = None,
        juju_version: str = '3.0.0',
        unit_id: int | None = 0,
        machine_id: str | None = None,
        availability_zone: str | None = None,
        principal_unit: str | None = None,
    ):
        self._charm_spec = charm_spec
        self._juju_version = juju_version
        self._charm_root = charm_root

        self._app_name = app_name
        self._unit_id = unit_id
        self._machine_id = machine_id
        self._availability_zone = availability_zone
        self._principal_unit = principal_unit

    def _get_event_env(self, state: State, event: _Event, charm_root: Path):
        """Build the simulated environment the operator framework expects."""
        env = {
            'JUJU_VERSION': self._juju_version,
            'JUJU_UNIT_NAME': f'{self._app_name}/{self._unit_id}',
            '_': './dispatch',
            'JUJU_DISPATCH_PATH': f'hooks/{event._juju_name}',
            'JUJU_HOOK_NAME': '' if event._is_action_event else event._juju_name,
            'JUJU_MODEL_NAME': state.model.name,
            'JUJU_MODEL_UUID': state.model.uuid,
            'JUJU_CHARM_DIR': str(charm_root.absolute()),
        }

        if self._machine_id is not None:
            env['JUJU_MACHINE_ID'] = self._machine_id

        if self._availability_zone is not None:
            env['JUJU_AVAILABILITY_ZONE'] = self._availability_zone

        if self._principal_unit is not None:
            env['JUJU_PRINCIPAL_UNIT'] = self._principal_unit

        if event._is_action_event and (action := event.action):
            env.update(
                {
                    'JUJU_ACTION_NAME': action.name.replace('_', '-'),
                    'JUJU_ACTION_UUID': action.id,
                },
            )

        if event._is_relation_event and (relation := event.relation):
            if isinstance(relation, PeerRelation):
                remote_app_name = self._app_name
            elif isinstance(relation, (Relation, SubordinateRelation)):
                remote_app_name = relation.remote_app_name
            else:
                raise ValueError(f'Unknown relation type: {relation}')
            env.update(
                {
                    'JUJU_RELATION': relation.endpoint,
                    'JUJU_RELATION_ID': str(relation.id),
                    'JUJU_REMOTE_APP': remote_app_name,
                },
            )

            remote_unit_id = event.relation_remote_unit_id

            # don't check truthiness because remote_unit_id could be 0
            if remote_unit_id is None and not event.name.endswith(
                ('_relation_created', 'relation_broken'),
            ):
                remote_unit_ids = relation._remote_unit_ids

                if len(remote_unit_ids) == 1:
                    remote_unit_id = remote_unit_ids[0]
                    logger.info(
                        "there's only one remote unit, so we set JUJU_REMOTE_UNIT to it, "
                        'but you probably should be parametrizing the event with `remote_unit_id` '
                        'to be explicit.',
                    )
                elif len(remote_unit_ids) > 1:
                    remote_unit_id = remote_unit_ids[0]
                    logger.warning(
                        'remote unit ID unset, and multiple remote unit IDs are present; '
                        'We will pick the first one and hope for the best. You should be passing '
                        '`remote_unit_id` to the Event constructor.',
                    )
                else:
                    logger.warning(
                        'remote unit ID unset; no remote unit data present. '
                        'Is this a realistic scenario?',
                    )

            if remote_unit_id is not None:
                remote_unit = f'{remote_app_name}/{remote_unit_id}'
                env['JUJU_REMOTE_UNIT'] = remote_unit
                if event.name.endswith('_relation_departed'):
                    if event.relation_departed_unit_id:
                        env['JUJU_DEPARTING_UNIT'] = (
                            f'{remote_app_name}/{event.relation_departed_unit_id}'
                        )
                    else:
                        env['JUJU_DEPARTING_UNIT'] = remote_unit

        if container := event.container:
            env.update({'JUJU_WORKLOAD_NAME': container.name})

        if notice := event.notice:
            if hasattr(notice.type, 'value'):
                notice_type = typing.cast('pebble.NoticeType', notice.type).value
            else:
                notice_type = str(notice.type)
            env.update(
                {
                    'JUJU_NOTICE_ID': notice.id,
                    'JUJU_NOTICE_TYPE': notice_type,
                    'JUJU_NOTICE_KEY': notice.key,
                },
            )

        if check_info := event.check_info:
            env['JUJU_PEBBLE_CHECK_NAME'] = check_info.name

        if storage := event.storage:
            env.update({'JUJU_STORAGE_ID': f'{storage.name}/{storage.index}'})

        if secret := event.secret:
            env.update(
                {
                    'JUJU_SECRET_ID': secret.id,
                    'JUJU_SECRET_LABEL': secret.label or '',
                },
            )
            # Don't check truthiness because revision could be 0.
            if event.secret_revision is not None:
                env['JUJU_SECRET_REVISION'] = str(event.secret_revision)

        return env

    @staticmethod
    def _wrap(charm_type: type[CharmType]) -> type[CharmType]:
        # dark sorcery to work around framework using class attrs to hold on to event sources
        # this should only be needed if we call play multiple times on the same runtime.
        class WrappedEvents(charm_type.on.__class__):
            """The charm's event sources, but wrapped."""

        WrappedEvents.__name__ = charm_type.on.__class__.__name__
        WrappedEvents.__qualname__ = charm_type.on.__class__.__qualname__
        WrappedEvents.__module__ = charm_type.on.__class__.__module__

        class WrappedCharm(charm_type):
            """The test charm's type, but with events wrapped."""

            on = WrappedEvents()

        WrappedCharm.__name__ = charm_type.__name__
        WrappedCharm.__qualname__ = charm_type.__qualname__
        WrappedCharm.__module__ = charm_type.__module__
        return typing.cast('type[CharmType]', WrappedCharm)

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

        metadata_yaml = virtual_charm_root / 'metadata.yaml'
        config_yaml = virtual_charm_root / 'config.yaml'
        actions_yaml = virtual_charm_root / 'actions.yaml'

        metadata_files_present: dict[Path, str | None] = {
            file: file.read_text() if charm_virtual_root_is_custom and file.exists() else None
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
                    f'metadata files found in custom charm_root {charm_virtual_root}. '
                    f'The spec was autoloaded so the contents should be identical. '
                    f'Proceeding...',
                )

        elif not spec.is_autoloaded and any_metadata_files_present_in_charm_virtual_root:
            logger.warning(
                f'Some metadata files found in custom user-provided charm_root '
                f'{charm_virtual_root} while you have passed meta, config or actions to '
                f'Context.run(). '
                'Single source of truth are the arguments passed to Context.run(). '
                'charm_root metadata files will be overwritten for the '
                'duration of this test, and restored afterwards. '
                'To avoid this, clean any metadata files from the charm_root before calling run.',
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
            typing.cast('tempfile.TemporaryDirectory', charm_virtual_root).cleanup()  # type: ignore

    @contextmanager
    def exec(
        self,
        state: State,
        event: _Event,
        context: Context,
    ):
        """Runs an event with this state as initial state on a charm.

        Returns the 'output state', that is, the state as mutated by the charm during the
        event handling.

        This will set the environment up and call ops.main().
        After that it's up to Ops.
        """
        from ._consistency_checker import check_consistency  # avoid cycles

        check_consistency(state, event, self._charm_spec, self._juju_version, self._unit_id)

        charm_type = self._charm_spec.charm_type
        logger.info(f'Preparing to fire {event.name} on {charm_type.__name__}')

        # we make a copy to avoid mutating the input state
        output_state = copy.deepcopy(state)

        logger.info(' - generating virtual charm root')
        with self._virtual_charm_root() as temporary_charm_root:
            logger.info(' - preparing env')
            env = self._get_event_env(
                state=state,
                event=event,
                charm_root=temporary_charm_root,
            )
            juju_context = JujuContext.from_environ(env)
            # We need to set JUJU_VERSION in os.environ, because charms may use
            # `JujuVersion.from_environ()` to get the (simulated) Juju version.
            # For consistency, we put all the other ones there too, although we'd
            # like to change this in the future.
            previous_env = os.environ.copy()
            os.environ.update(env)

            logger.info(' - entering ops.main (mocked)')
            from ._ops_main_mock import Ops

            ops = None

            try:
                ops = Ops(
                    state=output_state,
                    event=event,
                    context=context,
                    charm_spec=dataclasses.replace(
                        self._charm_spec,
                        charm_type=self._wrap(charm_type),
                    ),
                    juju_context=juju_context,
                )

                try:
                    yield ops
                except _Abort as e:
                    # If ops raised _Abort(0) within the charm code then we want to treat that as
                    # normal completion.
                    if e.exit_code != 0:
                        raise

            except (NoObserverError, ActionFailed):
                raise  # propagate along
            except Exception as e:
                bare = os.getenv('SCENARIO_BARE_CHARM_ERRORS', 'false')
                if bare.lower() == 'true' or (bare.isdigit() and int(bare)):
                    raise
                # The following is intentionally on one long line, so that the last line of pdb
                # output shows the error message (pdb shows the "raise" line).
                raise UncaughtCharmError(f'Uncaught {type(e).__name__} in charm, try "exceptions [n]" if using pdb on Python 3.13+. Details: {e!r}') from e  # fmt: skip  # noqa: E501

            finally:
                if ops:
                    ops.destroy()
                    context.trace_data.extend(ops.trace_data)
                for key in tuple(os.environ):
                    if key not in previous_env:
                        del os.environ[key]
                os.environ.update(previous_env)
                logger.info(' - exited ops.main')

        logger.info('event dispatched. done.')
        context._set_output_state(ops.state)
