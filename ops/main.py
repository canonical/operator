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

"""Main entry point to the framework.

Note that this module is callable, and calls the :func:`ops.main.main` function.
This is so that :code:`import ops` followed by :code:`ops.main(MyCharm)` works
as expected.
"""

import logging
import os
import shutil
import subprocess
import sys
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Type, Union, cast

import ops.charm
import ops.framework
import ops.model
import ops.storage
from ops.charm import CharmMeta
from ops.jujucontext import _JujuContext
from ops.log import setup_root_logging

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
    charm: 'ops.charm.CharmBase',
    bound_event: 'ops.framework.BoundEvent',
    link_to: Union[str, Path],
):
    """Create a symlink for a particular event.

    Args:
        charm: A charm object.
        bound_event: An event for which to create a symlink.
        link_to: What the event link should point to
    """
    # type guard
    assert bound_event.event_kind, f'unbound BoundEvent {bound_event}'

    if issubclass(bound_event.event_type, ops.charm.HookEvent):
        event_dir = charm.framework.charm_dir / 'hooks'
        event_path = event_dir / bound_event.event_kind.replace('_', '-')
    elif issubclass(bound_event.event_type, ops.charm.ActionEvent):
        if not bound_event.event_kind.endswith('_action'):
            raise RuntimeError(f'action event name {bound_event.event_kind} needs _action suffix')
        event_dir = charm.framework.charm_dir / 'actions'
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


def _setup_event_links(charm_dir: Path, charm: 'ops.charm.CharmBase', juju_context: _JujuContext):
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
        if issubclass(bound_event.event_type, (ops.charm.HookEvent, ops.charm.ActionEvent)):
            _create_event_link(charm, bound_event, link_to)


def _emit_charm_event(charm: 'ops.charm.CharmBase', event_name: str, juju_context: _JujuContext):
    """Emits a charm event based on a Juju event name.

    Args:
        charm: A charm instance to emit an event from.
        event_name: A Juju event name to emit on a charm.
        juju_context: An instance of the _JujuContext class.
    """
    event_to_emit = None
    try:
        event_to_emit = getattr(charm.on, event_name)
    except AttributeError:
        logger.debug('Event %s not defined for %s.', event_name, charm)

    # If the event is not supported by the charm implementation, do
    # not error out or try to emit it. This is to support rollbacks.
    if event_to_emit is not None:
        args, kwargs = _get_event_args(charm, event_to_emit, juju_context)
        logger.debug('Emitting Juju event %s.', event_name)
        event_to_emit.emit(*args, **kwargs)


def _get_event_args(
    charm: 'ops.charm.CharmBase',
    bound_event: 'ops.framework.BoundEvent',
    juju_context: _JujuContext,
) -> Tuple[List[Any], Dict[str, Any]]:
    event_type = bound_event.event_type
    model = charm.framework.model

    relation = None
    if issubclass(event_type, ops.charm.WorkloadEvent):
        workload_name = juju_context.workload_name
        assert workload_name is not None
        container = model.unit.get_container(workload_name)
        args: List[Any] = [container]
        if issubclass(event_type, ops.charm.PebbleNoticeEvent):
            notice_id = juju_context.notice_id
            notice_type = juju_context.notice_type
            notice_key = juju_context.notice_key
            args.extend([notice_id, notice_type, notice_key])
        elif issubclass(event_type, ops.charm.PebbleCheckEvent):
            check_name = juju_context.pebble_check_name
            args.append(check_name)
        return args, {}
    elif issubclass(event_type, ops.charm.SecretEvent):
        args: List[Any] = [
            juju_context.secret_id,
            juju_context.secret_label,
        ]
        if issubclass(event_type, (ops.charm.SecretRemoveEvent, ops.charm.SecretExpiredEvent)):
            args.append(juju_context.secret_revision)
        return args, {}
    elif issubclass(event_type, ops.charm.StorageEvent):
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
        storage = cast(Union[ops.storage.JujuStorage, ops.storage.SQLiteStorage], storage)
        storage.location = storage_location  # type: ignore
        return [storage], {}
    elif issubclass(event_type, ops.charm.ActionEvent):
        args: List[Any] = [juju_context.action_uuid]
        return args, {}
    elif issubclass(event_type, ops.charm.RelationEvent):
        relation_name = juju_context.relation_name
        assert relation_name is not None
        relation_id = juju_context.relation_id
        relation: Optional[ops.model.Relation] = model.get_relation(relation_name, relation_id)

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

    Also knows how to run “legacy” hooks when Juju called us via a top-level
    ``dispatch`` binary.

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

    def ensure_event_links(self, charm: 'ops.charm.CharmBase'):
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
        # K8s charms (see LP: #1854635).
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
    db_path: Path, meta: CharmMeta, juju_context: _JujuContext
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
      - re-emit any deferred events found in the storage
      - emit the Juju event to the charm
        - emit any custom events emitted by the charm during this phase
      - emit  the ``collect-status`` events
    - commit: responsible for:
      - store any events deferred throughout this execution
      - graceful teardown of the storage
    """

    def __init__(
        self,
        charm_class: Type['ops.charm.CharmBase'],
        model_backend: Optional[ops.model._ModelBackend] = None,
        use_juju_for_storage: Optional[bool] = None,
        charm_state_path: str = CHARM_STATE_FILE,
    ):
        self._juju_context = _JujuContext.from_dict(os.environ)
        self._charm_state_path = charm_state_path
        self._charm_class = charm_class
        if model_backend is None:
            model_backend = ops.model._ModelBackend(juju_context=self._juju_context)
        self._model_backend = model_backend

        # Do this as early as possible to be sure to catch the most logs.
        self._setup_root_logging()

        self._charm_root = self._juju_context.charm_dir
        self._charm_meta = CharmMeta.from_charm_root(self._charm_root)
        self._use_juju_for_storage = use_juju_for_storage

        # Set up dispatcher, framework and charm objects.
        self.dispatcher = _Dispatcher(self._charm_root, self._juju_context)
        self.dispatcher.run_any_legacy_hook()

        self.framework = self._make_framework(self.dispatcher)
        self.charm = self._make_charm(self.framework, self.dispatcher)

    def _make_charm(self, framework: 'ops.framework.Framework', dispatcher: _Dispatcher):
        charm = self._charm_class(framework)
        dispatcher.ensure_event_links(charm)
        return charm

    def _setup_root_logging(self):
        # For actions, there is a communication channel with the user running the
        # action, so we want to send exception details through stderr, rather than
        # only to juju-log as normal.
        handling_action = self._juju_context.action_name is not None
        setup_root_logging(
            self._model_backend, debug=self._juju_context.debug, exc_stderr=handling_action
        )

        logger.debug('ops %s up and running.', ops.__version__)

    def _make_storage(self, dispatcher: _Dispatcher):
        charm_state_path = self._charm_root / self._charm_state_path

        use_juju_for_storage = self._use_juju_for_storage
        if use_juju_for_storage and not ops.storage.juju_backend_available():
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
            store = ops.storage.JujuStorage()
        else:
            store = ops.storage.SQLiteStorage(charm_state_path)
        return store

    def _make_framework(self, dispatcher: _Dispatcher):
        # If we are in a RelationBroken event, we want to know which relation is
        # broken within the model, not only in the event's `.relation` attribute.

        if self._juju_context.dispatch_path.endswith('-relation-broken'):
            broken_relation_id = self._juju_context.relation_id
        else:
            broken_relation_id = None

        model = ops.model.Model(
            self._charm_meta, self._model_backend, broken_relation_id=broken_relation_id
        )
        store = self._make_storage(dispatcher)
        framework = ops.framework.Framework(
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
        # they do not have the full access to all hook tools.
        if not self.dispatcher.is_restricted_context():
            # Re-emit any deferred events from the previous run.
            self.framework.reemit()

        # Emit the Juju event.
        _emit_charm_event(self.charm, self.dispatcher.event_name, self._juju_context)
        # Emit collect-status events.
        ops.charm._evaluate_status(self.charm)

    def _commit(self):
        """Commit the framework and gracefully teardown."""
        self.framework.commit()

    def run(self):
        """Emit and then commit the framework."""
        try:
            self._emit()
            self._commit()
        finally:
            self.framework.close()


def main(charm_class: Type[ops.charm.CharmBase], use_juju_for_storage: Optional[bool] = None):
    """Set up the charm and dispatch the observed event.

    The event name is based on the way this executable was called (argv[0]).

    .. jujuremoved:: 4.0
        The ``use_juju_for_storage`` argument is not available from Juju 4.0

    Args:
        charm_class: the charm class to instantiate and receive the event.
        use_juju_for_storage: whether to use controller-side storage. If not specified
            then Kubernetes charms that haven't previously used local storage and that
            are running on a new enough Juju default to controller-side storage,
            otherwise local storage is used.
    """
    try:
        manager = _Manager(charm_class, use_juju_for_storage=use_juju_for_storage)

        manager.run()
    except _Abort as e:
        sys.exit(e.exit_code)


# Make this module callable and call main(), so that "import ops" and then
# "ops.main(Charm)" works as expected now that everything is imported in
# ops/__init__.py. Idea from https://stackoverflow.com/a/48100440/68707
class _CallableModule(sys.modules[__name__].__class__):
    def __call__(
        self, charm_class: Type[ops.charm.CharmBase], use_juju_for_storage: Optional[bool] = None
    ):
        return main(charm_class, use_juju_for_storage=use_juju_for_storage)


sys.modules[__name__].__class__ = _CallableModule
