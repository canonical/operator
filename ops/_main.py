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

import logging
import os
import shutil
import subprocess
import sys
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Type, Union, cast

from . import charm as _charm
from . import framework as _framework
from . import model as _model
from . import storage as _storage
from . import version as _version
from .jujucontext import _JujuContext
from .log import setup_root_logging

CHARM_STATE_FILE = '.unit-state.db'


logger = logging.getLogger()


def _exe_path(path: Path) -> Optional[Path]:
    """Find and return the full path to the given binary.

    Here path is the absolute path to a binary, but might be missing an extension.
    """
    p = shutil.which(path.name, mode=os.F_OK, path=str(path.parent))
    if p is None:
        return None
    return Path(p)


def _create_event_link(
    charm_dir: Path,
    bound_event: '_framework.BoundEvent',
    link_to: Union[str, Path],
):
    """Create a symlink for a particular event.

    Args:
        charm_dir: The root charm directory.
        bound_event: An event for which to create a symlink.
        link_to: What the event link should point to
    """
    # type guard
    assert bound_event.event_kind, f'unbound BoundEvent {bound_event}'

    if issubclass(bound_event.event_type, _.HookEvent):
        event_dir = charm_dir / 'hooks'
        event_path = event_dir / bound_event.event_kind.replace('_', '-')
    elif issubclass(bound_event.event_type, _charm.ActionEvent):
        if not bound_event.event_kind.endswith('_action'):
            raise RuntimeError(f'action event name {bound_event.event_kind} needs _action suffix')
        event_dir = charm_dir / 'actions'
        # The event_kind is suffixed with "_action" while the executable is not.
        event_path = event_dir / bound_event.event_kind[: -len('_action')].replace('_', '-')
    else:
        raise RuntimeError(
            f'cannot create a symlink: unsupported event type {bound_event.event_type}'
        )

    event_dir.mkdir(exist_ok=True)
    if not event_path.exists():
        target_path = os.path.relpath(link_to, str(event_dir))

        # Ignore the non-symlink files or directories
        # assuming the charm author knows what they are doing.
        logger.debug(
            'Creating a new relative symlink at %s pointing to %s', event_path, target_path
        )
        event_path.symlink_to(target_path)


def _setup_event_links(charm_dir: Path, charm: '_charm.CharmBase', juju_context: _JujuContext):
    """Set up links for supported events that originate from Juju.

    Whether a charm can handle an event or not can be determined by
    introspecting which events are defined on it.

    Hooks or actions are created as symlinks to the charm code file
    which is determined by inspecting symlinks provided by the charm
    author at hooks/install or hooks/start.

    Args:
        charm_dir: A root directory of the charm.
        charm: An instance of the Charm class.
        juju_context: An instance of the _JujuContext class.

    """
    link_to = os.path.realpath(juju_context.dispatch_path or sys.argv[0])
    for bound_event in charm.on.events().values():
        # Only events that originate from Juju need symlinks.
        if issubclass(bound_event.event_type, (_charm.HookEvent, _.ActionEvent)):
            _create_event_link(charm_dir, bound_event, link_to)


def _get_event_args(
    charm: '_charm.CharmBase',
    bound_event: '_framework.BoundEvent',
    juju_context: _JujuContext,
) -> Tuple[List[Any], Dict[str, Any]]:
    event_type = bound_event.event_type
    model = charm.framework.model

    relation = None
    if issubclass(event_type, _charm.WorkloadEvent):
        workload_name = juju_context.workload_name
        assert workload_name is not None
        container = model.unit.get_container(workload_name)
        args: List[Any] = [container]
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
        args: List[Any] = [
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

        storages = model.storages[storage_name]
        index, storage_location = model._backend._storage_event_details()
        if len(storages) == 1:
            storage = storages[0]
        else:
            # If there's more than one value, pick the right one. We'll realize the key on lookup
            storage = next((s for s in storages if s.index == index), None)
        storage = cast(Union[_storage.JujuStorage, _storage.SQLiteStorage], storage)
        storage.location = storage_location  # type: ignore
        return [storage], {}
    elif issubclass(event_type, _charm.ActionEvent):
        args: List[Any] = [juju_context.action_uuid]
        return args, {}
    elif issubclass(event_type, _charm.RelationEvent):
        relation_name = juju_context.relation_name
        assert relation_name is not None
        relation_id = juju_context.relation_id
        relation: Optional[_model.Relation] = model.get_relation(relation_name, relation_id)

    remote_app_name = juju_context.remote_app_name
    remote_unit_name = juju_context.remote_unit_name
    departing_unit_name = juju_context.relation_departing_unit_name

    if not remote_app_name and remote_unit_name:
        if '/' not in remote_unit_name:
            raise RuntimeError(f'invalid remote unit name: {remote_unit_name}')
        remote_app_name = remote_unit_name.split('/')[0]

    kwargs: Dict[str, Any] = {}
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
        is_dispatch_aware: are we running under a Juju that knows about the
            dispatch binary, and is that binary present?

    """

    def __init__(self, charm_dir: Path, juju_context: _JujuContext):
        self._juju_context = juju_context
        self._charm_dir = charm_dir
        self._exec_path = Path(self._juju_context.dispatch_path or sys.argv[0])

        dispatch = charm_dir / 'dispatch'
        if self._juju_context.version.is_dispatch_aware() and _exe_path(dispatch) is not None:
            self._init_dispatch()
        else:
            self._init_legacy()

    def ensure_event_links(self, charm: '_charm.CharmBase'):
        """Make sure necessary symlinks are present on disk."""
        if self.is_dispatch_aware:
            # links aren't needed
            return

        # When a charm is force-upgraded and a unit is in an error state Juju
        # does not run upgrade-charm and instead runs the failed hook followed
        # by config-changed. Given the nature of force-upgrading the hook setup
        # code is not triggered on config-changed.
        #
        # 'start' event is included as Juju does not fire the install event for
        # K8s charms https://bugs.launchpad.net/juju/+bug/1854635, fixed in juju 2.7.6 and 2.8
        if self.event_name in ('install', 'start', 'upgrade_charm') or self.event_name.endswith(
            '_storage_attached'
        ):
            _setup_event_links(self._charm_dir, charm, self._juju_context)

    def run_any_legacy_hook(self):
        """Run any extant legacy hook.

        If there is both a dispatch file and a legacy hook for the
        current event, run the wanted legacy hook.
        """
        if not self.is_dispatch_aware:
            # we *are* the legacy hook
            return

        dispatch_path = _exe_path(self._charm_dir / self._dispatch_path)
        if dispatch_path is None:
            return

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

    def _init_legacy(self):
        """Set up the 'legacy' dispatcher.

        The current Juju doesn't know about 'dispatch' and calls hooks
        explicitly.
        """
        self.is_dispatch_aware = False
        self._set_name_from_path(self._exec_path)

    def _init_dispatch(self):
        """Set up the new 'dispatch' dispatcher.

        The current Juju will run 'dispatch' if it exists, and otherwise fall
        back to the old behaviour.

        JUJU_DISPATCH_PATH will be set to the wanted hook, e.g. hooks/install,
        in both cases.
        """
        self._dispatch_path = Path(self._juju_context.dispatch_path)

        if 'OPERATOR_DISPATCH' in os.environ:
            logger.debug('Charm called itself via %s.', self._dispatch_path)
            raise _Abort(0)
        os.environ['OPERATOR_DISPATCH'] = '1'

        self.is_dispatch_aware = True
        self._set_name_from_path(self._dispatch_path)

    def is_restricted_context(self):
        """Return True if we are running in a restricted Juju context.

        When in a restricted context, most commands (relation-get, config-get,
        state-get) are not available. As such, we change how we interact with
        Juju.
        """
        return self.event_name in ('collect_metrics',)


def _should_use_controller_storage(
    db_path: Path, meta: _charm.CharmMeta, juju_context: _JujuContext
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
      - the Framework (hook tool wrappers)
      - the storage backend
      - the event that Juju is emitting on us
      - the charm instance (user-facing)
    - emit: core user-facing lifecycle step. Consists of:
      - emit the Juju event to the charm
        - emit any custom events emitted by the charm during this phase
      - emit  the ``collect-status`` events
    - commit: responsible for:
      - store any events deferred throughout this execution
      - graceful teardown of the storage

    The above steps are first run for any deferred notices found in the storage
    (all three steps for each notice, except for emitting Lifecycle events), and
    then run a final time for the Juju event that triggered this execution.
    """

    def __init__(
        self,
        charm_class: Type['_charm.CharmBase'],
        juju_context: _JujuContext,
        use_juju_for_storage: Optional[bool] = None,
        charm_state_path: str = CHARM_STATE_FILE,
    ):
        # The context is shared across deferred events and the Juju event. Any
        # data from the context that is event-specific must be included in the
        # event object snapshot/restore rather than re-read from the context.
        # Data not connected to the event (debug settings, the Juju version, the
        # app and unit name, and so forth) will be the *current* data, not the
        # data at the time the event was deferred -- this aligns with the data
        # from hook tools.
        self._juju_context = juju_context
        self._charm_state_path = charm_state_path
        self._charm_class = charm_class

        # Do this as early as possible to be sure to catch the most logs.
        self._setup_root_logging()

        self._charm_root = self._juju_context.charm_dir
        self._charm_meta = self._load_charm_meta()
        self._use_juju_for_storage = use_juju_for_storage

        # Handle legacy hooks - this is only done once, not with each deferred
        # event.
        self._dispatcher = _Dispatcher(self._charm_root, self._juju_context)
        self._dispatcher.run_any_legacy_hook()

        # Storage is shared across all events, so we create it once here.
        self._storage = self._make_storage()

        self.run_deferred()

        # This is the charm for the Juju event. We create it here so that it's
        # available for pre-emit adjustments when being used in testing.
        self.charm = self._make_charm(self._dispatcher.event_name)

        # This is with the charm used for the Juju event, but it's being removed
        # later this cycle anyway, so we want minimum tweaking.
        self._dispatcher.ensure_event_links(self.charm)

    def _load_charm_meta(self):
        return _charm.CharmMeta.from_charm_root(self._charm_root)

    def _make_model_backend(self):
        # model._ModelBackend is stateless and can be reused across events.
        # However, in testing (both Harness and Scenario) the backend stores all
        # the state that is normally in Juju. To be consistent, we create a new
        # backend object even in production code.
        return _model._ModelBackend(juju_context=self._juju_context)

    def _make_charm(self, event_name: str):
        framework = self._make_framework(event_name)
        return self._charm_class(framework)

    def _setup_root_logging(self):
        # For actions, there is a communication channel with the user running the
        # action, so we want to send exception details through stderr, rather than
        # only to juju-log as normal.
        handling_action = self._juju_context.action_name is not None
        # We don't really want to have a different backend here than when
        # running the event. However, we need to create a new backend for each
        # event and want the logging set up before we are ready to emit an
        # event. In practice, this isn't a problem:
        # * for model._ModelBackend, `juju_log` calls out directly to the hook
        #   tool; it's effectively a staticmethod.
        # * for _private.harness._TestingModelBackend, `juju_log` is not
        #   implemented, and the logging is never configured.
        # * for scenario.mocking._MockModelBackend, `juju_log` sends the logging
        #   through to the `Context` object, which will be the same for all
        #   events.
        # TODO: write tests to make sure that everything remains ok here.
        setup_root_logging(
            self._make_model_backend(), debug=self._juju_context.debug, exc_stderr=handling_action
        )

        logger.debug('ops %s up and running.', _version.version)

    def _make_storage(self):
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

        if use_juju_for_storage and self._dispatcher.is_restricted_context():
            # collect-metrics is going away in Juju 4.0, and restricted context
            # with it, so we don't need this to be particularly generic.
            logger.debug(
                '"collect_metrics" is not supported when using Juju for storage\n'
                'see: https://github.com/canonical/operator/issues/348',
            )
            # Note that we don't exit nonzero, because that would cause Juju to rerun the hook
            raise _Abort(0)

        if self._use_juju_for_storage:
            store = _storage.JujuStorage()
        else:
            store = _storage.SQLiteStorage(charm_state_path)
        return store

    def _make_framework(self, event_name: str):
        # If we are in a RelationBroken event, we want to know which relation is
        # broken within the model, not only in the event's `.relation` attribute.

        if self._juju_context.dispatch_path.endswith(('-relation-broken', '_relation_broken')):
            broken_relation_id = self._juju_context.relation_id
        else:
            broken_relation_id = None

        model_backend = self._make_model_backend()
        model = _model.Model(
            self._charm_meta, model_backend, broken_relation_id=broken_relation_id
        )
        framework = _framework.Framework(
            self._storage,
            self._charm_root,
            self._charm_meta,
            model,
            event_name=event_name,
            juju_debug_at=self._juju_context.debug_at,
        )
        framework.set_breakpointhook()
        return framework

    def _emit(self, charm: ops.charm.CharmBase, event_name: str):
        """Emit the event on the charm."""
        # Emit the Juju event.
        self._emit_charm_event(charm, event_name)
        # Emit collect-status events.
        _charm._evaluate_status(charm)

    def _get_event_to_emit(
        self, charm: ops.charm.CharmBase, event_name: str
    ) -> Optional[ops.framework.BoundEvent]:
        try:
            return getattr(charm.on, event_name)
        except AttributeError:
            logger.debug('Event %s not defined for %s.', event_name, charm)
        return None

    def _emit_charm_event(self, charm: ops.charm.CharmBase, event_name: str):
        """Emits a charm event based on a Juju event name.

        Args:
            charm: A charm instance to emit an event from.
            event_name: A Juju event name to emit on a charm.
            juju_context: An instance of the _JujuContext class.
        """
        event_to_emit = self._get_event_to_emit(charm, event_name)

        # If the event is not supported by the charm implementation, do
        # not error out or try to emit it. This is to support rollbacks.
        if event_to_emit is None:
            return

        args, kwargs = _get_event_args(charm, event_to_emit, self._juju_context)
        logger.debug('Emitting Juju event %s.', event_name)
        event_to_emit.emit(*args, **kwargs)

    def _commit(self, framework: ops.framework.Framework):
        """Commit the framework and gracefully teardown."""
        framework.commit()

    def _close(self):
        """Perform any necessary cleanup before the framework is closed."""
        # Provided for child classes - nothing needs to be done in the base.

    def run_deferred(self):
        """Emit and then commit the framework.

        A framework and charm object are created for each notice in the storage
        (an event and observer pair), the relevant deferred event is emitted,
        and the framework is committed. Note that collect-status events are not
        emitted.
        """
        # TODO: Remove the restricted context check below once we no longer need
        #       to support Juju < 4 (collect-metrics and restricted context are
        #       being removed in Juju 4.0).
        #
        # Skip re-emission of deferred events for collect-metrics events because
        # they do not have the full access to all hook tools.
        if self._dispatcher.is_restricted_context():
            return
        # Re-emit previously deferred events to the observers that deferred them.
        for event_path, _, _ in self._storage.notices():
            event_handle = ops.framework.Handle.from_path(event_path)
            logger.debug('Re-emitting deferred event %s.', event_handle)
            charm = self._make_charm(event_handle.kind)
            charm.framework.reemit(event_path)
            self._commit(charm.framework)

    def run(self):
        """Emit and then commit the framework."""
        try:
            self._emit(self.charm, self._dispatcher.event_name)
            self._commit(self.charm.framework)
            self._close()
        finally:
            self.charm.framework.close()


def main(charm_class: Type[_charm.CharmBase], use_juju_for_storage: Optional[bool] = None):
    """Set up the charm and dispatch the observed event.

    See `ops.main() <#ops-main-entry-point>`_ for details.
    """
    try:
        juju_context = _JujuContext.from_dict(os.environ)
        manager = _Manager(
            charm_class, use_juju_for_storage=use_juju_for_storage, juju_context=juju_context
        )

        manager.run()
    except _Abort as e:
        sys.exit(e.exit_code)
