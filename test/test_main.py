# Copyright 2019-2021 Canonical Ltd.
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
import importlib.util
import io
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import typing
import unittest
import warnings
from pathlib import Path
from unittest.mock import patch

import ops
from ops.main import CHARM_STATE_FILE, _should_use_controller_storage
from ops.storage import SQLiteStorage

from .charms.test_main.src.charm import MyCharmEvents
from .test_helpers import fake_script, fake_script_calls

# This relies on the expected repository structure to find a path to
# source of the charm under test.
TEST_CHARM_DIR = Path(f"{__file__}/../charms/test_main").resolve()

VERSION_LOGLINE = [
    'juju-log', '--log-level', 'DEBUG', '--',
    f'ops {ops.__version__} up and running.',
]

logger = logging.getLogger(__name__)


class SymlinkTargetError(Exception):
    pass


class EventSpec:
    def __init__(self,
                 event_type: typing.Type[ops.EventBase],
                 event_name: str,
                 env_var: typing.Optional[str] = None,
                 relation_id: typing.Optional[int] = None,
                 remote_app: typing.Optional[str] = None,
                 remote_unit: typing.Optional[str] = None,
                 model_name: typing.Optional[str] = None,
                 set_in_env: typing.Optional[typing.Dict[str,
                                                         str]] = None,
                 workload_name: typing.Optional[str] = None,
                 departing_unit_name: typing.Optional[str] = None,
                 secret_id: typing.Optional[str] = None,
                 secret_label: typing.Optional[str] = None,
                 secret_revision: typing.Optional[str] = None):
        self.event_type = event_type
        self.event_name = event_name
        self.env_var = env_var
        self.relation_id = relation_id
        self.remote_app = remote_app
        self.remote_unit = remote_unit
        self.departing_unit_name = departing_unit_name
        self.model_name = model_name
        self.set_in_env = set_in_env
        self.workload_name = workload_name
        self.secret_id = secret_id
        self.secret_label = secret_label
        self.secret_revision = secret_revision


@patch('ops.main.setup_root_logging', new=lambda *a, **kw: None)  # type: ignore
@patch('ops.main._emit_charm_event', new=lambda *a, **kw: None)  # type: ignore
@patch('ops.charm._evaluate_status', new=lambda *a, **kw: None)  # type: ignore
class CharmInitTestCase(unittest.TestCase):

    @patch('sys.stderr', new_callable=io.StringIO)
    def test_breakpoint(self, fake_stderr: io.StringIO):
        class MyCharm(ops.CharmBase):
            pass
        self._check(MyCharm, extra_environ={'JUJU_DEBUG_AT': 'all'})

        with patch('pdb.Pdb.set_trace') as mock:
            breakpoint()

        self.assertEqual(mock.call_count, 1)
        self.assertIn('Starting pdb to debug charm operator', fake_stderr.getvalue())

    def test_no_debug_breakpoint(self):
        class MyCharm(ops.CharmBase):
            pass
        self._check(MyCharm, extra_environ={'JUJU_DEBUG_AT': ''})

        with patch('pdb.Pdb.set_trace') as mock:
            breakpoint()

        self.assertEqual(mock.call_count, 0)

    def _check(
            self,
            charm_class: typing.Type[ops.CharmBase],
            *,
            extra_environ: typing.Optional[typing.Dict[str, str]] = None,
            **kwargs: typing.Any
    ):
        """Helper for below tests."""
        fake_environ = {
            'JUJU_UNIT_NAME': 'test_main/0',
            'JUJU_MODEL_NAME': 'mymodel',
            'JUJU_VERSION': '2.7.0',
        }
        if extra_environ is not None:
            fake_environ.update(extra_environ)
        with patch.dict(os.environ, fake_environ):
            with patch('ops.main._get_charm_dir') as mock_charmdir:
                with tempfile.TemporaryDirectory() as tmpdirname:
                    tmpdirname = Path(tmpdirname)
                    fake_metadata = tmpdirname / 'metadata.yaml'
                    with fake_metadata.open('wb') as fh:
                        fh.write(b'name: test')
                    mock_charmdir.return_value = tmpdirname

                    ops.main(charm_class, **kwargs)  # type: ignore

    def test_init_signature_passthrough(self):
        class MyCharm(ops.CharmBase):

            def __init__(self, *args):  # type: ignore
                super().__init__(*args)  # type: ignore

        with warnings.catch_warnings(record=True) as warn_cm:
            self._check(MyCharm)
        self.assertEqual(warn_cm, [])

    def test_init_signature_old_key_argument(self):
        class MyCharm(ops.CharmBase):

            def __init__(self, framework: ops.Framework, somekey: typing.Any):
                super().__init__(framework, somekey)  # type: ignore

        # Support for "key" has been deprecated since ops 0.7 and was removed in 2.0
        with self.assertRaises(TypeError):
            self._check(MyCharm)

    def test_init_signature_only_framework(self):
        class MyCharm(ops.CharmBase):

            def __init__(self, framework: ops.Framework):
                super().__init__(framework)

        with warnings.catch_warnings(record=True) as warn_cm:
            self._check(MyCharm)
        self.assertEqual(warn_cm, [])

    def test_storage_no_storage(self):
        # here we patch juju_backend_available so it refuses to set it up
        with patch('ops.storage.juju_backend_available') as juju_backend_available:
            juju_backend_available.return_value = False
            with self.assertRaisesRegex(
                    RuntimeError,
                    'charm set use_juju_for_storage=True, but Juju .* does not support it'):
                self._check(ops.CharmBase, use_juju_for_storage=True)

    def test_storage_with_storage(self):
        # here we patch juju_backend_available, so it gets set up and falls over when used
        with patch('ops.storage.juju_backend_available') as juju_backend_available:
            juju_backend_available.return_value = True
            with self.assertRaisesRegex(FileNotFoundError, 'state-get'):
                self._check(ops.CharmBase, use_juju_for_storage=True)

    def test_controller_storage_deprecated(self):
        with patch('ops.storage.juju_backend_available') as juju_backend_available:
            juju_backend_available.return_value = True
            with self.assertWarnsRegex(DeprecationWarning, 'Controller storage'):
                with self.assertRaisesRegex(FileNotFoundError, 'state-get'):
                    self._check(ops.CharmBase, use_juju_for_storage=True)


@patch('sys.argv', new=("hooks/config-changed",))
@patch('ops.main.setup_root_logging', new=lambda *a, **kw: None)  # type: ignore
@patch('ops.charm._evaluate_status', new=lambda *a, **kw: None)  # type: ignore
class TestDispatch(unittest.TestCase):
    def _check(self, *, with_dispatch: bool = False, dispatch_path: str = ''):
        """Helper for below tests."""
        class MyCharm(ops.CharmBase):
            def __init__(self, framework: ops.Framework):
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
                        ops.main(MyCharm)  # type: ignore

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


_event_test = typing.List[typing.Tuple[
    EventSpec,
    typing.Dict[str, typing.Union[str, int, None]]]]


class _TestMain(abc.ABC):

    @abc.abstractmethod
    def _setup_entry_point(self, directory: Path, entry_point: str):
        """Set up the given entry point in the given directory.

        If not using dispatch, that would be a symlink <dir>/<entry_point>
        pointing at src/charm.py; if using dispatch that would be the dispatch
        symlink. It could also not be a symlink...
        """
        return NotImplemented

    @abc.abstractmethod
    def _call_event(self, rel_path: Path, env: typing.Dict[str, str]):
        """Set up the environment and call (i.e. run) the given event."""
        return NotImplemented

    @abc.abstractmethod
    def test_setup_event_links(self):
        """Test auto-creation of symlinks caused by initial events.

        Depending on the combination of dispatch and non-dispatch, this should
        be checking for the creation or the _lack_ of creation, as appropriate.
        """
        return NotImplemented

    addCleanup = unittest.TestCase.addCleanup  # noqa
    assertEqual = unittest.TestCase.assertEqual  # noqa
    assertFalse = unittest.TestCase.assertFalse  # noqa
    assertIn = unittest.TestCase.assertIn  # noqa
    assertIsNotNone = unittest.TestCase.assertIsNotNone  # noqa
    assertRaises = unittest.TestCase.assertRaises  # noqa
    assertRegex = unittest.TestCase.assertRegex  # noqa
    assertNotIn = unittest.TestCase.assertNotIn  # noqa
    fail = unittest.TestCase.fail
    subTest = unittest.TestCase.subTest  # noqa

    def setUp(self):
        self._setup_charm_dir()

        # Relations events are defined dynamically and modify the class attributes.
        # We use a subclass temporarily to prevent these side effects from leaking.
        class TestCharmEvents(ops.CharmEvents):
            pass
        ops.CharmBase.on = TestCharmEvents()  # type: ignore

        def cleanup():
            ops.CharmBase.on = ops.CharmEvents()  # type: ignore
        self.addCleanup(cleanup)

        fake_script(typing.cast(unittest.TestCase, self), 'is-leader', 'echo true')
        fake_script(typing.cast(unittest.TestCase, self), 'juju-log', 'exit 0')

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
        assert charm_spec is not None
        self.charm_module = importlib.util.module_from_spec(charm_spec)
        assert charm_spec.loader is not None
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

    def _read_and_clear_state(self,
                              event_name: str) -> typing.Union[ops.BoundStoredState,
                                                               ops.StoredStateData]:
        if self.CHARM_STATE_FILE.stat().st_size:
            storage = SQLiteStorage(self.CHARM_STATE_FILE)
            with (self.JUJU_CHARM_DIR / 'metadata.yaml').open() as m:
                af = (self.JUJU_CHARM_DIR / 'actions.yaml')
                if af.exists():
                    with af.open() as a:
                        meta = ops.CharmMeta.from_yaml(m, a)
                else:
                    meta = ops.CharmMeta.from_yaml(m)
            framework = ops.Framework(storage, self.JUJU_CHARM_DIR, meta,
                                      None, event_name)  # type: ignore

            class ThisCharmEvents(MyCharmEvents):
                pass

            class _HasStored(typing.Protocol):
                _stored: ops.StoredState

            class Charm(self.charm_module.Charm, _HasStored):  # type: ignore
                on = ThisCharmEvents()

            mycharm = Charm(framework)
            stored = mycharm._stored
            # Override the saved data with a cleared state
            storage.save_snapshot(stored._data.handle.path, {})
            storage.commit()
            framework.close()
        else:
            stored = ops.StoredStateData(None, None)  # type: ignore
        return stored

    def _simulate_event(self, event_spec: EventSpec):
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
        if issubclass(event_spec.event_type, ops.SecretEvent):
            assert event_spec.secret_id is not None
            env.update({
                'JUJU_SECRET_ID': event_spec.secret_id,
                'JUJU_SECRET_LABEL': event_spec.secret_label or '',
            })
        if issubclass(event_spec.event_type, (ops.SecretRemoveEvent, ops.SecretExpiredEvent)):
            env.update({
                'JUJU_SECRET_REVISION': str(event_spec.secret_revision or ''),
            })
        if issubclass(event_spec.event_type, ops.RelationEvent):
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

            departing_unit_name = event_spec.departing_unit_name
            if departing_unit_name is None:
                departing_unit_name = ''
            env['JUJU_DEPARTING_UNIT'] = departing_unit_name
        else:
            env.update({
                'JUJU_REMOTE_UNIT': '',
                'JUJU_REMOTE_APP': '',
            })
        if issubclass(event_spec.event_type, ops.WorkloadEvent):
            assert event_spec.workload_name is not None
            env.update({
                'JUJU_WORKLOAD_NAME': event_spec.workload_name,
            })
        if issubclass(event_spec.event_type, ops.ActionEvent):
            event_filename = event_spec.event_name[:-len('_action')].replace('_', '-')
            assert event_spec.env_var is not None
            env.update({
                event_spec.env_var: event_filename,
            })
            if event_spec.env_var == 'JUJU_ACTION_NAME':
                event_dir = 'actions'
            else:
                raise RuntimeError('invalid envar name specified for an action event')
        else:
            event_filename = event_spec.event_name.replace('_', '-')
            event_dir = 'hooks'
        if event_spec.model_name is not None:
            env['JUJU_MODEL_NAME'] = event_spec.model_name

        self._call_event(Path(event_dir, event_filename), env)
        return self._read_and_clear_state(event_spec.event_name)

    def test_event_reemitted(self):
        # First run "install" to make sure all hooks are set up.
        state = self._simulate_event(EventSpec(ops.InstallEvent, 'install'))
        assert isinstance(state, ops.BoundStoredState)
        self.assertEqual(list(state.observed_event_types), ['InstallEvent'])

        state = self._simulate_event(EventSpec(ops.ConfigChangedEvent, 'config-changed'))
        assert isinstance(state, ops.BoundStoredState)
        self.assertEqual(list(state.observed_event_types), ['ConfigChangedEvent'])

        # Re-emit should pick the deferred config-changed.
        state = self._simulate_event(EventSpec(ops.UpdateStatusEvent, 'update-status'))
        assert isinstance(state, ops.BoundStoredState)
        self.assertEqual(
            list(state.observed_event_types),
            ['ConfigChangedEvent', 'UpdateStatusEvent'])

    def test_no_reemission_on_collect_metrics(self):
        fake_script(typing.cast(unittest.TestCase, self), 'add-metric', 'exit 0')

        # First run "install" to make sure all hooks are set up.
        state = self._simulate_event(EventSpec(ops.InstallEvent, 'install'))
        assert isinstance(state, ops.BoundStoredState)
        self.assertEqual(list(state.observed_event_types), ['InstallEvent'])

        state = self._simulate_event(EventSpec(ops.ConfigChangedEvent, 'config-changed'))
        assert isinstance(state, ops.BoundStoredState)
        self.assertEqual(list(state.observed_event_types), ['ConfigChangedEvent'])

        # Re-emit should not pick the deferred config-changed because
        # collect-metrics runs in a restricted context.
        state = self._simulate_event(EventSpec(ops.CollectMetricsEvent, 'collect-metrics'))
        assert isinstance(state, ops.BoundStoredState)
        self.assertEqual(list(state.observed_event_types), ['CollectMetricsEvent'])

    def test_multiple_events_handled(self):
        self._prepare_actions()

        fake_script(typing.cast(unittest.TestCase, self), 'action-get', "echo '{}'")

        # Sample events with a different amount of dashes used
        # and with endpoints from different sections of metadata.yaml
        events_under_test: _event_test = [(
            EventSpec(ops.InstallEvent, 'install'),
            {},
        ), (
            EventSpec(ops.StartEvent, 'start'),
            {},
        ), (
            EventSpec(ops.UpdateStatusEvent, 'update_status'),
            {},
        ), (
            EventSpec(ops.LeaderSettingsChangedEvent, 'leader_settings_changed'),
            {},
        ), (
            EventSpec(ops.RelationJoinedEvent, 'db_relation_joined',
                      relation_id=1,
                      remote_app='remote',
                      remote_unit='remote/0'),
            {'relation_name': 'db',
             'relation_id': 1,
             'app_name': 'remote',
             'unit_name': 'remote/0'},
        ), (
            EventSpec(ops.RelationChangedEvent, 'mon_relation_changed',
                      relation_id=2,
                      remote_app='remote',
                      remote_unit='remote/0'),
            {'relation_name': 'mon',
             'relation_id': 2,
             'app_name': 'remote',
             'unit_name': 'remote/0'},
        ), (
            EventSpec(ops.RelationChangedEvent, 'mon_relation_changed',
                      relation_id=2,
                      remote_app='remote',
                      remote_unit=None),
            {'relation_name': 'mon',
             'relation_id': 2,
             'app_name': 'remote'},
        ), (
            EventSpec(ops.RelationDepartedEvent, 'mon_relation_departed',
                      relation_id=2,
                      remote_app='remote',
                      remote_unit='remote/0',
                      departing_unit_name='remote/42'),
            {'relation_name': 'mon',
             'relation_id': 2,
             'app_name': 'remote',
             'unit_name': 'remote/0',
             'departing_unit': 'remote/42'},
        ), (
            EventSpec(ops.RelationBrokenEvent, 'ha_relation_broken',
                      relation_id=3),
            {'relation_name': 'ha',
             'relation_id': 3},
        ), (
            # Events without a remote app specified (for Juju < 2.7).
            EventSpec(ops.RelationJoinedEvent, 'db_relation_joined',
                      relation_id=1,
                      remote_unit='remote/0'),
            {'relation_name': 'db',
             'relation_id': 1,
             'app_name': 'remote',
             'unit_name': 'remote/0'},
        ), (
            EventSpec(ops.RelationChangedEvent, 'mon_relation_changed',
                      relation_id=2,
                      remote_unit='remote/0'),
            {'relation_name': 'mon',
             'relation_id': 2,
             'app_name': 'remote',
             'unit_name': 'remote/0'},
        ), (
            EventSpec(ops.RelationDepartedEvent, 'mon_relation_departed',
                      relation_id=2,
                      remote_unit='remote/0',
                      departing_unit_name='remote/42'),
            {'relation_name': 'mon',
             'relation_id': 2,
             'app_name': 'remote',
             'unit_name': 'remote/0',
             'departing_unit': 'remote/42'},
        ), (
            EventSpec(ops.ActionEvent, 'start_action',
                      env_var='JUJU_ACTION_NAME'),
            {},
        ), (
            EventSpec(ops.ActionEvent, 'foo_bar_action',
                      env_var='JUJU_ACTION_NAME'),
            {},
        ), (
            EventSpec(ops.PebbleReadyEvent, 'test_pebble_ready',
                      workload_name='test'),
            {'container_name': 'test'},
        ), (
            EventSpec(ops.SecretChangedEvent, 'secret_changed',
                      secret_id='secret:12345',
                      secret_label='foo'),
            {'id': 'secret:12345',
             'label': 'foo'}
        ), (
            EventSpec(ops.SecretRotateEvent, 'secret_rotate',
                      secret_id='secret:12345',
                      secret_label='foo',
                      secret_revision='42'),
            {'id': 'secret:12345',
             'label': 'foo'}
        ), (
            EventSpec(ops.SecretRemoveEvent, 'secret_remove',
                      secret_id='secret:12345',
                      secret_label='foo',
                      secret_revision='42'),
            {'id': 'secret:12345',
             'label': 'foo',
             'revision': 42}
        ), (
            EventSpec(ops.SecretExpiredEvent, 'secret_expired',
                      secret_id='secret:12345',
                      secret_label='foo',
                      secret_revision='42'),
            {'id': 'secret:12345',
             'label': 'foo',
             'revision': 42}
        )]

        logger.debug('Expected events %s', events_under_test)

        # First run "install" to make sure all hooks are set up.
        self._simulate_event(EventSpec(ops.InstallEvent, 'install'))

        # Simulate hook executions for every event.
        for event_spec, expected_event_data in events_under_test:
            state = self._simulate_event(event_spec)
            assert isinstance(state, ops.BoundStoredState)

            state_key = f"on_{event_spec.event_name}"
            handled_events = getattr(state, state_key, [])

            # Make sure that a handler for that event was called once.
            self.assertEqual(len(handled_events), 1)
            # Make sure the event handled by the Charm has the right type.
            handled_event_type = handled_events[0]
            self.assertEqual(handled_event_type, event_spec.event_type.__name__)

            self.assertEqual(list(state.observed_event_types), [event_spec.event_type.__name__])

            if expected_event_data:
                self.assertEqual(getattr(state, f"{event_spec.event_name}_data"),
                                 expected_event_data)

    def test_event_not_implemented(self):
        """Make sure events without implementation do not cause non-zero exit."""
        # Simulate a scenario where there is a symlink for an event that
        # a charm does not know how to handle.
        hook_path = self.JUJU_CHARM_DIR / 'hooks/not-implemented-event'
        # This will be cleared up in tearDown.
        hook_path.symlink_to('install')

        try:
            self._simulate_event(EventSpec(ops.HookEvent, 'not-implemented-event'))
        except subprocess.CalledProcessError:
            self.fail('Event simulation for an unsupported event'
                      ' results in a non-zero exit code returned')

    def test_no_actions(self):
        (self.JUJU_CHARM_DIR / 'actions.yaml').unlink()
        self._simulate_event(EventSpec(ops.InstallEvent, 'install'))

    def test_empty_actions(self):
        (self.JUJU_CHARM_DIR / 'actions.yaml').write_text('')
        self._simulate_event(EventSpec(ops.InstallEvent, 'install'))

    def test_collect_metrics(self):
        fake_script(typing.cast(unittest.TestCase, self), 'add-metric', 'exit 0')
        self._simulate_event(EventSpec(ops.InstallEvent, 'install'))
        # Clear the calls during 'install'
        fake_script_calls(typing.cast(unittest.TestCase, self), clear=True)
        self._simulate_event(EventSpec(ops.CollectMetricsEvent, 'collect_metrics'))

        expected = [
            VERSION_LOGLINE,
            ['juju-log', '--log-level', 'DEBUG', '--', 'Emitting Juju event collect_metrics.'],
            ['add-metric', '--labels', 'bar=4.2', 'foo=42'],
            ['is-leader', '--format=json'],
        ]
        calls = fake_script_calls(typing.cast(unittest.TestCase, self))

        self.assertEqual(calls, expected)

    def test_custom_event(self):
        self._simulate_event(EventSpec(ops.InstallEvent, 'install'))
        # Clear the calls during 'install'
        fake_script_calls(typing.cast(unittest.TestCase, self), clear=True)
        self._simulate_event(EventSpec(ops.UpdateStatusEvent, 'update-status',
                                       set_in_env={'EMIT_CUSTOM_EVENT': "1"}))

        calls = fake_script_calls(typing.cast(unittest.TestCase, self))

        custom_event_prefix = 'Emitting custom event <CustomEvent via Charm/on/custom'
        expected = [
            VERSION_LOGLINE,
            ['juju-log', '--log-level', 'DEBUG', '--', 'Emitting Juju event update_status.'],
            ['juju-log', '--log-level', 'DEBUG', '--', custom_event_prefix],
            ['is-leader', '--format=json'],
        ]
        # Remove the "[key]>" suffix from the end of the event string
        self.assertRegex(calls[2][-1], re.escape(custom_event_prefix) + '.*')
        calls[2][-1] = custom_event_prefix
        self.assertEqual(calls, expected)

    def test_logger(self):
        fake_script(typing.cast(unittest.TestCase, self), 'action-get', "echo '{}'")

        test_cases = [(
            EventSpec(ops.ActionEvent, 'log_critical_action', env_var='JUJU_ACTION_NAME'),
            ['juju-log', '--log-level', 'CRITICAL', '--', 'super critical'],
        ), (
            EventSpec(ops.ActionEvent, 'log_error_action',
                      env_var='JUJU_ACTION_NAME'),
            ['juju-log', '--log-level', 'ERROR', '--', 'grave error'],
        ), (
            EventSpec(ops.ActionEvent, 'log_warning_action',
                      env_var='JUJU_ACTION_NAME'),
            ['juju-log', '--log-level', 'WARNING', '--', 'wise warning'],
        ), (
            EventSpec(ops.ActionEvent, 'log_info_action',
                      env_var='JUJU_ACTION_NAME'),
            ['juju-log', '--log-level', 'INFO', '--', 'useful info'],
        )]

        # Set up action symlinks.
        self._simulate_event(EventSpec(ops.InstallEvent, 'install'))

        for event_spec, calls in test_cases:
            self._simulate_event(event_spec)
            self.assertIn(calls,
                          fake_script_calls(typing.cast(unittest.TestCase, self), clear=True))

    def test_excepthook(self):
        with self.assertRaises(subprocess.CalledProcessError):
            self._simulate_event(EventSpec(ops.InstallEvent, 'install',
                                           set_in_env={'TRY_EXCEPTHOOK': '1'}))

        calls = [' '.join(i) for i in fake_script_calls(typing.cast(unittest.TestCase, self))]

        self.assertEqual(calls.pop(0), ' '.join(VERSION_LOGLINE))
        self.assertRegex(calls.pop(0), 'Using local storage: not a Kubernetes podspec charm')
        self.assertRegex(calls.pop(0), 'Initializing SQLite local storage: ')

        self.maxDiff = None
        self.assertRegex(
            calls[0],
            '(?ms)juju-log --log-level ERROR -- Uncaught exception while in charm code:\n'
            'Traceback .most recent call last.:\n'
            '  .*'
            '    raise RuntimeError."failing as requested".\n'
            'RuntimeError: failing as requested'
        )
        self.assertEqual(len(calls), 1, f"expected 1 call, but got extra: {calls[1:]}")

    def test_sets_model_name(self):
        self._prepare_actions()

        fake_script(typing.cast(unittest.TestCase, self), 'action-get', "echo '{}'")
        state = self._simulate_event(EventSpec(
            ops.ActionEvent, 'get_model_name_action',
            env_var='JUJU_ACTION_NAME',
            model_name='test-model-name'))
        assert isinstance(state, ops.BoundStoredState)
        self.assertEqual(state._on_get_model_name_action, ['test-model-name'])

    def test_has_valid_status(self):
        self._prepare_actions()

        fake_script(typing.cast(unittest.TestCase, self), 'action-get', "echo '{}'")
        fake_script(typing.cast(unittest.TestCase, self), 'status-get',
                    """echo '{"status": "unknown", "message": ""}'""")
        state = self._simulate_event(EventSpec(
            ops.ActionEvent, 'get_status_action',
            env_var='JUJU_ACTION_NAME'))
        assert isinstance(state, ops.BoundStoredState)
        self.assertEqual(state.status_name, 'unknown')
        self.assertEqual(state.status_message, '')
        fake_script(
            typing.cast(unittest.TestCase, self),
            'status-get',
            """echo '{"status": "blocked", "message": "help meeee"}'""")
        state = self._simulate_event(EventSpec(
            ops.ActionEvent, 'get_status_action',
            env_var='JUJU_ACTION_NAME'))
        assert isinstance(state, ops.BoundStoredState)
        self.assertEqual(state.status_name, 'blocked')
        self.assertEqual(state.status_message, 'help meeee')


class TestMainWithNoDispatch(_TestMain, unittest.TestCase):
    has_dispatch = False
    hooks_are_symlinks = True

    def _setup_entry_point(self, directory: Path, entry_point: str):
        path = directory / entry_point
        path.symlink_to(self.charm_exec_path)

    def _call_event(self, rel_path: Path, env: typing.Dict[str, str]):
        env['JUJU_VERSION'] = '2.7.0'
        event_file = self.JUJU_CHARM_DIR / rel_path
        # Note that sys.executable is used to make sure we are using the same
        # interpreter for the child process to support virtual environments.
        fake_script(
            self,
            "storage-get",
            """
            if [ "$1" = "-s" ]; then
                id=${2#*/}
                key=${2%/*}
                echo "\\"/var/srv/${key}/${id}\\"" # NOQA: test_quote_backslashes
            elif [ "$1" = '--help' ]; then
                printf '%s\\n' \\
                'Usage: storage-get [options] [<key>]' \\
                '   ' \\
                'Summary:' \\
                'print information for storage instance with specified id' \\
                '   ' \\
                'Options:' \\
                '--format  (= smart)' \\
                '    Specify output format (json|smart|yaml)' \\
                '-o, --output (= "")' \\
                '    Specify an output file' \\
                '-s  (= test-stor/0)' \\
                '    specify a storage instance by id' \\
                '   ' \\
                'Details:' \\
                'When no <key> is supplied, all keys values are printed.'
            else
                # Return the same path for all disks since `storage-get`
                # on attach and detach takes no parameters and is not
                # deterministically faked with fake_script
                exit 1
            fi
            """,
        )
        fake_script(
            self,
            "storage-list",
            """
            echo '["disks/0"]'
            """,
        )
        subprocess.run(
            [sys.executable, str(event_file)],
            check=True, env=env, cwd=str(self.JUJU_CHARM_DIR))

    def test_setup_event_links(self):
        """Test auto-creation of symlinks caused by initial events."""
        all_event_hooks = [f"hooks/{name.replace('_', '-')}"
                           for name, event_source in self.charm_module.Charm.on.events().items()
                           if issubclass(event_source.event_type, ops.LifecycleEvent)]

        initial_events = {
            EventSpec(ops.InstallEvent, 'install'),
            EventSpec(ops.StorageAttachedEvent, 'disks-storage-attached'),
            EventSpec(ops.StartEvent, 'start'),
            EventSpec(ops.UpgradeCharmEvent, 'upgrade-charm'),
        }
        initial_hooks = {f"hooks/{ev.event_name}" for ev in initial_events}

        def _assess_event_links(event_spec: EventSpec):
            self.assertTrue(self.hooks_dir / event_spec.event_name in self.hooks_dir.iterdir())
            for event_hook in all_event_hooks:
                hook_path = self.JUJU_CHARM_DIR / event_hook
                self.assertTrue(hook_path.exists(), f"Missing hook: {event_hook}")
                if self.hooks_are_symlinks:
                    self.assertTrue(hook_path.is_symlink())
                    self.assertEqual(os.readlink(str(hook_path)), self.charm_exec_path)
                elif event_hook in initial_hooks:
                    self.assertFalse(hook_path.is_symlink())
                else:
                    # hooks are not symlinks, and this hook is not one of the initial ones
                    # check that it's a symlink to the initial ones
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
        self._simulate_event(EventSpec(ops.InstallEvent, 'install'))
        # foo-bar is one of the actions defined in actions.yaml
        action_hook = self.JUJU_CHARM_DIR / 'actions' / 'foo-bar'
        self.assertTrue(action_hook.exists())


class TestMainWithNoDispatchButJujuIsDispatchAware(TestMainWithNoDispatch):
    def _call_event(self, rel_path: Path, env: typing.Dict[str, str]):
        env['JUJU_DISPATCH_PATH'] = str(rel_path)
        env['JUJU_VERSION'] = '2.8.0'
        super()._call_event(rel_path, env)


class TestMainWithNoDispatchButDispatchPathIsSet(TestMainWithNoDispatch):
    def _call_event(self, rel_path: Path, env: typing.Dict[str, str]):
        env['JUJU_DISPATCH_PATH'] = str(rel_path)
        super()._call_event(rel_path, env)


class TestMainWithNoDispatchButScriptsAreCopies(TestMainWithNoDispatch):
    hooks_are_symlinks = False

    def _setup_entry_point(self, directory: Path, entry_point: str):
        charm_path = str(self.JUJU_CHARM_DIR / 'src/charm.py')
        path = directory / entry_point
        shutil.copy(charm_path, str(path))


class _TestMainWithDispatch(_TestMain):
    has_dispatch = True

    def test_setup_event_links(self):
        """Test auto-creation of symlinks.

        Symlink creation caused by initial events should _not_ happen when using dispatch.
        """
        all_event_hooks = [f"hooks/{e.replace('_', '-')}"
                           for e in self.charm_module.Charm.on.events().keys()]
        initial_events = {
            EventSpec(ops.InstallEvent, 'install'),
            EventSpec(ops.StorageAttachedEvent, 'disks-storage-attached'),
            EventSpec(ops.StartEvent, 'start'),
            EventSpec(ops.UpgradeCharmEvent, 'upgrade-charm'),
        }

        def _assess_event_links(event_spec: EventSpec):
            self.assertNotIn(self.hooks_dir / event_spec.event_name, self.hooks_dir.iterdir())
            for event_hook in all_event_hooks:
                self.assertFalse((self.JUJU_CHARM_DIR / event_hook).exists(),
                                 f"Spurious hook: {event_hook}")

        for initial_event in initial_events:
            self._setup_charm_dir()

            self._simulate_event(initial_event)
            _assess_event_links(initial_event)

    def test_hook_and_dispatch(self):
        old_path = self.fake_script_path
        self.fake_script_path = self.hooks_dir
        fake_script(typing.cast(unittest.TestCase, self), 'install', 'exit 0')
        state = self._simulate_event(EventSpec(ops.InstallEvent, 'install'))
        assert isinstance(state, ops.BoundStoredState)

        # the script was called, *and*, the .on. was called
        self.assertEqual(fake_script_calls(typing.cast(
            unittest.TestCase, self)), [['install', '']])
        self.assertEqual(list(state.observed_event_types), ['InstallEvent'])

        self.fake_script_path = old_path
        hook = Path('hooks/install')
        expected = [
            VERSION_LOGLINE,
            ['juju-log', '--log-level', 'INFO', '--',
             f'Running legacy {hook}.'],
            ['juju-log', '--log-level', 'DEBUG', '--',
             f'Legacy {hook} exited with status 0.'],
            ['juju-log', '--log-level', 'DEBUG', '--',
             'Using local storage: not a Kubernetes podspec charm'],
            ['juju-log', '--log-level', 'DEBUG', '--',
             'Emitting Juju event install.'],
            ['is-leader', '--format=json'],
        ]
        calls = fake_script_calls(typing.cast(unittest.TestCase, self))
        self.assertRegex(' '.join(calls.pop(-3)),
                         'Initializing SQLite local storage: ')
        self.assertEqual(calls, expected)

    def test_non_executable_hook_and_dispatch(self):
        (self.hooks_dir / "install").write_text("")
        state = self._simulate_event(EventSpec(ops.InstallEvent, 'install'))
        assert isinstance(state, ops.BoundStoredState)

        self.assertEqual(list(state.observed_event_types), ['InstallEvent'])

        expected = [
            VERSION_LOGLINE,
            ['juju-log', '--log-level', 'WARNING', '--',
             'Legacy hooks/install exists but is not executable.'],
            ['juju-log', '--log-level', 'DEBUG', '--',
             'Using local storage: not a Kubernetes podspec charm'],
            ['juju-log', '--log-level', 'DEBUG', '--',
             'Emitting Juju event install.'],
            ['is-leader', '--format=json'],
        ]
        calls = fake_script_calls(typing.cast(unittest.TestCase, self))
        self.assertRegex(' '.join(calls.pop(-3)),
                         'Initializing SQLite local storage: ')
        self.assertEqual(calls, expected)

    def test_hook_and_dispatch_with_failing_hook(self):
        self.stdout = self.stderr = tempfile.TemporaryFile()
        self.addCleanup(self.stdout.close)

        old_path = self.fake_script_path
        self.fake_script_path = self.hooks_dir
        fake_script(typing.cast(unittest.TestCase, self), 'install', 'exit 42')
        event = EventSpec(ops.InstallEvent, 'install')
        with self.assertRaises(subprocess.CalledProcessError):
            self._simulate_event(event)
        self.fake_script_path = old_path

        self.stdout.seek(0)
        self.assertEqual(self.stdout.read(), b'')
        calls = fake_script_calls(typing.cast(unittest.TestCase, self))
        hook = Path('hooks/install')
        expected = [
            VERSION_LOGLINE,
            ['juju-log', '--log-level', 'INFO', '--', f'Running legacy {hook}.'],
            ['juju-log', '--log-level', 'WARNING', '--',
             f'Legacy {hook} exited with status 42.'],
        ]
        self.assertEqual(calls, expected)

    def test_hook_and_dispatch_but_hook_is_dispatch(self):
        event = EventSpec(ops.InstallEvent, 'install')
        hook_path = self.hooks_dir / 'install'
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
                # sanity check
                self.assertEqual(path.is_absolute(), not rel)
                self.assertEqual(path.with_suffix('').name == 'dispatch', ind)
                try:
                    hook_path.symlink_to(path)

                    state = self._simulate_event(event)
                    assert isinstance(state, ops.BoundStoredState)

                    # the .on. was only called once
                    self.assertEqual(list(state.observed_event_types), ['InstallEvent'])
                    self.assertEqual(list(state.on_install), ['InstallEvent'])
                finally:
                    hook_path.unlink()

    def test_hook_and_dispatch_but_hook_is_dispatch_copy(self):
        hook_path = self.hooks_dir / 'install'
        path = (self.hooks_dir / self.charm_exec_path).resolve()
        shutil.copy(str(path), str(hook_path))

        event = EventSpec(ops.InstallEvent, 'install')
        state = self._simulate_event(event)
        assert isinstance(state, ops.BoundStoredState)

        # the .on. was only called once
        self.assertEqual(list(state.observed_event_types), ['InstallEvent'])
        self.assertEqual(list(state.on_install), ['InstallEvent'])
        hook = Path('hooks/install')
        expected = [
            VERSION_LOGLINE,
            ['juju-log', '--log-level', 'INFO', '--',
             f'Running legacy {hook}.'],
            VERSION_LOGLINE,    # because it called itself
            ['juju-log', '--log-level', 'DEBUG', '--',
             f'Charm called itself via {hook}.'],
            ['juju-log', '--log-level', 'DEBUG', '--',
             f'Legacy {hook} exited with status 0.'],
            ['juju-log', '--log-level', 'DEBUG', '--',
             'Using local storage: not a Kubernetes podspec charm'],
            ['juju-log', '--log-level', 'DEBUG', '--',
             'Emitting Juju event install.'],
            ['is-leader', '--format=json'],
        ]
        calls = fake_script_calls(typing.cast(unittest.TestCase, self))
        self.assertRegex(' '.join(calls.pop(-3)), 'Initializing SQLite local storage: ')

        self.assertEqual(calls, expected)


class TestMainWithDispatch(_TestMainWithDispatch, unittest.TestCase):
    def _setup_entry_point(self, directory: Path, entry_point: str):
        path = self.JUJU_CHARM_DIR / 'dispatch'
        if not path.exists():
            path.symlink_to(os.path.join('src', 'charm.py'))

    def _call_event(self, rel_path: Path, env: typing.Dict[str, str]):
        env['JUJU_DISPATCH_PATH'] = str(rel_path)
        env['JUJU_VERSION'] = '2.8.0'
        dispatch = self.JUJU_CHARM_DIR / 'dispatch'
        fake_script(
            self,
            "storage-get",
            """
            if [ "$1" = "-s" ]; then
                id=${2#*/}
                key=${2%/*}
                echo "\\"/var/srv/${key}/${id}\\"" # NOQA: test_quote_backslashes
            elif [ "$1" = '--help' ]; then
                printf '%s\\n' \\
                'Usage: storage-get [options] [<key>]' \\
                '   ' \\
                'Summary:' \\
                'print information for storage instance with specified id' \\
                '   ' \\
                'Options:' \\
                '--format  (= smart)' \\
                '    Specify output format (json|smart|yaml)' \\
                '-o, --output (= "")' \\
                '    Specify an output file' \\
                '-s  (= test-stor/0)' \\
                '    specify a storage instance by id' \\
                '   ' \\
                'Details:' \\
                'When no <key> is supplied, all keys values are printed.'
            else
                # Return the same path for all disks since `storage-get`
                # on attach and detach takes no parameters and is not
                # deterministically faked with fake_script
                exit 1
            fi
            """,
        )
        fake_script(
            self,
            "storage-list",
            """
            echo '["disks/0"]'
            """,
        )
        subprocess.run(
            [sys.executable, str(dispatch)],
            # stdout=self.stdout,
            # stderr=self.stderr,
            check=True, env=env, cwd=str(self.JUJU_CHARM_DIR))


class TestMainWithDispatchAsScript(_TestMainWithDispatch, unittest.TestCase):
    """Here dispatch is a script that execs the charm.py instead of a symlink."""

    has_dispatch = True

    def _setup_entry_point(self, directory: Path, entry_point: str):
        path = (self.JUJU_CHARM_DIR / 'dispatch')
        if not path.exists():
            path.write_text('#!/bin/sh\nexec "{}" "{}"\n'.format(
                sys.executable,
                self.JUJU_CHARM_DIR / 'src/charm.py'))
            path.chmod(0o755)

    def _call_event(self, rel_path: Path, env: typing.Dict[str, str]):
        env['JUJU_DISPATCH_PATH'] = str(rel_path)
        env['JUJU_VERSION'] = '2.8.0'
        fake_script(
            self,
            "storage-get",
            """
            if [ "$1" = "-s" ]; then
                id=${2#*/}
                key=${2%/*}
                echo "\\"/var/srv/${key}/${id}\\"" # NOQA: test_quote_backslashes
            elif [ "$1" = '--help' ]; then
                printf '%s\\n' \\
                'Usage: storage-get [options] [<key>]' \\
                '   ' \\
                'Summary:' \\
                'print information for storage instance with specified id' \\
                '   ' \\
                'Options:' \\
                '--format  (= smart)' \\
                '    Specify output format (json|smart|yaml)' \\
                '-o, --output (= "")' \\
                '    Specify an output file' \\
                '-s  (= test-stor/0)' \\
                '    specify a storage instance by id' \\
                '   ' \\
                'Details:' \\
                'When no <key> is supplied, all keys values are printed.'
            else
                # Return the same path for all disks since `storage-get`
                # on attach and detach takes no parameters and is not
                # deterministically faked with fake_script
                exit 1
            fi
            """,
        )
        fake_script(
            self,
            "storage-list",
            """
            echo '["disks/0"]'
            """,
        )
        dispatch = (self.JUJU_CHARM_DIR / 'dispatch')
        subprocess.check_call([str(dispatch)], env=env, cwd=str(self.JUJU_CHARM_DIR))


class TestStorageHeuristics(unittest.TestCase):
    def test_fallback_to_current_juju_version__too_old(self):
        meta = ops.CharmMeta.from_yaml("series: [kubernetes]")
        with patch.dict(os.environ, {"JUJU_VERSION": "1.0"}):
            self.assertFalse(_should_use_controller_storage(Path("/xyzzy"), meta))

    def test_fallback_to_current_juju_version__new_enough(self):
        meta = ops.CharmMeta.from_yaml("series: [kubernetes]")
        with patch.dict(os.environ, {"JUJU_VERSION": "2.8"}):
            self.assertTrue(_should_use_controller_storage(Path("/xyzzy"), meta))

    def test_not_if_not_in_k8s(self):
        meta = ops.CharmMeta.from_yaml("series: [ecs]")
        with patch.dict(os.environ, {"JUJU_VERSION": "2.8"}):
            self.assertFalse(_should_use_controller_storage(Path("/xyzzy"), meta))

    def test_not_if_already_local(self):
        meta = ops.CharmMeta.from_yaml("series: [kubernetes]")
        with patch.dict(os.environ, {"JUJU_VERSION": "2.8"}), tempfile.NamedTemporaryFile() as fd:
            self.assertFalse(_should_use_controller_storage(Path(fd.name), meta))
