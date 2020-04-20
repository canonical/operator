#!/usr/bin/env python3
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

import base64
import logging
import os
import pickle
import shutil
import subprocess
import sys
import tempfile
import unittest

import importlib.util

from pathlib import Path

from ops.charm import (
    CharmBase,
    CharmEvents,
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

from .test_helpers import fake_script, fake_script_calls

# This relies on the expected repository structure to find a path to
# source of the charm under test.
TEST_CHARM_DIR = Path(__file__ + '/../charms/test_main').resolve()

logger = logging.getLogger(__name__)


class SymlinkTargetError(Exception):
    pass


class EventSpec:
    def __init__(self, event_type, event_name, env_var=None,
                 relation_id=None, remote_app=None, remote_unit=None,
                 charm_config=None):
        self.event_type = event_type
        self.event_name = event_name
        self.env_var = env_var
        self.relation_id = relation_id
        self.remote_app = remote_app
        self.remote_unit = remote_unit
        self.charm_config = charm_config


class TestMain(unittest.TestCase):

    def setUp(self):
        self._setup_charm_dir()

        _, tmp_file = tempfile.mkstemp()
        self._state_file = Path(tmp_file)
        self.addCleanup(self._state_file.unlink)

        # Relations events are defined dynamically and modify the class attributes.
        # We use a subclass temporarily to prevent these side effects from leaking.
        class TestCharmEvents(CharmEvents):
            pass
        CharmBase.on = TestCharmEvents()

        def cleanup():
            shutil.rmtree(str(self.JUJU_CHARM_DIR))
            CharmBase.on = CharmEvents()
        self.addCleanup(cleanup)

        fake_script(self, 'juju-log', "exit 0")

    def _setup_charm_dir(self):
        self.JUJU_CHARM_DIR = Path(tempfile.mkdtemp()) / 'test_main'
        self.hooks_dir = self.JUJU_CHARM_DIR / 'hooks'
        charm_path = str(self.JUJU_CHARM_DIR / 'src/charm.py')
        self.charm_exec_path = os.path.relpath(charm_path,
                                               str(self.hooks_dir))
        shutil.copytree(str(TEST_CHARM_DIR), str(self.JUJU_CHARM_DIR))

        charm_spec = importlib.util.spec_from_file_location("charm", charm_path)
        self.charm_module = importlib.util.module_from_spec(charm_spec)
        charm_spec.loader.exec_module(self.charm_module)

        self._prepare_initial_hooks()

    def _prepare_initial_hooks(self):
        initial_hooks = ('install', 'start', 'upgrade-charm', 'disks-storage-attached')
        self.hooks_dir.mkdir()
        for hook in initial_hooks:
            hook_path = self.hooks_dir / hook
            hook_path.symlink_to(self.charm_exec_path)

    def _prepare_actions(self):
        actions_meta = '''
foo-bar:
  description: Foos the bar.
  title: foo-bar
  params:
    foo-name:
      type: string
      description: A foo name to bar.
    silent:
      type: boolean
      description:
      default: false
  required:
    - foo-name
start:
    description: Start the unit.'''
        actions_dir_name = 'actions'
        actions_meta_file = 'actions.yaml'

        with open(str(self.JUJU_CHARM_DIR / actions_meta_file), 'w+') as f:
            f.write(actions_meta)
        actions_dir = self.JUJU_CHARM_DIR / actions_dir_name
        actions_dir.mkdir()
        for action_name in ('start', 'foo-bar'):
            action_path = actions_dir / action_name
            action_path.symlink_to(self.charm_exec_path)

    def _read_and_clear_state(self):
        state = None
        if self._state_file.stat().st_size:
            with open(str(self._state_file), 'r+b') as state_file:
                state = pickle.load(state_file)
                state_file.truncate()
        return state

    def _simulate_event(self, event_spec):
        env = {
            'PATH': "{}:{}".format(Path(__file__).parent / 'bin', os.environ['PATH']),
            'JUJU_CHARM_DIR': str(self.JUJU_CHARM_DIR),
            'JUJU_UNIT_NAME': 'test_main/0',
            'CHARM_CONFIG': event_spec.charm_config,
        }
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
        event_file = self.JUJU_CHARM_DIR / event_dir / event_filename
        # Note that sys.executable is used to make sure we are using the same
        # interpreter for the child process to support virtual environments.
        cmd = [sys.executable, str(event_file)]
        subprocess.run(
            cmd, check=True, env=env, cwd=str(self.JUJU_CHARM_DIR),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return self._read_and_clear_state()

    def test_event_reemitted(self):
        # base64 encoding is used to avoid null bytes.
        charm_config = base64.b64encode(pickle.dumps({
            'STATE_FILE': self._state_file,
        }))

        # First run "install" to make sure all hooks are set up.
        state = self._simulate_event(EventSpec(InstallEvent, 'install', charm_config=charm_config))
        self.assertEqual(state['observed_event_types'], [InstallEvent])

        state = self._simulate_event(EventSpec(ConfigChangedEvent, 'config-changed',
                                               charm_config=charm_config))
        self.assertEqual(state['observed_event_types'], [ConfigChangedEvent])

        # Re-emit should pick the deferred config-changed.
        state = self._simulate_event(EventSpec(UpdateStatusEvent, 'update-status',
                                               charm_config=charm_config))
        self.assertEqual(state['observed_event_types'], [ConfigChangedEvent, UpdateStatusEvent])

    def test_no_reemission_on_collect_metrics(self):
        # base64 encoding is used to avoid null bytes.
        charm_config = base64.b64encode(pickle.dumps({
            'STATE_FILE': self._state_file,
        }))
        fake_script(self, 'add-metric', 'exit 0')

        # First run "install" to make sure all hooks are set up.
        state = self._simulate_event(EventSpec(InstallEvent, 'install', charm_config=charm_config))
        self.assertEqual(state['observed_event_types'], [InstallEvent])

        state = self._simulate_event(EventSpec(ConfigChangedEvent, 'config-changed',
                                               charm_config=charm_config))
        self.assertEqual(state['observed_event_types'], [ConfigChangedEvent])

        # Re-emit should not pick the deferred config-changed because
        # collect-metrics runs in a restricted context.
        state = self._simulate_event(EventSpec(CollectMetricsEvent, 'collect-metrics',
                                               charm_config=charm_config))
        self.assertEqual(state['observed_event_types'], [CollectMetricsEvent])

    def test_multiple_events_handled(self):
        self._prepare_actions()

        charm_config = base64.b64encode(pickle.dumps({
            'STATE_FILE': self._state_file,
        }))
        actions_charm_config = base64.b64encode(pickle.dumps({
            'STATE_FILE': self._state_file,
            'USE_ACTIONS': True,
        }))

        fake_script(self, 'action-get', "echo '{}'")

        # Sample events with a different amount of dashes used
        # and with endpoints from different sections of metadata.yaml
        events_under_test = [(
            EventSpec(InstallEvent, 'install',
                      charm_config=charm_config),
            {},
        ), (
            EventSpec(StartEvent, 'start',
                      charm_config=charm_config),
            {},
        ), (
            EventSpec(UpdateStatusEvent, 'update_status',
                      charm_config=charm_config),
            {},
        ), (
            EventSpec(LeaderSettingsChangedEvent, 'leader_settings_changed',
                      charm_config=charm_config),
            {},
        ), (
            EventSpec(RelationJoinedEvent, 'db_relation_joined',
                      relation_id=1,
                      remote_app='remote', remote_unit='remote/0',
                      charm_config=charm_config),
            {'relation_name': 'db',
             'relation_id': 1,
             'app_name': 'remote',
             'unit_name': 'remote/0'},
        ), (
            EventSpec(RelationChangedEvent, 'mon_relation_changed',
                      relation_id=2,
                      remote_app='remote', remote_unit='remote/0',
                      charm_config=charm_config),
            {'relation_name': 'mon',
             'relation_id': 2,
             'app_name': 'remote',
             'unit_name': 'remote/0'},
        ), (
            EventSpec(RelationChangedEvent, 'mon_relation_changed',
                      relation_id=2,
                      remote_app='remote', remote_unit=None,
                      charm_config=charm_config),
            {'relation_name': 'mon',
             'relation_id': 2,
             'app_name': 'remote',
             'unit_name': None},
        ), (
            EventSpec(RelationDepartedEvent, 'mon_relation_departed',
                      relation_id=2,
                      remote_app='remote', remote_unit='remote/0',
                      charm_config=charm_config),
            {'relation_name': 'mon',
             'relation_id': 2,
             'app_name': 'remote',
             'unit_name': 'remote/0'},
        ), (
            EventSpec(RelationBrokenEvent, 'ha_relation_broken',
                      relation_id=3,
                      charm_config=charm_config),
            {'relation_name': 'ha',
             'relation_id': 3},
        ), (
            # Events without a remote app specified (for Juju < 2.7).
            EventSpec(RelationJoinedEvent, 'db_relation_joined',
                      relation_id=1,
                      remote_unit='remote/0',
                      charm_config=charm_config),
            {'relation_name': 'db',
             'relation_id': 1,
             'app_name': 'remote',
             'unit_name': 'remote/0'},
        ), (
            EventSpec(RelationChangedEvent, 'mon_relation_changed',
                      relation_id=2,
                      remote_unit='remote/0',
                      charm_config=charm_config),
            {'relation_name': 'mon',
             'relation_id': 2,
             'app_name': 'remote',
             'unit_name': 'remote/0'},
        ), (
            EventSpec(RelationDepartedEvent, 'mon_relation_departed',
                      relation_id=2,
                      remote_unit='remote/0',
                      charm_config=charm_config),
            {'relation_name': 'mon',
             'relation_id': 2,
             'app_name': 'remote',
             'unit_name': 'remote/0'},
        ), (
            EventSpec(ActionEvent, 'start_action',
                      env_var='JUJU_ACTION_NAME',
                      charm_config=actions_charm_config),
            {},
        ), (
            EventSpec(ActionEvent, 'foo_bar_action',
                      env_var='JUJU_ACTION_NAME',
                      charm_config=actions_charm_config),
            {},
        )]

        logger.debug('Expected events %s', events_under_test)

        # First run "install" to make sure all hooks are set up.
        self._simulate_event(EventSpec(InstallEvent, 'install', charm_config=charm_config))

        # Simulate hook executions for every event.
        for event_spec, expected_event_data in events_under_test:
            state = self._simulate_event(event_spec)

            state_key = 'on_' + event_spec.event_name
            handled_events = state.get(state_key, [])

            # Make sure that a handler for that event was called once.
            self.assertEqual(len(handled_events), 1)
            # Make sure the event handled by the Charm has the right type.
            handled_event_type = handled_events[0]
            self.assertEqual(handled_event_type, event_spec.event_type)

            self.assertEqual(state['observed_event_types'], [event_spec.event_type])

            if event_spec.event_name in expected_event_data:
                self.assertEqual(state[event_spec.event_name + '_data'],
                                 expected_event_data[event_spec.event_name])

    def test_event_not_implemented(self):
        """Make sure events without implementation do not cause non-zero exit.
        """
        charm_config = base64.b64encode(pickle.dumps({
            'STATE_FILE': self._state_file,
        }))

        # Simulate a scenario where there is a symlink for an event that
        # a charm does not know how to handle.
        hook_path = self.JUJU_CHARM_DIR / 'hooks/not-implemented-event'
        # This will be cleared up in tearDown.
        hook_path.symlink_to('install')

        try:
            self._simulate_event(EventSpec(HookEvent, 'not-implemented-event',
                                           charm_config=charm_config))
        except subprocess.CalledProcessError:
            self.fail('Event simulation for an unsupported event'
                      ' results in a non-zero exit code returned')

    def test_setup_event_links(self):
        """Test auto-creation of symlinks caused by initial events.
        """
        all_event_hooks = ['hooks/' + e.replace("_", "-")
                           for e in self.charm_module.Charm.on.events().keys()]
        charm_config = base64.b64encode(pickle.dumps({
            'STATE_FILE': self._state_file,
        }))
        initial_events = {
            EventSpec(InstallEvent, 'install', charm_config=charm_config),
            EventSpec(StorageAttachedEvent, 'disks-storage-attached', charm_config=charm_config),
            EventSpec(StartEvent, 'start', charm_config=charm_config),
            EventSpec(UpgradeCharmEvent, 'upgrade-charm', charm_config=charm_config),
        }

        def _assess_event_links(event_spec):
            self.assertTrue(self.hooks_dir / event_spec.event_name in self.hooks_dir.iterdir())
            for event_hook in all_event_hooks:
                self.assertTrue((self.JUJU_CHARM_DIR / event_hook).exists(),
                                'Missing hook: ' + event_hook)
                self.assertEqual(os.readlink(str(self.JUJU_CHARM_DIR / event_hook)),
                                 self.charm_exec_path)

        for initial_event in initial_events:
            self._setup_charm_dir()

            self._simulate_event(initial_event)
            _assess_event_links(initial_event)
            # Make sure it is idempotent.
            self._simulate_event(initial_event)
            _assess_event_links(initial_event)

    def test_setup_action_links(self):
        charm_config = base64.b64encode(pickle.dumps({
            'STATE_FILE': self._state_file,
        }))
        actions_yaml = self.JUJU_CHARM_DIR / 'actions.yaml'
        actions_yaml.write_text('test: {}')
        self._simulate_event(EventSpec(InstallEvent, 'install', charm_config=charm_config))
        action_hook = self.JUJU_CHARM_DIR / 'actions' / 'test'
        self.assertTrue(action_hook.exists())

    def test_collect_metrics(self):
        indicator_file = self.JUJU_CHARM_DIR / 'indicator'
        charm_config = base64.b64encode(pickle.dumps({
            'STATE_FILE': self._state_file,
            'INDICATOR_FILE': indicator_file
        }))
        fake_script(self, 'add-metric', 'exit 0')
        self._simulate_event(EventSpec(InstallEvent, 'install', charm_config=charm_config))
        self._simulate_event(EventSpec(CollectMetricsEvent, 'collect_metrics',
                                       charm_config=charm_config))
        self.assertEqual(fake_script_calls(self),
                         [['add-metric', '--labels', 'bar=4.2', 'foo=42']])

    def test_logger(self):
        charm_config = base64.b64encode(pickle.dumps({
            'STATE_FILE': self._state_file,
            'USE_LOG_ACTIONS': True,
        }))
        fake_script(self, 'action-get', "echo '{}'")
        actions_yaml = self.JUJU_CHARM_DIR / 'actions.yaml'
        actions_yaml.write_text(
            '''
log_critical: {}
log_error: {}
log_warning: {}
log_info: {}
log_debug: {}
            ''')

        test_cases = [(
            EventSpec(ActionEvent, 'log_critical_action', env_var='JUJU_ACTION_NAME',
                      charm_config=charm_config),
            ['juju-log', '--log-level', 'CRITICAL', 'super critical'],
        ), (
            EventSpec(ActionEvent, 'log_error_action',
                      env_var='JUJU_ACTION_NAME',
                      charm_config=charm_config),
            ['juju-log', '--log-level', 'ERROR', 'grave error'],
        ), (
            EventSpec(ActionEvent, 'log_warning_action',
                      env_var='JUJU_ACTION_NAME',
                      charm_config=charm_config),
            ['juju-log', '--log-level', 'WARNING', 'wise warning'],
        ), (
            EventSpec(ActionEvent, 'log_info_action',
                      env_var='JUJU_ACTION_NAME',
                      charm_config=charm_config),
            ['juju-log', '--log-level', 'INFO', 'useful info'],
        )]

        # Set up action symlinks.
        self._simulate_event(EventSpec(InstallEvent, 'install',
                                       charm_config=charm_config))

        for event_spec, calls in test_cases:
            self._simulate_event(event_spec)
            self.assertIn(calls, fake_script_calls(self, clear=True))


if __name__ == "__main__":
    unittest.main()
