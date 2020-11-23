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
import sys
import logging

sys.path.append('lib')

from ops.charm import CharmBase  # noqa: E402 (module-level import after non-import code)
from ops.framework import StoredState  # noqa: E402
from ops.main import main        # noqa: E402 (ditto)

logger = logging.getLogger()


class Charm(CharmBase):

    _stored = StoredState()

    def __init__(self, *args):
        super().__init__(*args)

        self._stored.set_default(
            try_excepthook=False,

            on_install=[],
            on_start=[],
            on_config_changed=[],
            on_update_status=[],
            on_leader_settings_changed=[],
            on_db_relation_joined=[],
            on_mon_relation_changed=[],
            on_mon_relation_departed=[],
            on_ha_relation_broken=[],
            on_foo_bar_action=[],
            on_start_action=[],
            _on_get_model_name_action=[],
            on_collect_metrics=[],

            on_log_critical_action=[],
            on_log_error_action=[],
            on_log_warning_action=[],
            on_log_info_action=[],
            on_log_debug_action=[],

            # Observed event type names per invocation. A list is used to preserve the
            # order in which charm handlers have observed the events.
            observed_event_types=[],
        )

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

        actions = self.charm_dir / 'actions.yaml'
        if actions.exists() and actions.read_bytes():
            self.framework.observe(self.on.start_action, self._on_start_action)
            self.framework.observe(self.on.foo_bar_action, self._on_foo_bar_action)
            self.framework.observe(self.on.get_model_name_action, self._on_get_model_name_action)
            self.framework.observe(self.on.get_status_action, self._on_get_status_action)

            self.framework.observe(self.on.log_critical_action, self._on_log_critical_action)
            self.framework.observe(self.on.log_error_action, self._on_log_error_action)
            self.framework.observe(self.on.log_warning_action, self._on_log_warning_action)
            self.framework.observe(self.on.log_info_action, self._on_log_info_action)
            self.framework.observe(self.on.log_debug_action, self._on_log_debug_action)

        self.framework.observe(self.on.collect_metrics, self._on_collect_metrics)

        if os.getenv('TRY_EXCEPTHOOK', False):
            raise RuntimeError("failing as requested")

    def _on_install(self, event):
        self._stored.on_install.append(type(event).__name__)
        self._stored.observed_event_types.append(type(event).__name__)

    def _on_start(self, event):
        self._stored.on_start.append(type(event).__name__)
        self._stored.observed_event_types.append(type(event).__name__)

    def _on_config_changed(self, event):
        self._stored.on_config_changed.append(type(event).__name__)
        self._stored.observed_event_types.append(type(event).__name__)
        event.defer()

    def _on_update_status(self, event):
        self._stored.on_update_status.append(type(event).__name__)
        self._stored.observed_event_types.append(type(event).__name__)

    def _on_leader_settings_changed(self, event):
        self._stored.on_leader_settings_changed.append(type(event).__name__)
        self._stored.observed_event_types.append(type(event).__name__)

    def _on_db_relation_joined(self, event):
        assert event.app is not None, 'application name cannot be None for a relation-joined event'
        self._stored.on_db_relation_joined.append(type(event).__name__)
        self._stored.observed_event_types.append(type(event).__name__)
        self._stored.db_relation_joined_data = event.snapshot()

    def _on_mon_relation_changed(self, event):
        assert event.app is not None, (
            'application name cannot be None for a relation-changed event')
        if os.environ.get('JUJU_REMOTE_UNIT'):
            assert event.unit is not None, (
                'a unit name cannot be None for a relation-changed event'
                ' associated with a remote unit')
        self._stored.on_mon_relation_changed.append(type(event).__name__)
        self._stored.observed_event_types.append(type(event).__name__)
        self._stored.mon_relation_changed_data = event.snapshot()

    def _on_mon_relation_departed(self, event):
        assert event.app is not None, (
            'application name cannot be None for a relation-departed event')
        self._stored.on_mon_relation_departed.append(type(event).__name__)
        self._stored.observed_event_types.append(type(event).__name__)
        self._stored.mon_relation_departed_data = event.snapshot()

    def _on_ha_relation_broken(self, event):
        assert event.app is None, (
            'relation-broken events cannot have a reference to a remote application')
        assert event.unit is None, (
            'relation broken events cannot have a reference to a remote unit')
        self._stored.on_ha_relation_broken.append(type(event).__name__)
        self._stored.observed_event_types.append(type(event).__name__)
        self._stored.ha_relation_broken_data = event.snapshot()

    def _on_start_action(self, event):
        assert event.handle.kind == 'start_action', (
            'event action name cannot be different from the one being handled')
        self._stored.on_start_action.append(type(event).__name__)
        self._stored.observed_event_types.append(type(event).__name__)

    def _on_foo_bar_action(self, event):
        assert event.handle.kind == 'foo_bar_action', (
            'event action name cannot be different from the one being handled')
        self._stored.on_foo_bar_action.append(type(event).__name__)
        self._stored.observed_event_types.append(type(event).__name__)

    def _on_get_status_action(self, event):
        self._stored.status_name = self.unit.status.name
        self._stored.status_message = self.unit.status.message

    def _on_collect_metrics(self, event):
        self._stored.on_collect_metrics.append(type(event).__name__)
        self._stored.observed_event_types.append(type(event).__name__)
        event.add_metrics({'foo': 42}, {'bar': 4.2})

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
        self._stored._on_get_model_name_action.append(self.model.name)


if __name__ == '__main__':
    main(Charm)
