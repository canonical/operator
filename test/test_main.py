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

import abc
import io
import logging
import logassert
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import unittest
import importlib.util
import warnings
import yaml
from pathlib import Path
from unittest.mock import patch

from ops.charm import (
    CharmBase,
    CharmEvents,
    CharmMeta,
    HookEvent,
    InstallEvent,
    StartEvent,
    ConfigChangedEvent,
    UpgradeCharmEvent,
    UpdateStatusEvent,
    LeaderSettingsChangedEvent,
    RelationJoinedEvent,
    RelationChangedEvent,
    RelationDepartedEvent,
    RelationBrokenEvent,
    RelationEvent,
    StorageAttachedEvent,
    ActionEvent,
    CollectMetricsEvent,
)
from ops.framework import Framework, StoredStateData
from ops.main import main, CHARM_STATE_FILE, _should_use_controller_storage
from ops.storage import SQLiteStorage
from ops.version import version

from .test_helpers import fake_script, fake_script_calls

is_windows = platform.system() == 'Windows'

# This relies on the expected repository structure to find a path to
# source of the charm under test.
TEST_CHARM_DIR = Path(__file__ + '/../charms/test_main').resolve()

VERSION_LOGLINE = [
    'juju-log', '--log-level', 'DEBUG', '--',
    'Operator Framework {} up and running.'.format(version),
]
SLOW_YAML_LOGLINE = [
    'juju-log', '--log-level', 'DEBUG', '--',
    'yaml does not have libyaml extensions, using slower pure Python yaml loader',
]

logger = logging.getLogger(__name__)


class SymlinkTargetError(Exception):
    pass


class EventSpec:
    def __init__(self, event_type, event_name, env_var=None,
                 relation_id=None, remote_app=None, remote_unit=None,
                 model_name=None, set_in_env=None):
        self.event_type = event_type
        self.event_name = event_name
        self.env_var = env_var
        self.relation_id = relation_id
        self.remote_app = remote_app
        self.remote_unit = remote_unit
        self.model_name = model_name
        self.set_in_env = set_in_env


@patch('ops.main.setup_root_logging', new=lambda *a, **kw: None)
class CharmInitTestCase(unittest.TestCase):

    @unittest.skipIf(sys.version_info < (3, 7), "no breakpoint builtin for Python < 3.7")
    @patch('sys.stderr', new_callable=io.StringIO)
    def test_breakpoint(self, fake_stderr):
        class MyCharm(CharmBase):
            pass
        self._check(MyCharm, extra_environ={'JUJU_DEBUG_AT': 'all'})

        with patch('pdb.Pdb.set_trace') as mock:
            breakpoint()        # noqa: F821 ('undefined name' in <3.7)

        self.assertEqual(mock.call_count, 1)
        self.assertIn('Starting pdb to debug charm operator', fake_stderr.getvalue())

    @unittest.skipIf(sys.version_info < (3, 7), "no breakpoint builtin for Python < 3.7")
    def test_no_debug_breakpoint(self):
        class MyCharm(CharmBase):
            pass
        self._check(MyCharm, extra_environ={'JUJU_DEBUG_AT': ''})

        with patch('pdb.Pdb.set_trace') as mock:
            breakpoint()        # noqa: F821 ('undefined name' in <3.7)

        self.assertEqual(mock.call_count, 0)

    def _check(self, charm_class, *, extra_environ=None, **kwargs):
        """Helper for below tests."""
        fake_environ = {
            'JUJU_UNIT_NAME': 'test_main/0',
            'JUJU_MODEL_NAME': 'mymodel',
            'JUJU_VERSION': '2.7.0',
        }
        if extra_environ is not None:
            fake_environ.update(extra_environ)
        with patch.dict(os.environ, fake_environ):
            with patch('ops.main._emit_charm_event'):
                with patch('ops.main._get_charm_dir') as mock_charmdir:
                    with tempfile.TemporaryDirectory() as tmpdirname:
                        tmpdirname = Path(tmpdirname)
                        fake_metadata = tmpdirname / 'metadata.yaml'
                        with fake_metadata.open('wb') as fh:
                            fh.write(b'name: test')
                        mock_charmdir.return_value = tmpdirname

                        with warnings.catch_warnings(record=True) as warnings_cm:
                            main(charm_class, **kwargs)

        return warnings_cm

    def test_init_signature_passthrough(self):
        class MyCharm(CharmBase):

            def __init__(self, *args):
                super().__init__(*args)

        warn_cm = self._check(MyCharm)
        self.assertFalse(warn_cm)

    def test_init_signature_both_arguments(self):
        class MyCharm(CharmBase):

            def __init__(self, framework, somekey):
                super().__init__(framework, somekey)

        warn_cm = self._check(MyCharm)
        self.assertEqual(len(warn_cm), 1)
        (warn,) = warn_cm
        self.assertTrue(issubclass(warn.category, DeprecationWarning))
        self.assertEqual(str(warn.message), (
            "the second argument, 'key', has been deprecated and will be removed "
            "after the 0.7 release"))

    def test_init_signature_only_framework(self):
        class MyCharm(CharmBase):

            def __init__(self, framework):
                super().__init__(framework)

        warn_cm = self._check(MyCharm)
        self.assertFalse(warn_cm)

    def test_storage_no_storage(self):
        # here we patch juju_backend_available so it refuses to set it up
        with patch('ops.storage.juju_backend_available') as juju_backend_available:
            juju_backend_available.return_value = False
            with self.assertRaisesRegex(
                    RuntimeError,
                    'charm set use_juju_for_storage=True, but Juju .* does not support it'):
                self._check(CharmBase, use_juju_for_storage=True)

    def test_storage_with_storage(self):
        # here we patch juju_backend_available, so it gets set up and falls over when used
        with patch('ops.storage.juju_backend_available') as juju_backend_available:
            juju_backend_available.return_value = True
            with self.assertRaisesRegex(FileNotFoundError, 'state-get'):
                self._check(CharmBase, use_juju_for_storage=True)


@patch('sys.argv', new=("hooks/config-changed",))
@patch('ops.main.setup_root_logging', new=lambda *a, **kw: None)
class TestDispatch(unittest.TestCase):
    def _check(self, *, with_dispatch=False, dispatch_path=''):
        """Helper for below tests."""
        class MyCharm(CharmBase):
            def __init__(self, framework):
                super().__init__(framework)

        fake_environ = {
            'JUJU_UNIT_NAME': 'test_main/0',
            'JUJU_MODEL_NAME': 'mymodel',
        }
        if dispatch_path:
            fake_environ['JUJU_DISPATCH_PATH'] = dispatch_path
            fake_environ['JUJU_VERSION'] = '2.8.0'
        else:
            fake_environ['JUJU_VERSION'] = '2.7.0'

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            fake_metadata = tmpdir / 'metadata.yaml'
            with fake_metadata.open('wb') as fh:
                fh.write(b'name: test')
            if with_dispatch:
                dispatch = tmpdir / 'dispatch'
                dispatch.write_text('', encoding='utf8')
                dispatch.chmod(0o755)

            with patch.dict(os.environ, fake_environ):
                with patch('ops.main._emit_charm_event') as mock_charm_event:
                    with patch('ops.main._get_charm_dir') as mock_charmdir:
                        mock_charmdir.return_value = tmpdir
                        main(MyCharm)

        self.assertEqual(mock_charm_event.call_count, 1)
        return mock_charm_event.call_args[0][1]

    def test_most_legacy(self):
        """Without dispatch, sys.argv[0] is used."""
        event = self._check()
        self.assertEqual(event, 'config_changed')

    def test_with_dispatch(self):
        """With dispatch, dispatch is used."""
        event = self._check(with_dispatch=True, dispatch_path='hooks/potatos')
        self.assertEqual(event, 'potatos')

    def test_with_dispatch_path_but_no_dispatch(self):
        """Dispatch path overwrites sys.argv[0] even if no actual dispatch."""
        event = self._check(with_dispatch=False, dispatch_path='hooks/foo')
        self.assertEqual(event, 'foo')


class _TestMain(abc.ABC):

    @abc.abstractmethod
    def _setup_entry_point(self, directory, entry_point):
        """Set up the given entry point in the given directory.

        If not using dispatch, that would be a symlink <dir>/<entry_point>
        pointing at src/charm.py; if using dispatch that would be the dispatch
        symlink. It could also not be a symlink...
        """
        return NotImplemented

    @abc.abstractmethod
    def _call_event(self, rel_path, env):
        """Set up the environment and call (i.e. run) the given event."""
        return NotImplemented

    @abc.abstractmethod
    def test_setup_event_links(self):
        """Test auto-creation of symlinks caused by initial events.

        Depending on the combination of dispatch and non-dispatch, this should
        be checking for the creation or the _lack_ of creation, as appropriate.
        """
        return NotImplemented

    def setUp(self):
        self._setup_charm_dir()

        # Relations events are defined dynamically and modify the class attributes.
        # We use a subclass temporarily to prevent these side effects from leaking.
        class TestCharmEvents(CharmEvents):
            pass
        CharmBase.on = TestCharmEvents()

        def cleanup():
            CharmBase.on = CharmEvents()
        self.addCleanup(cleanup)

        fake_script(self, 'juju-log', "exit 0")

        # set to something other than None for tests that care
        self.stdout = None
        self.stderr = None

    def _setup_charm_dir(self):
        self._tmpdir = Path(tempfile.mkdtemp(prefix='tmp-ops-test-')).resolve()
        self.addCleanup(shutil.rmtree, str(self._tmpdir))
        self.JUJU_CHARM_DIR = self._tmpdir / 'test_main'
        self.CHARM_STATE_FILE = self.JUJU_CHARM_DIR / CHARM_STATE_FILE
        self.hooks_dir = self.JUJU_CHARM_DIR / 'hooks'
        charm_path = str(self.JUJU_CHARM_DIR / 'src/charm.py')
        self.charm_exec_path = os.path.relpath(charm_path, str(self.hooks_dir))
        shutil.copytree(str(TEST_CHARM_DIR), str(self.JUJU_CHARM_DIR))

        charm_spec = importlib.util.spec_from_file_location("charm", charm_path)
        self.charm_module = importlib.util.module_from_spec(charm_spec)
        charm_spec.loader.exec_module(self.charm_module)

        self._prepare_initial_hooks()

    def _prepare_initial_hooks(self):
        initial_hooks = ('install', 'start', 'upgrade-charm', 'disks-storage-attached')
        self.hooks_dir.mkdir()
        for hook in initial_hooks:
            self._setup_entry_point(self.hooks_dir, hook)

    def _prepare_actions(self):
        # TODO: jam 2020-06-16 this same work could be done just triggering the 'install' event
        #  of the charm, it might be cleaner to not set up entry points directly here.
        actions_dir_name = 'actions'
        actions_dir = self.JUJU_CHARM_DIR / actions_dir_name
        actions_dir.mkdir()
        for action_name in ('start', 'foo-bar', 'get-model-name', 'get-status'):
            self._setup_entry_point(actions_dir, action_name)

    def _read_and_clear_state(self):
        if self.CHARM_STATE_FILE.stat().st_size:
            storage = SQLiteStorage(self.CHARM_STATE_FILE)
            with (self.JUJU_CHARM_DIR / 'metadata.yaml').open() as m:
                af = (self.JUJU_CHARM_DIR / 'actions.yaml')
                if af.exists():
                    with af.open() as a:
                        meta = CharmMeta.from_yaml(m, a)
                else:
                    meta = CharmMeta.from_yaml(m)
            framework = Framework(storage, self.JUJU_CHARM_DIR, meta, None)

            class ThisCharmEvents(CharmEvents):
                pass

            class Charm(self.charm_module.Charm):
                on = ThisCharmEvents()

            mycharm = Charm(framework)
            stored = mycharm._stored
            # Override the saved data with a cleared state
            storage.save_snapshot(stored._data.handle.path, {})
            storage.commit()
            framework.close()
        else:
            stored = StoredStateData(None, None)
        return stored

    def _simulate_event(self, event_spec):
        ppath = Path(__file__).parent
        pypath = str(ppath.parent)
        if 'PYTHONPATH' in os.environ:
            pypath += os.pathsep + os.environ['PYTHONPATH']
        env = os.environ.copy()
        env.update({
            'PATH': os.pathsep.join([str(ppath / 'bin'), env['PATH']]),
            'PYTHONPATH': pypath,
            'JUJU_CHARM_DIR': str(self.JUJU_CHARM_DIR),
            'JUJU_UNIT_NAME': 'test_main/0',
        })
        if event_spec.set_in_env is not None:
            env.update(event_spec.set_in_env)
        if issubclass(event_spec.event_type, RelationEvent):
            rel_name = event_spec.event_name.split('_')[0]
            env.update({
                'JUJU_RELATION': rel_name,
                'JUJU_RELATION_ID': str(event_spec.relation_id),
            })
            remote_app = event_spec.remote_app
            # For juju < 2.7 app name is extracted from JUJU_REMOTE_UNIT.
            if remote_app is not None:
                env['JUJU_REMOTE_APP'] = remote_app

            remote_unit = event_spec.remote_unit
            if remote_unit is None:
                remote_unit = ''

            env['JUJU_REMOTE_UNIT'] = remote_unit
        else:
            env.update({
                'JUJU_REMOTE_UNIT': '',
                'JUJU_REMOTE_APP': '',
            })
        if issubclass(event_spec.event_type, ActionEvent):
            event_filename = event_spec.event_name[:-len('_action')].replace('_', '-')
            env.update({
                event_spec.env_var: event_filename,
            })
            if event_spec.env_var == 'JUJU_ACTION_NAME':
                event_dir = 'actions'
            else:
                raise RuntimeError('invalid envar name specified for a action event')
        else:
            event_filename = event_spec.event_name.replace('_', '-')
            event_dir = 'hooks'
        if event_spec.model_name is not None:
            env['JUJU_MODEL_NAME'] = event_spec.model_name

        self._call_event(Path(event_dir, event_filename), env)
        return self._read_and_clear_state()

    def test_event_reemitted(self):
        # First run "install" to make sure all hooks are set up.
        state = self._simulate_event(EventSpec(InstallEvent, 'install'))
        self.assertEqual(list(state.observed_event_types), ['InstallEvent'])

        state = self._simulate_event(EventSpec(ConfigChangedEvent, 'config-changed'))
        self.assertEqual(list(state.observed_event_types), ['ConfigChangedEvent'])

        # Re-emit should pick the deferred config-changed.
        state = self._simulate_event(EventSpec(UpdateStatusEvent, 'update-status'))
        self.assertEqual(
            list(state.observed_event_types),
            ['ConfigChangedEvent', 'UpdateStatusEvent'])

    def test_no_reemission_on_collect_metrics(self):
        fake_script(self, 'add-metric', 'exit 0')

        # First run "install" to make sure all hooks are set up.
        state = self._simulate_event(EventSpec(InstallEvent, 'install'))
        self.assertEqual(list(state.observed_event_types), ['InstallEvent'])

        state = self._simulate_event(EventSpec(ConfigChangedEvent, 'config-changed'))
        self.assertEqual(list(state.observed_event_types), ['ConfigChangedEvent'])

        # Re-emit should not pick the deferred config-changed because
        # collect-metrics runs in a restricted context.
        state = self._simulate_event(EventSpec(CollectMetricsEvent, 'collect-metrics'))
        self.assertEqual(list(state.observed_event_types), ['CollectMetricsEvent'])

    def test_multiple_events_handled(self):
        self._prepare_actions()

        fake_script(self, 'action-get', "echo '{}'")

        # Sample events with a different amount of dashes used
        # and with endpoints from different sections of metadata.yaml
        events_under_test = [(
            EventSpec(InstallEvent, 'install'),
            {},
        ), (
            EventSpec(StartEvent, 'start'),
            {},
        ), (
            EventSpec(UpdateStatusEvent, 'update_status'),
            {},
        ), (
            EventSpec(LeaderSettingsChangedEvent, 'leader_settings_changed'),
            {},
        ), (
            EventSpec(RelationJoinedEvent, 'db_relation_joined',
                      relation_id=1,
                      remote_app='remote', remote_unit='remote/0'),
            {'relation_name': 'db',
             'relation_id': 1,
             'app_name': 'remote',
             'unit_name': 'remote/0'},
        ), (
            EventSpec(RelationChangedEvent, 'mon_relation_changed',
                      relation_id=2,
                      remote_app='remote', remote_unit='remote/0'),
            {'relation_name': 'mon',
             'relation_id': 2,
             'app_name': 'remote',
             'unit_name': 'remote/0'},
        ), (
            EventSpec(RelationChangedEvent, 'mon_relation_changed',
                      relation_id=2,
                      remote_app='remote', remote_unit=None),
            {'relation_name': 'mon',
             'relation_id': 2,
             'app_name': 'remote',
             'unit_name': None},
        ), (
            EventSpec(RelationDepartedEvent, 'mon_relation_departed',
                      relation_id=2,
                      remote_app='remote', remote_unit='remote/0'),
            {'relation_name': 'mon',
             'relation_id': 2,
             'app_name': 'remote',
             'unit_name': 'remote/0'},
        ), (
            EventSpec(RelationBrokenEvent, 'ha_relation_broken',
                      relation_id=3),
            {'relation_name': 'ha',
             'relation_id': 3},
        ), (
            # Events without a remote app specified (for Juju < 2.7).
            EventSpec(RelationJoinedEvent, 'db_relation_joined',
                      relation_id=1,
                      remote_unit='remote/0'),
            {'relation_name': 'db',
             'relation_id': 1,
             'app_name': 'remote',
             'unit_name': 'remote/0'},
        ), (
            EventSpec(RelationChangedEvent, 'mon_relation_changed',
                      relation_id=2,
                      remote_unit='remote/0'),
            {'relation_name': 'mon',
             'relation_id': 2,
             'app_name': 'remote',
             'unit_name': 'remote/0'},
        ), (
            EventSpec(RelationDepartedEvent, 'mon_relation_departed',
                      relation_id=2,
                      remote_unit='remote/0'),
            {'relation_name': 'mon',
             'relation_id': 2,
             'app_name': 'remote',
             'unit_name': 'remote/0'},
        ), (
            EventSpec(ActionEvent, 'start_action',
                      env_var='JUJU_ACTION_NAME'),
            {},
        ), (
            EventSpec(ActionEvent, 'foo_bar_action',
                      env_var='JUJU_ACTION_NAME'),
            {},
        )]

        logger.debug('Expected events %s', events_under_test)

        # First run "install" to make sure all hooks are set up.
        self._simulate_event(EventSpec(InstallEvent, 'install'))

        # Simulate hook executions for every event.
        for event_spec, expected_event_data in events_under_test:
            state = self._simulate_event(event_spec)

            state_key = 'on_' + event_spec.event_name
            handled_events = getattr(state, state_key, [])

            # Make sure that a handler for that event was called once.
            self.assertEqual(len(handled_events), 1)
            # Make sure the event handled by the Charm has the right type.
            handled_event_type = handled_events[0]
            self.assertEqual(handled_event_type, event_spec.event_type.__name__)

            self.assertEqual(list(state.observed_event_types), [event_spec.event_type.__name__])

            if event_spec.event_name in expected_event_data:
                self.assertEqual(state[event_spec.event_name + '_data'],
                                 expected_event_data[event_spec.event_name])

    def test_event_not_implemented(self):
        """Make sure events without implementation do not cause non-zero exit."""
        # Simulate a scenario where there is a symlink for an event that
        # a charm does not know how to handle.
        hook_path = self.JUJU_CHARM_DIR / 'hooks/not-implemented-event'
        # This will be cleared up in tearDown.
        hook_path.symlink_to('install')

        try:
            self._simulate_event(EventSpec(HookEvent, 'not-implemented-event'))
        except subprocess.CalledProcessError:
            self.fail('Event simulation for an unsupported event'
                      ' results in a non-zero exit code returned')

    def test_no_actions(self):
        (self.JUJU_CHARM_DIR / 'actions.yaml').unlink()
        self._simulate_event(EventSpec(InstallEvent, 'install'))

    def test_empty_actions(self):
        (self.JUJU_CHARM_DIR / 'actions.yaml').write_text('')
        self._simulate_event(EventSpec(InstallEvent, 'install'))

    def test_collect_metrics(self):
        fake_script(self, 'add-metric', 'exit 0')
        self._simulate_event(EventSpec(InstallEvent, 'install'))
        # Clear the calls during 'install'
        fake_script_calls(self, clear=True)
        self._simulate_event(EventSpec(CollectMetricsEvent, 'collect_metrics'))

        expected = [
            VERSION_LOGLINE,
            ['juju-log', '--log-level', 'DEBUG', '--',
             'Using local storage: {} already exists'.format(self.CHARM_STATE_FILE)],
            ['juju-log', '--log-level', 'DEBUG', '--', 'Emitting Juju event collect_metrics.'],
            ['add-metric', '--labels', 'bar=4.2', 'foo=42'],
        ]
        if not yaml.__with_libyaml__:
            expected.insert(1, SLOW_YAML_LOGLINE)
        calls = fake_script_calls(self)

        if self.has_dispatch:
            expected.insert(1, [
                'juju-log', '--log-level', 'DEBUG', '--',
                'Legacy {} does not exist.'.format(Path('hooks/collect-metrics'))])

        self.assertEqual(calls, expected)

    def test_logger(self):
        fake_script(self, 'action-get', "echo '{}'")

        test_cases = [(
            EventSpec(ActionEvent, 'log_critical_action', env_var='JUJU_ACTION_NAME'),
            ['juju-log', '--log-level', 'CRITICAL', '--', 'super critical'],
        ), (
            EventSpec(ActionEvent, 'log_error_action',
                      env_var='JUJU_ACTION_NAME'),
            ['juju-log', '--log-level', 'ERROR', '--', 'grave error'],
        ), (
            EventSpec(ActionEvent, 'log_warning_action',
                      env_var='JUJU_ACTION_NAME'),
            ['juju-log', '--log-level', 'WARNING', '--', 'wise warning'],
        ), (
            EventSpec(ActionEvent, 'log_info_action',
                      env_var='JUJU_ACTION_NAME'),
            ['juju-log', '--log-level', 'INFO', '--', 'useful info'],
        )]

        # Set up action symlinks.
        self._simulate_event(EventSpec(InstallEvent, 'install'))

        for event_spec, calls in test_cases:
            self._simulate_event(event_spec)
            self.assertIn(calls, fake_script_calls(self, clear=True))

    @unittest.skipIf(is_windows, 'TODO windows multiline args are hard')
    def test_excepthook(self):
        with self.assertRaises(subprocess.CalledProcessError):
            self._simulate_event(EventSpec(InstallEvent, 'install',
                                           set_in_env={'TRY_EXCEPTHOOK': '1'}))

        calls = [' '.join(i) for i in fake_script_calls(self)]

        self.assertEqual(calls.pop(0), ' '.join(VERSION_LOGLINE))

        if self.has_dispatch:
            self.assertEqual(
                calls.pop(0),
                'juju-log --log-level DEBUG -- Legacy {} does not exist.'.format(
                    Path("hooks/install")))

        if not yaml.__with_libyaml__:
            self.assertEquals(calls.pop(0), ' '.join(SLOW_YAML_LOGLINE))

        self.assertRegex(calls.pop(0), 'Using local storage: not a kubernetes charm')

        self.maxDiff = None
        self.assertRegex(
            calls[0],
            '(?ms)juju-log --log-level ERROR -- Uncaught exception while in charm code:\n'
            'Traceback .most recent call last.:\n'
            '  .*'
            '    raise RuntimeError."failing as requested".\n'
            'RuntimeError: failing as requested'
        )
        self.assertEqual(len(calls), 1, "expected 1 call, but got extra: {}".format(calls[1:]))

    def test_sets_model_name(self):
        self._prepare_actions()

        fake_script(self, 'action-get', "echo '{}'")
        state = self._simulate_event(EventSpec(
            ActionEvent, 'get_model_name_action',
            env_var='JUJU_ACTION_NAME',
            model_name='test-model-name'))
        self.assertIsNotNone(state)
        self.assertEqual(state._on_get_model_name_action, ['test-model-name'])

    def test_has_valid_status(self):
        self._prepare_actions()

        fake_script(self, 'action-get', "echo '{}'")
        fake_script(self, 'status-get', """echo '{"status": "unknown", "message": ""}'""")
        state = self._simulate_event(EventSpec(
            ActionEvent, 'get_status_action',
            env_var='JUJU_ACTION_NAME'))
        self.assertIsNotNone(state)
        self.assertEqual(state.status_name, 'unknown')
        self.assertEqual(state.status_message, '')
        fake_script(
            self, 'status-get', """echo '{"status": "blocked", "message": "help meeee"}'""")
        state = self._simulate_event(EventSpec(
            ActionEvent, 'get_status_action',
            env_var='JUJU_ACTION_NAME'))
        self.assertIsNotNone(state)
        self.assertEqual(state.status_name, 'blocked')
        self.assertEqual(state.status_message, 'help meeee')


class TestMainWithNoDispatch(_TestMain, unittest.TestCase):
    has_dispatch = False
    hooks_are_symlinks = True

    def _setup_entry_point(self, directory, entry_point):
        path = directory / entry_point
        path.symlink_to(self.charm_exec_path)

    def _call_event(self, rel_path, env):
        env['JUJU_VERSION'] = '2.7.0'
        event_file = self.JUJU_CHARM_DIR / rel_path
        # Note that sys.executable is used to make sure we are using the same
        # interpreter for the child process to support virtual environments.
        subprocess.run(
            [sys.executable, str(event_file)],
            check=True, env=env, cwd=str(self.JUJU_CHARM_DIR))

    def test_setup_event_links(self):
        """Test auto-creation of symlinks caused by initial events."""
        all_event_hooks = ['hooks/' + e.replace("_", "-")
                           for e in self.charm_module.Charm.on.events().keys()]
        initial_events = {
            EventSpec(InstallEvent, 'install'),
            EventSpec(StorageAttachedEvent, 'disks-storage-attached'),
            EventSpec(StartEvent, 'start'),
            EventSpec(UpgradeCharmEvent, 'upgrade-charm'),
        }
        initial_hooks = {'hooks/' + ev.event_name for ev in initial_events}

        def _assess_event_links(event_spec):
            self.assertTrue(self.hooks_dir / event_spec.event_name in self.hooks_dir.iterdir())
            for event_hook in all_event_hooks:
                hook_path = self.JUJU_CHARM_DIR / event_hook
                self.assertTrue(hook_path.exists(), 'Missing hook: ' + event_hook)
                if self.hooks_are_symlinks:
                    self.assertTrue(hook_path.is_symlink())
                    if not is_windows:
                        # TODO(benhoyt): fix this now that tests are running on GitHub Actions
                        self.assertEqual(os.readlink(str(hook_path)), self.charm_exec_path)
                elif event_hook in initial_hooks:
                    self.assertFalse(hook_path.is_symlink())
                else:
                    # hooks are not symlinks, and this hook is not one of the initial ones
                    # check that it's a symlink to the inital ones
                    self.assertTrue(hook_path.is_symlink())
                    self.assertEqual(os.readlink(str(hook_path)), event_spec.event_name)

        for initial_event in initial_events:
            self._setup_charm_dir()

            self._simulate_event(initial_event)
            _assess_event_links(initial_event)
            # Make sure it is idempotent.
            self._simulate_event(initial_event)
            _assess_event_links(initial_event)

    def test_setup_action_links(self):
        self._simulate_event(EventSpec(InstallEvent, 'install'))
        # foo-bar is one of the actions defined in actions.yaml
        action_hook = self.JUJU_CHARM_DIR / 'actions' / 'foo-bar'
        self.assertTrue(action_hook.exists())


class TestMainWithNoDispatchButJujuIsDispatchAware(TestMainWithNoDispatch):
    def _call_event(self, rel_path, env):
        env['JUJU_DISPATCH_PATH'] = str(rel_path)
        env['JUJU_VERSION'] = '2.8.0'
        super()._call_event(rel_path, env)


class TestMainWithNoDispatchButDispatchPathIsSet(TestMainWithNoDispatch):
    def _call_event(self, rel_path, env):
        env['JUJU_DISPATCH_PATH'] = str(rel_path)
        super()._call_event(rel_path, env)


class TestMainWithNoDispatchButScriptsAreCopies(TestMainWithNoDispatch):
    hooks_are_symlinks = False

    def _setup_entry_point(self, directory, entry_point):
        charm_path = str(self.JUJU_CHARM_DIR / 'src/charm.py')
        path = directory / entry_point
        shutil.copy(charm_path, str(path))


class _TestMainWithDispatch(_TestMain):
    has_dispatch = True

    def test_setup_event_links(self):
        """Test auto-creation of symlinks caused by initial events does _not_ happen when using dispatch.
        """
        all_event_hooks = ['hooks/' + e.replace("_", "-")
                           for e in self.charm_module.Charm.on.events().keys()]
        initial_events = {
            EventSpec(InstallEvent, 'install'),
            EventSpec(StorageAttachedEvent, 'disks-storage-attached'),
            EventSpec(StartEvent, 'start'),
            EventSpec(UpgradeCharmEvent, 'upgrade-charm'),
        }

        def _assess_event_links(event_spec):
            self.assertNotIn(self.hooks_dir / event_spec.event_name, self.hooks_dir.iterdir())
            for event_hook in all_event_hooks:
                self.assertFalse((self.JUJU_CHARM_DIR / event_hook).exists(),
                                 'Spurious hook: ' + event_hook)

        for initial_event in initial_events:
            self._setup_charm_dir()

            self._simulate_event(initial_event)
            _assess_event_links(initial_event)

    def test_hook_and_dispatch(self):
        old_path = self.fake_script_path
        self.fake_script_path = self.hooks_dir
        fake_script(self, 'install', 'exit 0')
        state = self._simulate_event(EventSpec(InstallEvent, 'install'))

        # the script was called, *and*, the .on. was called
        self.assertEqual(fake_script_calls(self), [['install', '']])
        self.assertEqual(list(state.observed_event_types), ['InstallEvent'])

        self.fake_script_path = old_path
        hook = Path('hooks/install')
        expected = [
            VERSION_LOGLINE,
            ['juju-log', '--log-level', 'INFO', '--',
             'Running legacy {}.'.format(hook)],
            ['juju-log', '--log-level', 'DEBUG', '--',
             'Legacy {} exited with status 0.'.format(hook)],
            ['juju-log', '--log-level', 'DEBUG', '--',
             'Using local storage: not a kubernetes charm'],
            ['juju-log', '--log-level', 'DEBUG', '--',
             'Emitting Juju event install.'],
        ]
        if not yaml.__with_libyaml__:
            expected.insert(3, SLOW_YAML_LOGLINE)
        self.assertEqual(fake_script_calls(self), expected)

    @unittest.skipIf(is_windows, "this is UNIXish; TODO: write equivalent windows test")
    def test_non_executable_hook_and_dispatch(self):
        (self.hooks_dir / "install").write_text("")
        state = self._simulate_event(EventSpec(InstallEvent, 'install'))

        self.assertEqual(list(state.observed_event_types), ['InstallEvent'])

        expected = [
            VERSION_LOGLINE,
            ['juju-log', '--log-level', 'WARNING', '--',
             'Legacy hooks/install exists but is not executable.'],
            ['juju-log', '--log-level', 'DEBUG', '--',
             'Using local storage: not a kubernetes charm'],
            ['juju-log', '--log-level', 'DEBUG', '--',
             'Emitting Juju event install.'],
        ]
        if not yaml.__with_libyaml__:
            expected.insert(2, SLOW_YAML_LOGLINE)
        self.assertEqual(fake_script_calls(self), expected)

    def test_hook_and_dispatch_with_failing_hook(self):
        self.stdout = self.stderr = tempfile.TemporaryFile()
        self.addCleanup(self.stdout.close)

        old_path = self.fake_script_path
        self.fake_script_path = self.hooks_dir
        fake_script(self, 'install', 'exit 42')
        event = EventSpec(InstallEvent, 'install')
        with self.assertRaises(subprocess.CalledProcessError):
            self._simulate_event(event)
        self.fake_script_path = old_path

        self.stdout.seek(0)
        self.assertEqual(self.stdout.read(), b'')
        calls = fake_script_calls(self)
        hook = Path('hooks/install')
        expected = [
            VERSION_LOGLINE,
            ['juju-log', '--log-level', 'INFO', '--', 'Running legacy {}.'.format(hook)],
            ['juju-log', '--log-level', 'WARNING', '--',
             'Legacy {} exited with status 42.'.format(hook)],
        ]
        self.assertEqual(calls, expected)

    def test_hook_and_dispatch_but_hook_is_dispatch(self):
        event = EventSpec(InstallEvent, 'install')
        hook_path = self.hooks_dir / 'install'
        if is_windows:
            hook_path = hook_path.with_suffix('.bat')
        for ((rel, ind), path) in {
                # relative and indirect
                (True, True): Path('../dispatch'),
                # relative and direct
                (True, False): Path(self.charm_exec_path),
                # absolute and direct
                (False, False): (self.hooks_dir / self.charm_exec_path).resolve(),
                # absolute and indirect
                (False, True): self.JUJU_CHARM_DIR / 'dispatch',
        }.items():
            with self.subTest(path=path, rel=rel, ind=ind):
                if is_windows:
                    path = path.with_suffix('.sh')
                # sanity check
                self.assertEqual(path.is_absolute(), not rel)
                self.assertEqual(path.with_suffix('').name == 'dispatch', ind)
                try:
                    hook_path.symlink_to(path)

                    state = self._simulate_event(event)

                    # the .on. was only called once
                    self.assertEqual(list(state.observed_event_types), ['InstallEvent'])
                    self.assertEqual(list(state.on_install), ['InstallEvent'])
                finally:
                    hook_path.unlink()

    @unittest.skipIf(is_windows, "this needs rethinking on Windows")
    def test_hook_and_dispatch_but_hook_is_dispatch_copy(self):
        hook_path = self.hooks_dir / 'install'
        path = (self.hooks_dir / self.charm_exec_path).resolve()
        shutil.copy(str(path), str(hook_path))

        event = EventSpec(InstallEvent, 'install')
        state = self._simulate_event(event)

        # the .on. was only called once
        self.assertEqual(list(state.observed_event_types), ['InstallEvent'])
        self.assertEqual(list(state.on_install), ['InstallEvent'])
        hook = Path('hooks/install')
        expected = [
            VERSION_LOGLINE,
            ['juju-log', '--log-level', 'INFO', '--',
             'Running legacy {}.'.format(hook)],
            VERSION_LOGLINE,    # because it called itself
            ['juju-log', '--log-level', 'DEBUG', '--',
             'Charm called itself via {}.'.format(hook)],
            ['juju-log', '--log-level', 'DEBUG', '--',
             'Legacy {} exited with status 0.'.format(hook)],
            ['juju-log', '--log-level', 'DEBUG', '--',
             'Using local storage: not a kubernetes charm'],
            ['juju-log', '--log-level', 'DEBUG', '--',
             'Emitting Juju event install.'],
        ]
        if not yaml.__with_libyaml__:
            expected.insert(5, SLOW_YAML_LOGLINE)
        self.assertEqual(fake_script_calls(self), expected)


# NOTE
#  AIUI On windows dispatch must be a script (see TestMainWithDispatchAsScript),
#  because Juju won't call python even if we rename dispatch to dispatch.py
@unittest.skipIf(is_windows, "Juju on windows won't make this work (see note)")
class TestMainWithDispatch(_TestMainWithDispatch, unittest.TestCase):
    def _setup_entry_point(self, directory, entry_point):
        path = self.JUJU_CHARM_DIR / 'dispatch'
        if not path.exists():
            path.symlink_to(os.path.join('src', 'charm.py'))

    def _call_event(self, rel_path, env):
        env['JUJU_DISPATCH_PATH'] = str(rel_path)
        env['JUJU_VERSION'] = '2.8.0'
        dispatch = self.JUJU_CHARM_DIR / 'dispatch'
        subprocess.run(
            [sys.executable, str(dispatch)],
            # stdout=self.stdout,
            # stderr=self.stderr,
            check=True, env=env, cwd=str(self.JUJU_CHARM_DIR))


class TestMainWithDispatchAsScript(_TestMainWithDispatch, unittest.TestCase):
    """Here dispatch is a script that execs the charm.py instead of a symlink."""

    has_dispatch = True

    if is_windows:
        suffix = '.BAT'
        script = '@ECHO OFF\n"{}" "{}"\n'
    else:
        suffix = ''
        script = '#!/bin/sh\nexec "{}" "{}"\n'

    def _setup_entry_point(self, directory, entry_point):
        path = (self.JUJU_CHARM_DIR / 'dispatch').with_suffix(self.suffix)
        if not path.exists():
            path.write_text(self.script.format(
                sys.executable,
                self.JUJU_CHARM_DIR / 'src/charm.py'))
            path.chmod(0o755)

    def _call_event(self, rel_path, env):
        env['JUJU_DISPATCH_PATH'] = str(rel_path)
        env['JUJU_VERSION'] = '2.8.0'
        dispatch = (self.JUJU_CHARM_DIR / 'dispatch').with_suffix(self.suffix)
        subprocess.check_call([str(dispatch)], env=env, cwd=str(self.JUJU_CHARM_DIR))


class TestStorageHeuristics(unittest.TestCase):
    def setUp(self):
        logassert.setup(self, '')

    def test_fallback_to_current_juju_version__too_old(self):
        meta = CharmMeta.from_yaml("series: [kubernetes]")
        with patch.dict(os.environ, {"JUJU_VERSION": "1.0"}):
            self.assertFalse(_should_use_controller_storage(Path("/xyzzy"), meta))
            self.assertLogged('Using local storage: JUJU_VERSION=1.0.0')

    def test_fallback_to_current_juju_version__new_enough(self):
        meta = CharmMeta.from_yaml("series: [kubernetes]")
        with patch.dict(os.environ, {"JUJU_VERSION": "2.8"}):
            self.assertTrue(_should_use_controller_storage(Path("/xyzzy"), meta))
            self.assertLogged('Using controller storage: JUJU_VERSION=2.8.0')

    def test_not_if_not_in_k8s(self):
        meta = CharmMeta.from_yaml("series: [ecs]")
        with patch.dict(os.environ, {"JUJU_VERSION": "2.8"}):
            self.assertFalse(_should_use_controller_storage(Path("/xyzzy"), meta))
            self.assertLogged('Using local storage: not a kubernetes charm')

    def test_not_if_already_local(self):
        meta = CharmMeta.from_yaml("series: [kubernetes]")
        with patch.dict(os.environ, {"JUJU_VERSION": "2.8"}), tempfile.NamedTemporaryFile() as fd:
            self.assertFalse(_should_use_controller_storage(Path(fd.name), meta))
            self.assertLogged('Using local storage: {} already exists'.format(fd.name))
