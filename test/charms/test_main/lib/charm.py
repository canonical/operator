#!/usr/bin/env python3

import os
import base64
import pickle

from juju.charm import CharmBase

import logging

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

        self._state_file = self._charm_config.get('STATE_FILE')
        self._state = {}

        self._state['on_install'] = []
        self._state['on_config_changed'] = []
        self._state['on_update_status'] = []
        self._state['on_leader_settings_changed'] = []
        self._state['on_db_relation_joined'] = []
        self._state['on_mon_relation_changed'] = []
        self._state['on_ha_relation_broken'] = []

        # Observed event types per invocation. A list is used to preserve the order in which charm handlers have observed the events.
        self._state['observed_event_types'] = []

        self.framework.observe(self.on.install, self)
        self.framework.observe(self.on.config_changed, self)
        self.framework.observe(self.on.update_status, self)
        self.framework.observe(self.on.leader_settings_changed, self)
        # Test relation events with endpoints from different
        # sections (provides, requires, peers) as well.
        self.framework.observe(self.endpoints['db'].on.joined, self.on_db_relation_joined)
        self.framework.observe(self.endpoints['mon'].on.changed, self.on_mon_relation_changed)
        self.framework.observe(self.endpoints['ha'].on.broken, self.on_ha_relation_broken)

    def _write_state(self):
        """Write state variables so that the parent process can read them.

        Each invocation will override the previous state which is intentional.
        """
        if self._state_file is not None:
            with open(self._state_file, 'wb') as f:
                pickle.dump(self._state, f)

    def on_install(self, event):
        self._state['on_install'].append(type(event))
        self._state['observed_event_types'].append(type(event))
        self._write_state()

    def on_config_changed(self, event):
        self._state['on_config_changed'].append(type(event))
        self._state['observed_event_types'].append(type(event))
        event.defer()
        self._write_state()

    def on_update_status(self, event):
        self._state['on_update_status'].append(type(event))
        self._state['observed_event_types'].append(type(event))
        self._write_state()

    def on_leader_settings_changed(self, event):
        self._state['on_leader_settings_changed'].append(type(event))
        self._state['observed_event_types'].append(type(event))
        self._write_state()

    def on_db_relation_joined(self, event):
        self._state['on_db_relation_joined'].append(type(event))
        self._state['observed_event_types'].append(type(event))
        self._state['db_relation_joined_data'] = event.snapshot()
        self._write_state()

    def on_mon_relation_changed(self, event):
        self._state['on_mon_relation_changed'].append(type(event))
        self._state['observed_event_types'].append(type(event))
        self._state['mon_relation_changed_data'] = event.snapshot()
        self._write_state()

    def on_ha_relation_broken(self, event):
        self._state['on_ha_relation_broken'].append(type(event))
        self._state['observed_event_types'].append(type(event))
        self._state['ha_relation_broken_data'] = event.snapshot()
        self._write_state()
