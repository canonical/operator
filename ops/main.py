# Copyright 2019-2020 Canonical Ltd.
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

"""Main entry point to the Operator Framework."""

import inspect
import logging
import os
import shutil
import subprocess
import sys
import typing
import warnings
from pathlib import Path

import yaml

import ops.charm
import ops.framework
import ops.model
import ops.storage

from ops.log import setup_root_logging
from ops.jujuversion import JujuVersion

CHARM_STATE_FILE = '.unit-state.db'


logger = logging.getLogger()


def _exe_path(path: Path) -> typing.Optional[Path]:
    """Find and return the full path to the given binary.

    Here path is the absolute path to a binary, but might be missing an extension.
    """
    p = shutil.which(path.name, mode=os.F_OK, path=str(path.parent))
    if p is None:
        return None
    return Path(p)


def _get_charm_dir():
    charm_dir = os.environ.get("JUJU_CHARM_DIR")
    if charm_dir is None:
        # Assume $JUJU_CHARM_DIR/lib/op/main.py structure.
        charm_dir = Path('{}/../../..'.format(__file__)).resolve()
    else:
        charm_dir = Path(charm_dir).resolve()
    return charm_dir


def _create_event_link(charm, bound_event, link_to):
    """Create a symlink for a particular event.

    charm -- A charm object.
    bound_event -- An event for which to create a symlink.
    link_to -- What the event link should point to
    """
    if issubclass(bound_event.event_type, ops.charm.HookEvent):
        event_dir = charm.framework.charm_dir / 'hooks'
        event_path = event_dir / bound_event.event_kind.replace('_', '-')
    elif issubclass(bound_event.event_type, ops.charm.ActionEvent):
        if not bound_event.event_kind.endswith("_action"):
            raise RuntimeError(
                'action event name {} needs _action suffix'.format(bound_event.event_kind))
        event_dir = charm.framework.charm_dir / 'actions'
        # The event_kind is suffixed with "_action" while the executable is not.
        event_path = event_dir / bound_event.event_kind[:-len('_action')].replace('_', '-')
    else:
        raise RuntimeError(
            'cannot create a symlink: unsupported event type {}'.format(bound_event.event_type))

    event_dir.mkdir(exist_ok=True)
    if not event_path.exists():
        target_path = os.path.relpath(link_to, str(event_dir))

        # Ignore the non-symlink files or directories
        # assuming the charm author knows what they are doing.
        logger.debug(
            'Creating a new relative symlink at %s pointing to %s',
            event_path, target_path)
        event_path.symlink_to(target_path)


def _setup_event_links(charm_dir, charm):
    """Set up links for supported events that originate from Juju.

    Whether a charm can handle an event or not can be determined by
    introspecting which events are defined on it.

    Hooks or actions are created as symlinks to the charm code file
    which is determined by inspecting symlinks provided by the charm
    author at hooks/install or hooks/start.

    charm_dir -- A root directory of the charm.
    charm -- An instance of the Charm class.

    """
    # XXX: on windows this function does not accomplish what it wants to:
    #      it creates symlinks with no extension pointing to a .py
    #      and juju only knows how to handle .exe, .bat, .cmd, and .ps1
    #      so it does its job, but does not accomplish anything as the
    #      hooks aren't 'callable'.
    link_to = os.path.realpath(os.environ.get("JUJU_DISPATCH_PATH", sys.argv[0]))
    for bound_event in charm.on.events().values():
        # Only events that originate from Juju need symlinks.
        if issubclass(bound_event.event_type, (ops.charm.HookEvent, ops.charm.ActionEvent)):
            _create_event_link(charm, bound_event, link_to)


def _emit_charm_event(charm, event_name):
    """Emits a charm event based on a Juju event name.

    charm -- A charm instance to emit an event from.
    event_name -- A Juju event name to emit on a charm.
    """
    event_to_emit = None
    try:
        event_to_emit = getattr(charm.on, event_name)
    except AttributeError:
        logger.debug("Event %s not defined for %s.", event_name, charm)

    # If the event is not supported by the charm implementation, do
    # not error out or try to emit it. This is to support rollbacks.
    if event_to_emit is not None:
        args, kwargs = _get_event_args(charm, event_to_emit)
        logger.debug('Emitting Juju event %s.', event_name)
        event_to_emit.emit(*args, **kwargs)


def _get_event_args(charm, bound_event):
    event_type = bound_event.event_type
    model = charm.framework.model

    if issubclass(event_type, ops.charm.RelationEvent):
        relation_name = os.environ['JUJU_RELATION']
        relation_id = int(os.environ['JUJU_RELATION_ID'].split(':')[-1])
        relation = model.get_relation(relation_name, relation_id)
    else:
        relation = None

    remote_app_name = os.environ.get('JUJU_REMOTE_APP', '')
    remote_unit_name = os.environ.get('JUJU_REMOTE_UNIT', '')
    if remote_app_name or remote_unit_name:
        if not remote_app_name:
            if '/' not in remote_unit_name:
                raise RuntimeError('invalid remote unit name: {}'.format(remote_unit_name))
            remote_app_name = remote_unit_name.split('/')[0]
        args = [relation, model.get_app(remote_app_name)]
        if remote_unit_name:
            args.append(model.get_unit(remote_unit_name))
        return args, {}
    elif relation:
        return [relation], {}
    return [], {}


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

    def __init__(self, charm_dir: Path):
        self._charm_dir = charm_dir
        self._exec_path = Path(os.environ.get('JUJU_DISPATCH_PATH', sys.argv[0]))

        dispatch = charm_dir / 'dispatch'
        if JujuVersion.from_environ().is_dispatch_aware() and _exe_path(dispatch) is not None:
            self._init_dispatch()
        else:
            self._init_legacy()

    def ensure_event_links(self, charm):
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
        if (self.event_name in ('install', 'start', 'upgrade_charm')
                or self.event_name.endswith('_storage_attached')):
            _setup_event_links(self._charm_dir, charm)

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
            logger.debug("Legacy %s does not exist.", self._dispatch_path)
            return

        # super strange that there isn't an is_executable
        if not os.access(str(dispatch_path), os.X_OK):
            logger.warning("Legacy %s exists but is not executable.", self._dispatch_path)
            return

        if dispatch_path.resolve() == Path(sys.argv[0]).resolve():
            logger.debug("Legacy %s is just a link to ourselves.", self._dispatch_path)
            return

        argv = sys.argv.copy()
        argv[0] = str(dispatch_path)
        logger.info("Running legacy %s.", self._dispatch_path)
        try:
            subprocess.run(argv, check=True)
        except subprocess.CalledProcessError as e:
            logger.warning("Legacy %s exited with status %d.", self._dispatch_path, e.returncode)
            sys.exit(e.returncode)
        except OSError as e:
            logger.warning("Unable to run legacy %s: %s", self._dispatch_path, e)
            sys.exit(1)
        else:
            logger.debug("Legacy %s exited with status 0.", self._dispatch_path)

    def _set_name_from_path(self, path: Path):
        """Sets the name attribute to that which can be inferred from the given path."""
        name = path.name.replace('-', '_')
        if path.parent.name == 'actions':
            name = '{}_action'.format(name)
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
        self._dispatch_path = Path(os.environ['JUJU_DISPATCH_PATH'])

        if 'OPERATOR_DISPATCH' in os.environ:
            logger.debug("Charm called itself via %s.", self._dispatch_path)
            sys.exit(0)
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


def _should_use_controller_storage(db_path: Path, meta: ops.charm.CharmMeta) -> bool:
    """Figure out whether we want to use controller storage or not."""
    # if you've previously used local state, carry on using that
    if db_path.exists():
        logger.debug("Using local storage: %s already exists", db_path)
        return False

    # if you're not in k8s you don't need controller storage
    if 'kubernetes' not in meta.series:
        logger.debug("Using local storage: not a kubernetes charm")
        return False

    # are we in a new enough Juju?
    cur_version = JujuVersion.from_environ()

    if cur_version.has_controller_storage():
        logger.debug("Using controller storage: JUJU_VERSION=%s", cur_version)
        return True
    else:
        logger.debug("Using local storage: JUJU_VERSION=%s", cur_version)
        return False


def main(charm_class: ops.charm.CharmBase, use_juju_for_storage: bool = None):
    """Setup the charm and dispatch the observed event.

    The event name is based on the way this executable was called (argv[0]).

    Args:
        charm_class: your charm class.
        use_juju_for_storage: whether to use controller-side storage. If not specified
            then kubernetes charms that haven't previously used local storage and that
            are running on a new enough Juju default to controller-side storage,
            otherwise local storage is used.
    """
    charm_dir = _get_charm_dir()

    model_backend = ops.model._ModelBackend()
    debug = ('JUJU_DEBUG' in os.environ)
    setup_root_logging(model_backend, debug=debug)
    logger.debug("Operator Framework %s up and running.", ops.__version__)

    dispatcher = _Dispatcher(charm_dir)
    dispatcher.run_any_legacy_hook()

    metadata = (charm_dir / 'metadata.yaml').read_text()
    actions_meta = charm_dir / 'actions.yaml'
    if actions_meta.exists():
        actions_metadata = actions_meta.read_text()
    else:
        actions_metadata = None

    if not yaml.__with_libyaml__:
        logger.debug('yaml does not have libyaml extensions, using slower pure Python yaml loader')
    meta = ops.charm.CharmMeta.from_yaml(metadata, actions_metadata)
    model = ops.model.Model(meta, model_backend)

    charm_state_path = charm_dir / CHARM_STATE_FILE

    if use_juju_for_storage and not ops.storage.juju_backend_available():
        # raise an exception; the charm is broken and needs fixing.
        msg = 'charm set use_juju_for_storage=True, but Juju version {} does not support it'
        raise RuntimeError(msg.format(JujuVersion.from_environ()))

    if use_juju_for_storage is None:
        use_juju_for_storage = _should_use_controller_storage(charm_state_path, meta)

    if use_juju_for_storage:
        if dispatcher.is_restricted_context():
            # TODO: jam 2020-06-30 This unconditionally avoids running a collect metrics event
            #  Though we eventually expect that juju will run collect-metrics in a
            #  non-restricted context. Once we can determine that we are running collect-metrics
            #  in a non-restricted context, we should fire the event as normal.
            logger.debug('"%s" is not supported when using Juju for storage\n'
                         'see: https://github.com/canonical/operator/issues/348',
                         dispatcher.event_name)
            # Note that we don't exit nonzero, because that would cause Juju to rerun the hook
            return
        store = ops.storage.JujuStorage()
    else:
        store = ops.storage.SQLiteStorage(charm_state_path)
    framework = ops.framework.Framework(store, charm_dir, meta, model)
    framework.set_breakpointhook()
    try:
        sig = inspect.signature(charm_class)
        try:
            sig.bind(framework)
        except TypeError:
            msg = (
                "the second argument, 'key', has been deprecated and will be "
                "removed after the 0.7 release")
            warnings.warn(msg, DeprecationWarning)
            charm = charm_class(framework, None)
        else:
            charm = charm_class(framework)
        dispatcher.ensure_event_links(charm)

        # TODO: Remove the collect_metrics check below as soon as the relevant
        #       Juju changes are made. Also adjust the docstring on
        #       EventBase.defer().
        #
        # Skip reemission of deferred events for collect-metrics events because
        # they do not have the full access to all hook tools.
        if not dispatcher.is_restricted_context():
            framework.reemit()

        _emit_charm_event(charm, dispatcher.event_name)

        framework.commit()
    finally:
        framework.close()
