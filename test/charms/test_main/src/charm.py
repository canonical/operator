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

import logging
import os
import sys
import typing

import ops

sys.path.append('lib')


logger = logging.getLogger()


class CustomEvent(ops.EventBase):
    pass


class MyCharmEvents(ops.CharmEvents):
    custom = ops.EventSource(CustomEvent)


class Charm(ops.CharmBase):
    on = MyCharmEvents()  # type: ignore

    _stored = ops.StoredState()

    def __init__(self, *args: typing.Any):
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
            on_test_pebble_ready=[],
            on_test_pebble_custom_notice=[],
            on_test_pebble_check_failed=[],
            on_test_pebble_check_recovered=[],
            on_log_critical_action=[],
            on_log_error_action=[],
            on_log_warning_action=[],
            on_log_info_action=[],
            on_log_debug_action=[],
            on_secret_changed=[],
            on_secret_remove=[],
            on_secret_rotate=[],
            on_secret_expired=[],
            on_custom=[],
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
        self.framework.observe(self.on.test_pebble_ready, self._on_test_pebble_ready)
        self.framework.observe(
            self.on.test_pebble_custom_notice, self._on_test_pebble_custom_notice
        )
        self.framework.observe(self.on.test_pebble_check_failed, self._on_test_pebble_check_failed)
        self.framework.observe(
            self.on.test_pebble_check_recovered, self._on_test_pebble_check_recovered
        )

        self.framework.observe(self.on.secret_remove, self._on_secret_remove)
        self.framework.observe(self.on.secret_rotate, self._on_secret_rotate)
        self.framework.observe(self.on.secret_changed, self._on_secret_changed)
        self.framework.observe(self.on.secret_expired, self._on_secret_expired)

        actions = self.charm_dir / 'actions.yaml'
        if actions.exists() and actions.read_bytes():
            self.framework.observe(self.on.start_action, self._on_start_action)
            self.framework.observe(self.on.foo_bar_action, self._on_foo_bar_action)
            self.framework.observe(self.on.get_model_name_action, self._on_get_model_name_action)
            self.framework.observe(self.on.get_status_action, self._on_get_status_action)
            self.framework.observe(self.on.keyerror_action, self._on_keyerror_action)

            self.framework.observe(self.on.log_critical_action, self._on_log_critical_action)
            self.framework.observe(self.on.log_error_action, self._on_log_error_action)
            self.framework.observe(self.on.log_warning_action, self._on_log_warning_action)
            self.framework.observe(self.on.log_info_action, self._on_log_info_action)
            self.framework.observe(self.on.log_debug_action, self._on_log_debug_action)

        self.framework.observe(self.on.collect_metrics, self._on_collect_metrics)
        self.framework.observe(self.on.custom, self._on_custom)

        if os.getenv('TRY_EXCEPTHOOK', False):
            raise RuntimeError('failing as requested')

    def _on_install(self, event: ops.InstallEvent):
        self._stored.on_install.append(type(event).__name__)
        self._stored.observed_event_types.append(type(event).__name__)

    def _on_start(self, event: ops.StartEvent):
        self._stored.on_start.append(type(event).__name__)
        self._stored.observed_event_types.append(type(event).__name__)

    def _on_config_changed(self, event: ops.ConfigChangedEvent):
        self._stored.on_config_changed.append(type(event).__name__)
        self._stored.observed_event_types.append(type(event).__name__)
        event.defer()

    def _on_update_status(self, event: ops.UpdateStatusEvent):
        self._stored.on_update_status.append(type(event).__name__)
        self._stored.observed_event_types.append(type(event).__name__)

        if os.getenv('EMIT_CUSTOM_EVENT'):
            self.on.custom.emit()

    def _on_leader_settings_changed(self, event: ops.LeaderSettingsChangedEvent):
        self._stored.on_leader_settings_changed.append(type(event).__name__)
        self._stored.observed_event_types.append(type(event).__name__)

    def _on_db_relation_joined(self, event: ops.RelationJoinedEvent):
        assert event.app is not None, 'application name cannot be None for a relation-joined event'
        assert event.relation.active, 'a joined relation is always active'
        assert self.model.relations['db']
        self._stored.on_db_relation_joined.append(type(event).__name__)
        self._stored.observed_event_types.append(type(event).__name__)
        self._stored.db_relation_joined_data = event.snapshot()

    def _on_mon_relation_changed(self, event: ops.RelationChangedEvent):
        assert (
            event.app is not None
        ), 'application name cannot be None for a relation-changed event'
        if os.environ.get('JUJU_REMOTE_UNIT'):
            assert event.unit is not None, (
                'a unit name cannot be None for a relation-changed event'
                ' associated with a remote unit'
            )
        assert event.relation.active, 'a changed relation is always active'
        assert self.model.relations['mon']
        self._stored.on_mon_relation_changed.append(type(event).__name__)
        self._stored.observed_event_types.append(type(event).__name__)
        self._stored.mon_relation_changed_data = event.snapshot()

    def _on_mon_relation_departed(self, event: ops.RelationDepartedEvent):
        assert (
            event.app is not None
        ), 'application name cannot be None for a relation-departed event'
        assert event.relation.active, 'a departed relation is still active'
        assert self.model.relations['mon']
        self._stored.on_mon_relation_departed.append(type(event).__name__)
        self._stored.observed_event_types.append(type(event).__name__)
        self._stored.mon_relation_departed_data = event.snapshot()

    def _on_ha_relation_broken(self, event: ops.RelationBrokenEvent):
        assert (
            event.app is None
        ), 'relation-broken events cannot have a reference to a remote application'
        assert (
            event.unit is None
        ), 'relation broken events cannot have a reference to a remote unit'
        assert not event.relation.active, 'relation broken events always have a broken relation'
        assert not self.model.relations['ha']
        self._stored.on_ha_relation_broken.append(type(event).__name__)
        self._stored.observed_event_types.append(type(event).__name__)
        self._stored.ha_relation_broken_data = event.snapshot()

    def _on_test_pebble_ready(self, event: ops.PebbleReadyEvent):
        assert event.workload is not None, 'workload events must have a reference to a container'
        self._stored.on_test_pebble_ready.append(type(event).__name__)
        self._stored.observed_event_types.append(type(event).__name__)
        self._stored.test_pebble_ready_data = event.snapshot()

    def _on_test_pebble_custom_notice(self, event: ops.PebbleCustomNoticeEvent):
        assert event.workload is not None
        assert isinstance(event.notice, ops.LazyNotice)
        self._stored.on_test_pebble_custom_notice.append(type(event).__name__)
        self._stored.observed_event_types.append(type(event).__name__)
        self._stored.test_pebble_custom_notice_data = event.snapshot()

    def _on_test_pebble_check_failed(self, event: ops.PebbleCheckFailedEvent):
        assert event.workload is not None, 'workload events must have a reference to a container'
        assert isinstance(event.info, ops.LazyCheckInfo)
        self._stored.on_test_pebble_check_failed.append(type(event).__name__)
        self._stored.observed_event_types.append(type(event).__name__)
        self._stored.test_pebble_check_failed_data = event.snapshot()

    def _on_test_pebble_check_recovered(self, event: ops.PebbleCheckRecoveredEvent):
        assert event.workload is not None, 'workload events must have a reference to a container'
        assert isinstance(event.info, ops.LazyCheckInfo)
        self._stored.on_test_pebble_check_recovered.append(type(event).__name__)
        self._stored.observed_event_types.append(type(event).__name__)
        self._stored.test_pebble_check_recovered_data = event.snapshot()

    def _on_start_action(self, event: ops.ActionEvent):
        assert (
            event.handle.kind == 'start_action'
        ), 'event action name cannot be different from the one being handled'
        self._stored.on_start_action.append(type(event).__name__)
        self._stored.observed_event_types.append(type(event).__name__)

    def _on_secret_changed(self, event: ops.SecretChangedEvent):
        # subprocess and isinstance don't mix well
        assert (
            type(event.secret).__name__ == 'Secret'
        ), f'SecretEvent.secret must be a Secret instance, not {type(event.secret)}'
        assert event.secret.id, 'secret must have an ID'
        self._stored.on_secret_changed.append(type(event).__name__)
        self._stored.observed_event_types.append(type(event).__name__)
        self._stored.secret_changed_data = event.snapshot()

    def _on_secret_remove(self, event: ops.SecretRemoveEvent):
        # subprocess and isinstance don't mix well
        assert (
            type(event.secret).__name__ == 'Secret'
        ), f'SecretEvent.secret must be a Secret instance, not {type(event.secret)}'
        assert event.secret.id, 'secret must have an ID'
        self._stored.on_secret_remove.append(type(event).__name__)
        self._stored.observed_event_types.append(type(event).__name__)
        self._stored.secret_remove_data = event.snapshot()

    def _on_secret_rotate(self, event: ops.SecretRotateEvent):
        # subprocess and isinstance don't mix well
        assert (
            type(event.secret).__name__ == 'Secret'
        ), f'SecretEvent.secret must be a Secret instance, not {type(event.secret)}'
        assert event.secret.id, 'secret must have an ID'
        self._stored.on_secret_rotate.append(type(event).__name__)
        self._stored.observed_event_types.append(type(event).__name__)
        self._stored.secret_rotate_data = event.snapshot()

    def _on_secret_expired(self, event: ops.SecretExpiredEvent):
        # subprocess and isinstance don't mix well
        assert (
            type(event.secret).__name__ == 'Secret'
        ), f'SecretEvent.secret must be a Secret instance, not {type(event.secret)}'
        assert event.secret.id, 'secret must have an ID'
        self._stored.on_secret_expired.append(type(event).__name__)
        self._stored.observed_event_types.append(type(event).__name__)
        self._stored.secret_expired_data = event.snapshot()

    def _on_foo_bar_action(self, event: ops.ActionEvent):
        assert (
            event.handle.kind == 'foo_bar_action'
        ), 'event action name cannot be different from the one being handled'
        self._stored.on_foo_bar_action.append(type(event).__name__)
        self._stored.observed_event_types.append(type(event).__name__)

    def _on_get_status_action(self, event: ops.ActionEvent):
        self._stored.status_name = self.unit.status.name
        self._stored.status_message = self.unit.status.message

    def _on_keyerror_action(self, event: ops.ActionEvent):
        # Deliberately raise an uncaught exception, so that we can observe the
        # behaviour when an action crashes.
        raise KeyError("'foo' not found in 'bar'")

    def _on_collect_metrics(self, event: ops.CollectMetricsEvent):
        self._stored.on_collect_metrics.append(type(event).__name__)
        self._stored.observed_event_types.append(type(event).__name__)
        event.add_metrics({'foo': 42}, {'bar': '4.2'})

    def _on_custom(self, event: MyCharmEvents):
        self._stored.on_custom.append(type(event).__name__)
        self._stored.observed_event_types.append(type(event).__name__)

    def _on_log_critical_action(self, event: ops.ActionEvent):
        logger.critical('super critical')

    def _on_log_error_action(self, event: ops.ActionEvent):
        logger.error('grave error')

    def _on_log_warning_action(self, event: ops.ActionEvent):
        logger.warning('wise warning')

    def _on_log_info_action(self, event: ops.ActionEvent):
        logger.info('useful info')

    def _on_log_debug_action(self, event: ops.ActionEvent):
        logger.debug('insightful debug')

    def _on_get_model_name_action(self, event: ops.ActionEvent):
        self._stored._on_get_model_name_action.append(self.model.name)


if __name__ == '__main__':
    ops.main(Charm)  # type: ignore
