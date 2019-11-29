#!/usr/bin/env python3

import unittest
import logging
import os
import sys
import subprocess
import pickle
import base64
import tempfile

import importlib.util

import op.main

from pathlib import Path

from op.charm import (
    CharmBase,
    CharmEvents,
    HookEvent,
    InstallEvent,
    StartEvent,
    LeaderElectedEvent,
    UpgradeCharmEvent,
    ConfigChangedEvent,
    UpdateStatusEvent,
    LeaderSettingsChangedEvent,
    RelationJoinedEvent,
    RelationChangedEvent,
    RelationDepartedEvent,
    RelationBrokenEvent,
    RelationEvent,
    StorageAttachedEvent,
)

# This relies on the expected repository structure to find
# a path to the charm under test.
JUJU_CHARM_DIR = Path(f'{__file__}/../charms/test_main').resolve()

charm_spec = importlib.util.spec_from_file_location("charm", str(JUJU_CHARM_DIR / 'lib/charm.py'))
charm = importlib.util.module_from_spec(charm_spec)
charm_spec.loader.exec_module(charm)


logger = logging.getLogger(__name__)


class SymlinkTargetError(Exception):
    pass


class EventSpec:
    def __init__(self, event_type, event_name, relation_id=None, remote_app=None, remote_unit=None,
                 charm_config=None):
        self.event_type = event_type
        self.event_name = event_name
        self.relation_id = relation_id
        self.remote_app = remote_app
        self.remote_unit = remote_unit
        self.charm_config = charm_config


class TestMain(unittest.TestCase):

    CHARM_PY_RELPATH = '../lib/charm.py'

    @classmethod
    def _clear_unit_db(cls):
        charm_state_file = JUJU_CHARM_DIR / op.main.CHARM_STATE_FILE
        if charm_state_file.exists():
            charm_state_file.unlink()

    def setUp(self):
        self._clear_unit_db()
        self._clear_symlinks()

        # Change cwd for the current process to the test charm directory
        # as it is preserved across fork + exec.
        self.addCleanup(os.chdir, os.curdir)
        os.chdir(JUJU_CHARM_DIR)
        _, tmp_file = tempfile.mkstemp()
        self._state_file = Path(tmp_file)
        self.addCleanup(self._state_file.unlink)

        # Relations events are defined dynamically and modify the class attributes.
        # We use a subclass temporarily to prevent these side effects from leaking.
        class TestCharmEvents(CharmEvents):
            pass
        CharmBase.on = TestCharmEvents()

        def cleanup():
            self._clear_unit_db()
            self._clear_symlinks()
            CharmBase.on = CharmEvents()
        self.addCleanup(cleanup)

    @classmethod
    def _clear_symlinks(cls):
        r, _, files = next(os.walk(JUJU_CHARM_DIR / 'hooks'))
        for f in files:
            absolute_path = Path(r) / f
            if absolute_path.name == 'install' and absolute_path.is_symlink():
                if os.readlink(absolute_path) != cls.CHARM_PY_RELPATH:
                    raise SymlinkTargetError(f'"{absolute_path.name}" link does not point to {cls.CHARM_PY_RELPATH}')
            elif absolute_path.name.endswith('-storage-attached') and absolute_path.is_symlink():
                if os.readlink(absolute_path) != 'install':
                    raise SymlinkTargetError(f'"{absolute_path.name}" link does not point to "install"')
            else:
                absolute_path.unlink()

    def _read_and_clear_state(self):
        state = None
        if self._state_file.stat().st_size:
            with open(self._state_file, 'r+b') as state_file:
                state = pickle.load(state_file)
                state_file.truncate()
        return state

    def _simulate_event(self, event_spec):
        event_hook = JUJU_CHARM_DIR / f"hooks/{event_spec.event_name.replace('_', '-')}"
        env = {
            'PATH': str(Path(__file__).parent / 'bin'),
            'JUJU_CHARM_DIR': JUJU_CHARM_DIR,
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
        # Note that sys.executable is used to make sure we are using the same
        # interpreter for the child process to support virtual environments.
        subprocess.check_call([sys.executable, event_hook], env=env)
        return self._read_and_clear_state()

    def test_event_reemitted(self):
        # base64 encoding is used to avoid null bytes.
        charm_config = base64.b64encode(pickle.dumps({
            'STATE_FILE': self._state_file,
        }))

        # First run "install" to make sure all hooks are set up.
        state = self._simulate_event(EventSpec(InstallEvent, 'install', charm_config=charm_config))
        self.assertEqual(state['observed_event_types'], [InstallEvent])

        state = self._simulate_event(EventSpec(ConfigChangedEvent, 'config-changed', charm_config=charm_config))
        self.assertEqual(state['observed_event_types'], [ConfigChangedEvent])

        # Re-emit should pick the deferred config-changed.
        state = self._simulate_event(EventSpec(UpdateStatusEvent, 'update-status', charm_config=charm_config))
        self.assertEqual(state['observed_event_types'], [ConfigChangedEvent, UpdateStatusEvent])

    def test_multiple_events_handled(self):
        charm_config = base64.b64encode(pickle.dumps({
            'STATE_FILE': self._state_file,
        }))

        # Sample events with a different amount of dashes used
        # and with endpoints from different sections of metadata.yaml
        events_under_test = [(
            EventSpec(InstallEvent, 'install', charm_config=charm_config),
            {},
        ), (
            EventSpec(UpdateStatusEvent, 'update_status', charm_config=charm_config),
            {},
        ), (
            EventSpec(LeaderSettingsChangedEvent, 'leader_settings_changed', charm_config=charm_config),
            {},
        ), (
            EventSpec(RelationJoinedEvent, 'db_relation_joined', relation_id=1,
                      remote_app='remote', remote_unit='remote/0', charm_config=charm_config),
            {'relation_name': 'db', 'relation_id': 1, 'app_name': 'remote', 'unit_name': 'remote/0'},
        ), (
            EventSpec(RelationChangedEvent, 'mon_relation_changed', relation_id=2,
                      remote_app='remote', remote_unit='remote/0', charm_config=charm_config),
            {'relation_name': 'mon', 'relation_id': 2, 'app_name': 'remote', 'unit_name': 'remote/0'},
        ), (
            EventSpec(RelationChangedEvent, 'mon_relation_changed', relation_id=2,
                      remote_app='remote', remote_unit=None, charm_config=charm_config),
            {'relation_name': 'mon', 'relation_id': 2, 'app_name': 'remote', 'unit_name': None},
        ), (
            EventSpec(RelationDepartedEvent, 'mon_relation_departed', relation_id=2,
                      remote_app='remote', remote_unit='remote/0', charm_config=charm_config),
            {'relation_name': 'mon', 'relation_id': 2, 'app_name': 'remote', 'unit_name': 'remote/0'},
        ), (
            EventSpec(RelationBrokenEvent, 'ha_relation_broken', relation_id=3,
                      charm_config=charm_config),
            {'relation_name': 'ha', 'relation_id': 3},
        ), (
            # Events without a remote app specified (for Juju < 2.7).
            EventSpec(RelationJoinedEvent, 'db_relation_joined', relation_id=1,
                      remote_unit='remote/0', charm_config=charm_config),
            {'relation_name': 'db', 'relation_id': 1, 'app_name': 'remote', 'unit_name': 'remote/0'},
        ), (
            EventSpec(RelationChangedEvent, 'mon_relation_changed', relation_id=2,
                      remote_unit='remote/0', charm_config=charm_config),
            {'relation_name': 'mon', 'relation_id': 2, 'app_name': 'remote', 'unit_name': 'remote/0'},
        ), (
            EventSpec(RelationDepartedEvent, 'mon_relation_departed', relation_id=2,
                      remote_unit='remote/0', charm_config=charm_config),
            {'relation_name': 'mon', 'relation_id': 2, 'app_name': 'remote', 'unit_name': 'remote/0'},
        )]

        logger.debug(f'Expected events {events_under_test}')

        # First run "install" to make sure all hooks are set up.
        self._simulate_event(EventSpec(InstallEvent, 'install', charm_config=charm_config))

        # Simulate hook executions for every event.
        for event_spec, expected_event_data in events_under_test:
            state = self._simulate_event(event_spec)

            handled_events = state.get(f'on_{event_spec.event_name}', [])

            # Make sure that a handler for that event was called once.
            self.assertEqual(len(handled_events), 1)
            # Make sure the event handled by the Charm has the right type.
            handled_event_type = handled_events[0]
            self.assertEqual(handled_event_type, event_spec.event_type)

            self.assertEqual(state['observed_event_types'], [event_spec.event_type])

            if event_spec.event_name in expected_event_data:
                self.assertEqual(state[f'{event_spec.event_name}_data'], expected_event_data[event_spec.event_name])

    def test_event_not_implemented(self):
        """Make sure events without implementation do not cause non-zero exit.
        """
        charm_config = base64.b64encode(pickle.dumps({
            'STATE_FILE': self._state_file,
        }))

        # Simulate a scenario where there is a symlink for an event that
        # a charm does not know how to handle.
        hook_path = JUJU_CHARM_DIR / 'hooks/not-implemented-event'
        # This will be cleared up in tearDown.
        hook_path.symlink_to('install')

        try:
            self._simulate_event(EventSpec(HookEvent, 'not-implemented-event', charm_config=charm_config))
        except subprocess.CalledProcessError:
            self.fail('Event simulation for an unsupported event'
                      ' results in a non-zero exit code returned')

    def test_setup_hooks(self):
        """Test auto-creation of symlinks for supported events.
        """
        event_hooks = [f'hooks/{e.replace("_", "-")}'
                       for e in charm.Charm.on.events().keys()
                       if e != 'install']

        install_link_path = JUJU_CHARM_DIR / 'hooks/install'

        # The symlink is expected to be present in the source tree.
        self.assertTrue(install_link_path.exists())
        # It has to point to main.py in the lib directory of the charm.
        self.assertEqual(os.readlink(install_link_path), self.CHARM_PY_RELPATH)

        def _assess_setup_hooks(event_spec):
            event_hook = JUJU_CHARM_DIR / f'hooks/{event_spec.event_name}'

            # Simulate a fork + exec of a hook from a unit agent.
            self._simulate_event(event_spec)

            r, _, files = next(os.walk(JUJU_CHARM_DIR / 'hooks'))

            self.assertTrue(event_spec.event_name in files)

            for event_hook in event_hooks:
                self.assertTrue(os.path.exists(event_hook))
                self.assertEqual(os.readlink(event_hook), 'install')
                self.assertEqual(os.readlink('hooks/install'),
                                 self.CHARM_PY_RELPATH)

        charm_config = base64.b64encode(pickle.dumps({
            'STATE_FILE': self._state_file,
        }))

        # Assess 'install' first because upgrade-charm or other
        # events cannot be handled before install creates symlinks for them.
        events_to_assess = (
            EventSpec(InstallEvent, 'install', charm_config=charm_config),
            EventSpec(StartEvent, 'start', charm_config=charm_config),
            EventSpec(ConfigChangedEvent, 'config-changed', charm_config=charm_config),
            EventSpec(LeaderElectedEvent, 'leader-elected', charm_config=charm_config),
            EventSpec(UpgradeCharmEvent, 'upgrade-charm', charm_config=charm_config),
            EventSpec(UpdateStatusEvent, 'update-status', charm_config=charm_config),
        )

        for event_spec in events_to_assess:
            _assess_setup_hooks(event_spec)

        self._clear_symlinks()

        # Storage hooks run before "install" so this case needs to be checked as well.
        events_to_assess = (
            EventSpec(StorageAttachedEvent, 'disks-storage-attached', charm_config=charm_config),
            EventSpec(InstallEvent, 'install', charm_config=charm_config),
            EventSpec(StartEvent, 'start', charm_config=charm_config),
            EventSpec(ConfigChangedEvent, 'config-changed', charm_config=charm_config),
            EventSpec(LeaderElectedEvent, 'leader-elected', charm_config=charm_config),
            EventSpec(UpgradeCharmEvent, 'upgrade-charm', charm_config=charm_config),
            EventSpec(UpdateStatusEvent, 'update-status', charm_config=charm_config),
        )

        for event_spec in events_to_assess:
            _assess_setup_hooks(event_spec)


if __name__ == "__main__":
    unittest.main()
