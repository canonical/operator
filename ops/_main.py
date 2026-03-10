# Copyright 2019 Canonical Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Implement the main entry point to the framework."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import warnings
from pathlib import Path
from typing import Any, cast

import opentelemetry.trace

from . import charm as _charm
from . import framework as _framework
from . import model as _model
from . import storage as _storage
from ._private import tracer
from .jujucontext import JujuContext
from .log import setup_root_logging
from .version import version

CHARM_STATE_FILE = '.unit-state.db'

logger = logging.getLogger()


def _exe_path(path: Path) -> Path | None:
    """Find and return the full path to the given binary.

    Here path is the absolute path to a binary, but might be missing an extension.
    """
    p = shutil.which(path.name, mode=os.F_OK, path=str(path.parent))
    if p is None:
        return None
    return Path(p)


def _get_event_args(
    charm: _charm.CharmBase,
    bound_event: _framework.BoundEvent,
    juju_context: JujuContext,
) -> tuple[list[Any], dict[str, Any]]:
    event_type = bound_event.event_type
    model = charm.framework.model

    relation = None
    if issubclass(event_type, _charm.WorkloadEvent):
        workload_name = juju_context.workload_name
        assert workload_name is not None
        container = model.unit.get_container(workload_name)
        args: list[Any] = [container]
        if issubclass(event_type, _charm.PebbleNoticeEvent):
            notice_id = juju_context.notice_id
            notice_type = juju_context.notice_type
            notice_key = juju_context.notice_key
            args.extend([notice_id, notice_type, notice_key])
        elif issubclass(event_type, _charm.PebbleCheckEvent):
            check_name = juju_context.pebble_check_name
            args.append(check_name)
        return args, {}
    elif issubclass(event_type, _charm.SecretEvent):
        args: list[Any] = [
            juju_context.secret_id,
            juju_context.secret_label,
        ]
        if issubclass(event_type, (_charm.SecretRemoveEvent, _charm.SecretExpiredEvent)):
            args.append(juju_context.secret_revision)
        return args, {}
    elif issubclass(event_type, _charm.StorageEvent):
        # Before JUJU_STORAGE_ID exists, take the event name as
        # <storage_name>_storage_<attached|detached> and replace it with <storage_name>
        storage_name = juju_context.storage_name or '-'.join(
            bound_event.event_kind.split('_')[:-2]
        )
        storage_index = juju_context.storage_index

        storages = model.storages[storage_name]
        storage_location = model._backend.storage_get(
            f'{storage_name}/{storage_index}', 'location'
        )
        if len(storages) == 1:
            storage = storages[0]
        else:
            # If there's more than one value, pick the right one. We'll realize the key on lookup
            storage = next((s for s in storages if s.index == storage_index), None)
        storage = cast('_storage.JujuStorage | _storage.SQLiteStorage', storage)
        storage.location = storage_location  # type: ignore
        return [storage], {}
    elif issubclass(event_type, _charm.ActionEvent):
        args: list[Any] = [juju_context.action_uuid]
        return args, {}
    elif issubclass(event_type, _charm.RelationEvent):
        relation_name = juju_context.relation_name
        assert relation_name is not None
        relation_id = juju_context.relation_id
        relation: _model.Relation | None = model.get_relation(relation_name, relation_id)

    remote_app_name = juju_context.remote_app_name
    remote_unit_name = juju_context.remote_unit_name
    departing_unit_name = juju_context.relation_departing_unit_name

    if not remote_app_name and remote_unit_name:
        if '/' not in remote_unit_name:
            raise RuntimeError(f'invalid remote unit name: {remote_unit_name}')
        remote_app_name = remote_unit_name.split('/')[0]

    kwargs: dict[str, Any] = {}
    if remote_app_name:
        kwargs['app'] = model.get_app(remote_app_name)
    if remote_unit_name:
        kwargs['unit'] = model.get_unit(remote_unit_name)
    if departing_unit_name:
        kwargs['departing_unit_name'] = departing_unit_name

    if relation:
        return [relation], kwargs
    return [], kwargs


class _Dispatcher:
    """Encapsulate how to figure out what event Juju wants us to run.

    Juju 2.7.0 and later provide the JUJU_DISPATCH_PATH environment variable.
    Earlier versions called individual hook scripts, and that are supported via
    two separate mechanisms:
    - Charmcraft 0.1.2 and produce `dispatch` shell script that fills this
      environment variable if it's missing
    - Ops 0.8.0 and later likewise take use ``sys.argv[0]`` if the environment
      variable is missing

    Args:
        charm_dir: the toplevel directory of the charm

    Attributes:
        event_name: the name of the event to run

    """

    event_name: str

    def __init__(self, charm_dir: Path, juju_context: JujuContext):
        self._juju_context = juju_context
        self._charm_dir = charm_dir
        self._exec_path = Path(self._juju_context.dispatch_path or sys.argv[0])

        # Grab the correct hook from JUJU_DISPATCH_PATH, e.g. hooks/install.
        self._dispatch_path = Path(self._juju_context.dispatch_path)

        if 'OPERATOR_DISPATCH' in os.environ:
            logger.debug('Charm called itself via %s.', self._dispatch_path)
            raise _Abort(0)
        os.environ['OPERATOR_DISPATCH'] = '1'

        self._set_name_from_path(self._dispatch_path)

    def run_any_legacy_hook(self):
        """Run any extant legacy hook.

        If there is a legacy hook for the current event, run it.
        """
        dispatch_path = _exe_path(self._charm_dir / self._dispatch_path)
        if dispatch_path is None:
            return  # There is no legacy hook.

        warnings.warn('Legacy hooks are deprecated.', category=DeprecationWarning)

        # super strange that there isn't an is_executable
        if not os.access(str(dispatch_path), os.X_OK):
            logger.warning('Legacy %s exists but is not executable.', self._dispatch_path)
            return

        if dispatch_path.resolve() == Path(sys.argv[0]).resolve():
            logger.debug('Legacy %s is just a link to ourselves.', self._dispatch_path)
            return

        argv = sys.argv.copy()
        argv[0] = str(dispatch_path)
        logger.info('Running legacy %s.', self._dispatch_path)
        try:
            subprocess.run(argv, check=True)
        except subprocess.CalledProcessError as e:
            logger.warning('Legacy %s exited with status %d.', self._dispatch_path, e.returncode)
            raise _Abort(e.returncode) from e
        except OSError as e:
            logger.warning('Unable to run legacy %s: %s', self._dispatch_path, e)
            raise _Abort(1) from e
        else:
            logger.debug('Legacy %s exited with status 0.', self._dispatch_path)

    def _set_name_from_path(self, path: Path):
        """Sets the name attribute to that which can be inferred from the given path."""
        name = path.name.replace('-', '_')
        if path.parent.name == 'actions':
            name = f'{name}_action'
        self.event_name = name

    def is_restricted_context(self):
        """Return ``True`` if we are running in a restricted Juju context.

        When in a restricted context, most commands (relation-get, config-get,
        state-get) are not available. As such, we change how we interact with
        Juju.
        """
        return self.event_name in ('collect_metrics', 'meter_status_changed')


def _should_use_controller_storage(
    db_path: Path, meta: _charm.CharmMeta, juju_context: JujuContext
) -> bool:
    """Figure out whether we want to use controller storage or not."""
    # if local state has been used previously, carry on using that
    if db_path.exists():
        return False

    # only use controller storage for Kubernetes podspec charms
    is_podspec = 'kubernetes' in meta.series
    if not is_podspec:
        logger.debug('Using local storage: not a Kubernetes podspec charm')
        return False

    # are we in a new enough Juju?
    if juju_context.version.has_controller_storage():
        logger.debug('Using controller storage: JUJU_VERSION=%s', juju_context.version)
        return True
    else:
        logger.debug('Using local storage: JUJU_VERSION=%s', juju_context.version)
        return False


class _Abort(Exception):  # noqa: N818
    """Raised when something happens that should interrupt ops execution."""

    def __init__(self, exit_code: int):
        super().__init__()
        self.exit_code = exit_code


class _Manager:
    """Initialises the Framework and manages the lifecycle of a charm.

    Running _Manager consists of three main steps:
    - setup: initialise the following from JUJU_* environment variables:
      - the Framework (hook command wrappers)
      - the storage backend
      - the event that Juju is emitting on us
      - the charm instance (user-facing)
    - emit: core user-facing lifecycle step. Consists of:
      - re-emit any deferred events found in the storage
      - emit the Juju event to the charm
        - emit any custom events emitted by the charm during this phase
      - emit  the ``collect-status`` events
    - commit: responsible for:
      - store any events deferred throughout this execution
      - graceful teardown of the storage
    """

    _framework_class = _framework.Framework

    def __init__(
        self,
        charm_class: type[_charm.CharmBase],
        model_backend: _model._ModelBackend | None = None,
        use_juju_for_storage: bool | None = None,
        charm_state_path: str = CHARM_STATE_FILE,
        juju_context: JujuContext | None = None,
    ):
        from . import tracing  # break circular import

        if juju_context is None:
            juju_context = JujuContext._from_dict(os.environ)

        try:
            name = charm_class.__name__
        except AttributeError:
            name = str(charm_class)

        self._juju_context = juju_context
        if tracing:
            tracing._setup(juju_context, name)
        self._tracing_context = tracer.start_as_current_span('ops.main')
        self._tracing_context.__enter__()
        self._charm_state_path = charm_state_path
        self._charm_class = charm_class
        if model_backend is None:
            model_backend = _model._ModelBackend(juju_context=self._juju_context)
        self._model_backend = model_backend

        # Do this as early as possible to be sure to catch the most logs.
        self._setup_root_logging()

        self._charm_root = self._juju_context.charm_dir
        self._charm_meta = self._load_charm_meta()
        self._use_juju_for_storage = use_juju_for_storage

        # Set up dispatcher, framework and charm objects.
        self.dispatcher = _Dispatcher(self._charm_root, self._juju_context)
        self.dispatcher.run_any_legacy_hook()

        self.framework = self._make_framework(self.dispatcher)
        with self.framework._event_context('__init__'):
            self.charm = self._charm_class(self.framework)

    def _load_charm_meta(self):
        return _charm.CharmMeta.from_charm_root(self._charm_root)

    def _setup_root_logging(self):
        # For actions, there is a communication channel with the user running the
        # action, so we want to send exception details through stderr, rather than
        # only to juju-log as normal.
        handling_action = self._juju_context.action_name is not None
        setup_root_logging(
            self._model_backend, debug=self._juju_context.debug, exc_stderr=handling_action
        )

        logger.debug('ops %s up and running.', version)

    def _make_storage(self, dispatcher: _Dispatcher):
        charm_state_path = self._charm_root / self._charm_state_path

        use_juju_for_storage = self._use_juju_for_storage
        if use_juju_for_storage and not _storage.juju_backend_available():
            # raise an exception; the charm is broken and needs fixing.
            msg = 'charm set use_juju_for_storage=True, but Juju version {} does not support it'
            raise RuntimeError(msg.format(self._juju_context.version))

        if use_juju_for_storage is None:
            use_juju_for_storage = _should_use_controller_storage(
                charm_state_path, self._charm_meta, self._juju_context
            )
        elif use_juju_for_storage:
            warnings.warn(
                "Controller storage is deprecated; it's intended for "
                'podspec charms and will be removed in a future release.',
                category=DeprecationWarning,
            )

        if use_juju_for_storage and dispatcher.is_restricted_context():
            # TODO: jam 2020-06-30 This unconditionally avoids running a collect metrics event
            #  Though we eventually expect that Juju will run collect-metrics in a
            #  non-restricted context. Once we can determine that we are running
            #  collect-metrics in a non-restricted context, we should fire the event as normal.
            logger.debug(
                '"%s" is not supported when using Juju for storage\n'
                'see: https://github.com/canonical/operator/issues/348',
                dispatcher.event_name,
            )
            # Note that we don't exit nonzero, because that would cause Juju to rerun the hook
            raise _Abort(0)

        if self._use_juju_for_storage:
            store = _storage.JujuStorage()
        else:
            store = _storage.SQLiteStorage(charm_state_path)
        return store

    def _make_framework(self, dispatcher: _Dispatcher):
        # If we are in a RelationBroken event, we want to know which relation is
        # broken within the model, not only in the event's `.relation` attribute.
        if dispatcher.event_name.endswith('_relation_broken'):
            broken_relation_id = self._juju_context.relation_id
        else:
            broken_relation_id = None

        # In a RelationDeparted event, the unit is not included in the Juju
        # `relation-list` output, but the charm still has access to the remote
        # relation data. To provide the charm with a mechanism for getting
        # access to that data, we include the remote unit in Relation.units.
        # We also expect it to be available in RelationBroken events, so ensure
        # that it's available then as well. For other relation events, the unit
        # will either already be in the set via `relation-list` (such as in a
        # RelationChanged event) or correctly not in the list yet because the
        # relation has not been fully set up (such as in a RelationJoined event).
        if dispatcher.event_name.endswith(('_relation_departed', '_relation_broken')):
            remote_unit_name = self._juju_context.remote_unit_name
        else:
            remote_unit_name = None

        model = _model.Model(
            self._charm_meta,
            self._model_backend,
            broken_relation_id=broken_relation_id,
            remote_unit_name=remote_unit_name,
        )
        store = self._make_storage(dispatcher)
        framework = self._framework_class(
            store,
            self._charm_root,
            self._charm_meta,
            model,
            event_name=dispatcher.event_name,
            juju_debug_at=self._juju_context.debug_at,
        )
        framework.set_breakpointhook()
        return framework

    def _emit(self):
        """Emit the event on the charm."""
        # TODO: Remove the collect_metrics check below as soon as the relevant
        #       Juju changes are made. Also adjust the docstring on
        #       EventBase.defer().
        #
        # Skip reemission of deferred events for collect-metrics events because
        # they do not have the full access to all hook commands.
        if not self.dispatcher.is_restricted_context():
            # Re-emit any deferred events from the previous run.
            self.framework.reemit()

        # Emit the Juju event.
        self._emit_charm_event(self.dispatcher.event_name)
        # Emit collect-status events. In a restricted context, we can't run
        # is-leader, so can't do the full evaluation. Skip it rather than
        # only running the unit status.
        if not self.dispatcher.is_restricted_context():
            _charm._evaluate_status(self.charm)

    def _get_event_to_emit(self, event_name: str) -> _framework.BoundEvent | None:
        try:
            return getattr(self.charm.on, event_name)
        except AttributeError:
            logger.debug('Event %s not defined for %s.', event_name, self.charm)
        return None

    def _get_event_args(
        self, bound_event: _framework.BoundEvent
    ) -> tuple[list[Any], dict[str, Any]]:
        # A wrapper so that the testing subclasses can easily override the
        # behaviour.
        return _get_event_args(self.charm, bound_event, self._juju_context)

    def _emit_charm_event(self, event_name: str):
        """Emits a charm event based on a Juju event name.

        Args:
            charm: A charm instance to emit an event from.
            event_name: A Juju event name to emit on a charm.
            juju_context: An instance of the JujuContext class.
        """
        event_to_emit = self._get_event_to_emit(event_name)

        # If the event is not supported by the charm implementation, do
        # not error out or try to emit it. This is to support rollbacks.
        if event_to_emit is None:
            return

        args, kwargs = self._get_event_args(event_to_emit)
        logger.debug('Emitting Juju event %s.', event_name)
        # If tracing is set up, log the trace id so that tools like jhack can pick it up.
        # If tracing is not set up, span is non-recording and trace is zero.
        trace_id = opentelemetry.trace.get_current_span().get_span_context().trace_id
        if trace_id:
            # Note that https://github.com/canonical/jhack depends on exact string format.
            logger.debug("Starting root trace with id='%s'.", hex(trace_id)[2:])
        event_to_emit.emit(*args, **kwargs)

    def _commit(self):
        """Commit the framework and gracefully teardown."""
        self.framework.commit()

    def _close(self):
        """Perform any necessary cleanup before the framework is closed."""
        # Provided for child classes - nothing needs to be done in the base.

    def destroy(self):
        """Finalise the manager."""
        from . import tracing  # break circular import

        self._tracing_context.__exit__(*sys.exc_info())
        if tracing:
            tracing._shutdown()

    def run(self):
        """Emit and then commit the framework."""
        try:
            self._emit()
            self._commit()
            self._close()
        finally:
            self.framework.close()


def main(charm_class: type[_charm.CharmBase], use_juju_for_storage: bool | None = None):
    """Set up the charm and dispatch the observed event.

    See `ops.main() <#ops-main-entry-point>`_ for details.
    """
    manager = None
    try:
        manager = _Manager(charm_class, use_juju_for_storage=use_juju_for_storage)

        manager.run()
    except _Abort as e:
        sys.exit(e.exit_code)
    finally:
        if manager:
            manager.destroy()
