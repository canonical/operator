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

import os
import base64
import pickle
import sys
import logging

sys.path.append('lib')

from ops.charm import CharmBase  # noqa: E402 (module-level import after non-import code)
from ops.main import main        # noqa: E402 (ditto)

logger = logging.getLogger()


class Charm(CharmBase):

    def __init__(self, *args):
        super().__init__(*args)

        # This environment variable controls the test charm behavior.
        charm_config = os.environ.get('CHARM_CONFIG')
        if charm_config is not None:
            self._charm_config = pickle.loads(base64.b64decode(charm_config))
        else:
            self._charm_config = {}

        # TODO: refactor to use StoredState
        # (this implies refactoring most of test_main.py)
        self._state_file = self._charm_config.get('STATE_FILE')
        try:
            with open(str(self._state_file), 'rb') as f:
                self._state = pickle.load(f)
        except (FileNotFoundError, EOFError):
            self._state = {
                'on_install': [],
                'on_start': [],
                'on_config_changed': [],
                'on_update_status': [],
                'on_leader_settings_changed': [],
                'on_db_relation_joined': [],
                'on_mon_relation_changed': [],
                'on_mon_relation_departed': [],
                'on_ha_relation_broken': [],
                'on_foo_bar_action': [],
                'on_start_action': [],
                '_on_get_model_name_action': [],
                'on_collect_metrics': [],

                'on_log_critical_action': [],
                'on_log_error_action': [],
                'on_log_warning_action': [],
                'on_log_info_action': [],
                'on_log_debug_action': [],

                # Observed event types per invocation. A list is used to preserve the
                # order in which charm handlers have observed the events.
                'observed_event_types': [],
            }

        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.start, self._on_start)
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.update_status, self._on_update_status)
        self.framework.observe(self.on.leader_settings_changed, self._on_leader_settings_changed)
        # Test relation events with endpoints from different
        # sections (provides, requires, peers) as well.
        self.framework.observe(self.on.db_relation_joined, self._on_db_relation_joined)
        self.framework.observe(self.on.mon_relation_changed, self._on_mon_relation_changed)
        self.framework.observe(self.on.mon_relation_departed, self._on_mon_relation_departed)
        self.framework.observe(self.on.ha_relation_broken, self._on_ha_relation_broken)

        if self._charm_config.get('USE_ACTIONS'):
            self.framework.observe(self.on.start_action, self._on_start_action)
            self.framework.observe(self.on.foo_bar_action, self._on_foo_bar_action)
            self.framework.observe(self.on.get_model_name_action, self._on_get_model_name_action)
            self.framework.observe(self.on.get_status_action, self._on_get_status_action)

        self.framework.observe(self.on.collect_metrics, self._on_collect_metrics)

        if self._charm_config.get('USE_LOG_ACTIONS'):
            self.framework.observe(self.on.log_critical_action, self._on_log_critical_action)
            self.framework.observe(self.on.log_error_action, self._on_log_error_action)
            self.framework.observe(self.on.log_warning_action, self._on_log_warning_action)
            self.framework.observe(self.on.log_info_action, self._on_log_info_action)
            self.framework.observe(self.on.log_debug_action, self._on_log_debug_action)

        if self._charm_config.get('TRY_EXCEPTHOOK'):
            raise RuntimeError("failing as requested")

    def _write_state(self):
        """Write state variables so that the parent process can read them.

        Each invocation will override the previous state which is intentional.
        """
        if self._state_file is not None:
            with self._state_file.open('wb') as f:
                pickle.dump(self._state, f)

    def _on_install(self, event):
        self._state['on_install'].append(type(event))
        self._state['observed_event_types'].append(type(event))
        self._write_state()

    def _on_start(self, event):
        self._state['on_start'].append(type(event))
        self._state['observed_event_types'].append(type(event))
        self._write_state()

    def _on_config_changed(self, event):
        self._state['on_config_changed'].append(type(event))
        self._state['observed_event_types'].append(type(event))
        event.defer()
        self._write_state()

    def _on_update_status(self, event):
        self._state['on_update_status'].append(type(event))
        self._state['observed_event_types'].append(type(event))
        self._write_state()

    def _on_leader_settings_changed(self, event):
        self._state['on_leader_settings_changed'].append(type(event))
        self._state['observed_event_types'].append(type(event))
        self._write_state()

    def _on_db_relation_joined(self, event):
        assert event.app is not None, 'application name cannot be None for a relation-joined event'
        self._state['on_db_relation_joined'].append(type(event))
        self._state['observed_event_types'].append(type(event))
        self._state['db_relation_joined_data'] = event.snapshot()
        self._write_state()

    def _on_mon_relation_changed(self, event):
        assert event.app is not None, (
            'application name cannot be None for a relation-changed event')
        if os.environ.get('JUJU_REMOTE_UNIT'):
            assert event.unit is not None, (
                'a unit name cannot be None for a relation-changed event'
                ' associated with a remote unit')
        self._state['on_mon_relation_changed'].append(type(event))
        self._state['observed_event_types'].append(type(event))
        self._state['mon_relation_changed_data'] = event.snapshot()
        self._write_state()

    def _on_mon_relation_departed(self, event):
        assert event.app is not None, (
            'application name cannot be None for a relation-departed event')
        self._state['on_mon_relation_departed'].append(type(event))
        self._state['observed_event_types'].append(type(event))
        self._state['mon_relation_departed_data'] = event.snapshot()
        self._write_state()

    def _on_ha_relation_broken(self, event):
        assert event.app is None, (
            'relation-broken events cannot have a reference to a remote application')
        assert event.unit is None, (
            'relation broken events cannot have a reference to a remote unit')
        self._state['on_ha_relation_broken'].append(type(event))
        self._state['observed_event_types'].append(type(event))
        self._state['ha_relation_broken_data'] = event.snapshot()
        self._write_state()

    def _on_start_action(self, event):
        assert event.handle.kind == 'start_action', (
            'event action name cannot be different from the one being handled')
        self._state['on_start_action'].append(type(event))
        self._state['observed_event_types'].append(type(event))
        self._write_state()

    def _on_foo_bar_action(self, event):
        assert event.handle.kind == 'foo_bar_action', (
            'event action name cannot be different from the one being handled')
        self._state['on_foo_bar_action'].append(type(event))
        self._state['observed_event_types'].append(type(event))
        self._write_state()

    def _on_get_status_action(self, event):
        self._state['status_name'] = self.unit.status.name
        self._state['status_message'] = self.unit.status.message
        self._write_state()

    def _on_collect_metrics(self, event):
        self._state['on_collect_metrics'].append(type(event))
        self._state['observed_event_types'].append(type(event))
        event.add_metrics({'foo': 42}, {'bar': 4.2})
        self._write_state()

    def _on_log_critical_action(self, event):
        logger.critical('super critical')

    def _on_log_error_action(self, event):
        logger.error('grave error')

    def _on_log_warning_action(self, event):
        logger.warning('wise warning')

    def _on_log_info_action(self, event):
        logger.info('useful info')

    def _on_log_debug_action(self, event):
        logger.debug('insightful debug')

    def _on_get_model_name_action(self, event):
        self._state['_on_get_model_name_action'].append(self.model.name)
        self._write_state()


if __name__ == '__main__':
    main(Charm)
