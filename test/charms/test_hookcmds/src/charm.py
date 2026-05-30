#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
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

"""Test charm for ops.hookcmds integration tests.

Each action exercises a distinct area of the hookcmds public API so that the
integration-test suite can verify real Juju output is parsed correctly by the
hookcmds wrapper functions.
"""

from __future__ import annotations

import json
from typing import Any

import ops
import ops.hookcmds as hookcmds


class TestHookcmdsCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on.start, self._on_start)
        framework.observe(self.on['get-status'].action, self._on_get_status)
        framework.observe(self.on['set-and-check-status'].action, self._on_set_and_check_status)
        framework.observe(self.on['get-all-config'].action, self._on_get_all_config)
        framework.observe(self.on['get-config-value'].action, self._on_get_config_value)
        framework.observe(self.on['check-leadership'].action, self._on_check_leadership)
        framework.observe(self.on['test-logging'].action, self._on_test_logging)
        framework.observe(self.on['set-app-version'].action, self._on_set_app_version)
        framework.observe(self.on['get-network-info'].action, self._on_get_network_info)
        framework.observe(self.on['test-ports'].action, self._on_test_ports)
        framework.observe(self.on['test-unit-state'].action, self._on_test_unit_state)
        framework.observe(self.on['test-secret-crud'].action, self._on_test_secret_crud)
        framework.observe(self.on['test-goal-state'].action, self._on_test_goal_state)
        framework.observe(self.on['test-relation-data'].action, self._on_test_relation_data)
        framework.observe(self.on['test-storage'].action, self._on_test_storage)
        framework.observe(self.on['test-action-params'].action, self._on_test_action_params)
        framework.observe(self.on['fail-action'].action, self._on_fail_action)

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------

    def _on_start(self, event: ops.StartEvent):
        self.unit.status = ops.ActiveStatus()

    # -------------------------------------------------------------------------
    # Status
    # -------------------------------------------------------------------------

    def _on_get_status(self, event: ops.ActionEvent):
        """Return unit and (if leader) app status via hookcmds."""
        unit_st = hookcmds.status_get()
        results: dict[str, Any] = {
            'unit-status': unit_st.status,
            'unit-message': unit_st.message,
        }
        if hookcmds.is_leader():
            app_st = hookcmds.status_get(app=True)
            results['app-status'] = app_st.status
            results['app-message'] = app_st.message
            results['app-unit-count'] = str(len(app_st.units))
        event.set_results(results)

    def _on_set_and_check_status(self, event: ops.ActionEvent):
        """Set unit status then read it back."""
        status = event.params['status']
        message = event.params.get('message') or None
        hookcmds.status_set(status, message)
        unit_st = hookcmds.status_get()
        event.set_results({
            'status': unit_st.status,
            'message': unit_st.message,
        })
        # Restore active so the unit does not stay in a non-active state.
        hookcmds.status_set('active')

    # -------------------------------------------------------------------------
    # Config
    # -------------------------------------------------------------------------

    def _on_get_all_config(self, event: ops.ActionEvent):
        """Return all config as a JSON string."""
        config = hookcmds.config_get()
        event.set_results({'config': json.dumps(config)})

    def _on_get_config_value(self, event: ops.ActionEvent):
        """Return a single config value and its Python type name."""
        key = event.params['key']
        value = hookcmds.config_get(key)
        event.set_results({'value': str(value), 'type': type(value).__name__})

    # -------------------------------------------------------------------------
    # Leadership
    # -------------------------------------------------------------------------

    def _on_check_leadership(self, event: ops.ActionEvent):
        leader = hookcmds.is_leader()
        event.set_results({'is-leader': str(leader).lower()})

    # -------------------------------------------------------------------------
    # Logging
    # -------------------------------------------------------------------------

    def _on_test_logging(self, event: ops.ActionEvent):
        """Call juju_log at every supported level; return ok on success."""
        message = event.params.get('message', 'integration test log message')
        for level in ('TRACE', 'DEBUG', 'INFO', 'WARNING', 'ERROR'):
            hookcmds.juju_log(f'[{level}] {message}', level=level)  # type: ignore[arg-type]
        event.set_results({'ok': 'true', 'levels-logged': '5'})

    # -------------------------------------------------------------------------
    # Application version
    # -------------------------------------------------------------------------

    def _on_set_app_version(self, event: ops.ActionEvent):
        version = event.params['version']
        hookcmds.app_version_set(version)
        event.set_results({'ok': 'true', 'version': version})

    # -------------------------------------------------------------------------
    # Network
    # -------------------------------------------------------------------------

    def _on_get_network_info(self, event: ops.ActionEvent):
        """Return network info for the 'peer' binding."""
        network = hookcmds.network_get('peer')
        bind_addrs = network.bind_addresses
        results: dict[str, Any] = {
            'bind-addresses-count': str(len(bind_addrs)),
            'egress-subnets': ','.join(str(s) for s in network.egress_subnets),
            'ingress-addresses': ','.join(str(a) for a in network.ingress_addresses),
            'has-bind-addresses': str(len(bind_addrs) > 0).lower(),
        }
        if bind_addrs:
            first = bind_addrs[0]
            results['interface-name'] = first.interface_name
            if first.addresses:
                results['first-address'] = first.addresses[0].value
        event.set_results(results)

    # -------------------------------------------------------------------------
    # Ports
    # -------------------------------------------------------------------------

    def _on_test_ports(self, event: ops.ActionEvent):
        """Open TCP+UDP ports, verify via opened_ports, then close and verify."""
        port = int(event.params.get('port', 8877))

        before = hookcmds.opened_ports()
        initial_count = len(before)

        # Open TCP
        hookcmds.open_port('tcp', port)
        after_tcp = hookcmds.opened_ports()

        # Open UDP same port
        hookcmds.open_port('udp', port)
        after_both = hookcmds.opened_ports()

        # Close TCP
        hookcmds.close_port('tcp', port)
        after_close_tcp = hookcmds.opened_ports()

        # Close UDP
        hookcmds.close_port('udp', port)
        final = hookcmds.opened_ports()

        tcp_opened = any(p.port == port and p.protocol == 'tcp' for p in after_tcp)
        udp_opened = any(p.port == port and p.protocol == 'udp' for p in after_both)
        tcp_closed = not any(p.port == port and p.protocol == 'tcp' for p in after_close_tcp)
        udp_still_open = any(p.port == port and p.protocol == 'udp' for p in after_close_tcp)
        back_to_initial = len(final) == initial_count

        event.set_results({
            'initial-count': str(initial_count),
            'after-open-tcp-count': str(len(after_tcp)),
            'after-open-both-count': str(len(after_both)),
            'after-close-tcp-count': str(len(after_close_tcp)),
            'final-count': str(len(final)),
            'tcp-was-opened': str(tcp_opened).lower(),
            'udp-was-opened': str(udp_opened).lower(),
            'tcp-was-closed': str(tcp_closed).lower(),
            'udp-still-open-after-tcp-close': str(udp_still_open).lower(),
            'back-to-initial': str(back_to_initial).lower(),
        })

    # -------------------------------------------------------------------------
    # Server-side state
    # -------------------------------------------------------------------------

    def _on_test_unit_state(self, event: ops.ActionEvent):
        """Full state lifecycle: set → get(key) → get(all) → delete → verify."""
        key = event.params['key']
        value = event.params['value']

        hookcmds.state_set({key: value})

        retrieved = hookcmds.state_get(key)
        all_state = hookcmds.state_get(None)

        hookcmds.state_delete(key)

        after_delete = hookcmds.state_get(None)

        event.set_results({
            'retrieved': retrieved,
            'types-match': str(retrieved == value).lower(),
            'key-in-all': str(key in all_state).lower(),
            'all-value-matches': str(all_state.get(key) == value).lower(),
            'key-deleted': str(key not in after_delete).lower(),
        })

    # -------------------------------------------------------------------------
    # Secrets
    # -------------------------------------------------------------------------

    def _on_test_secret_crud(self, event: ops.ActionEvent):
        """Full secret lifecycle: add → ids → info_get → get → set → remove."""
        # --- Create ---
        secret_id = hookcmds.secret_add(
            {'password': 'initial-secret', 'username': 'admin'},
            label='hookcmds-inttest',
            description='Created by ops.hookcmds integration test',
        )

        # --- List ---
        ids = hookcmds.secret_ids()

        # --- Metadata ---
        info = hookcmds.secret_info_get(id=secret_id)

        # --- Read initial content (tracked revision) ---
        content = hookcmds.secret_get(id=secret_id)

        # --- Update content → new revision ---
        hookcmds.secret_set(secret_id, content={'password': 'updated-secret', 'username': 'admin'})

        # --- Peek at latest revision without updating tracking ---
        latest = hookcmds.secret_get(id=secret_id, peek=True)

        # --- Update metadata only ---
        hookcmds.secret_set(secret_id, description='Updated by hookcmds test')
        updated_info = hookcmds.secret_info_get(id=secret_id)

        # --- Look up by label ---
        by_label = hookcmds.secret_get(label='hookcmds-inttest')

        # --- Remove first revision only ---
        hookcmds.secret_remove(secret_id, revision=1)

        # --- Remove all remaining revisions ---
        hookcmds.secret_remove(secret_id)

        event.set_results({
            'secret-id': secret_id,
            'in-ids-list': str(any(i in secret_id or secret_id in i for i in ids)).lower(),
            'initial-label': info.label or '',
            'initial-description': info.description or '',
            'initial-revision': str(info.revision),
            'initial-password': content.get('password', ''),
            'updated-password': latest.get('password', ''),
            'updated-description': updated_info.description or '',
            'label-lookup-password': by_label.get('password', ''),
        })

    # -------------------------------------------------------------------------
    # Goal state
    # -------------------------------------------------------------------------

    def _on_test_goal_state(self, event: ops.ActionEvent):
        gs = hookcmds.goal_state()
        unit_names = sorted(gs.units.keys())
        unit_statuses = [gs.units[n].status for n in unit_names]
        # Relations may be empty if no peer has joined yet.
        event.set_results({
            'unit-count': str(len(unit_names)),
            'unit-names': ','.join(unit_names),
            'unit-statuses': ','.join(unit_statuses),
            'relation-endpoint-count': str(len(gs.relations)),
        })

    # -------------------------------------------------------------------------
    # Relations
    # -------------------------------------------------------------------------

    def _on_test_relation_data(self, event: ops.ActionEvent):
        """relation_ids → relation_list → relation_set → relation_get."""
        ids = hookcmds.relation_ids('peer')
        if not ids:
            event.fail('No peer relation IDs - is there more than one unit?')
            return

        # IDs are returned as "endpoint:N" strings; extract the integer part.
        rel_id = int(ids[0].split(':')[-1])

        # List other units in the relation.
        members = hookcmds.relation_list(rel_id)

        # Write data into our own unit's relation bag.
        test_key = 'hookcmds-inttest'
        test_value = 'verified-by-integration-test'
        hookcmds.relation_set({test_key: test_value}, rel_id)

        # Read our own unit's data back by key.
        unit_name = self.unit.name
        retrieved_key = hookcmds.relation_get(rel_id, key=test_key, unit=unit_name)

        # Read all data for our own unit.
        all_data = hookcmds.relation_get(rel_id, unit=unit_name)

        event.set_results({
            'relation-id-str': ids[0],
            'relation-id-int': str(rel_id),
            'member-count': str(len(members)),
            'set-value': test_value,
            'retrieved-value': retrieved_key,
            'values-match': str(retrieved_key == test_value).lower(),
            'key-in-all-data': str(test_key in all_data).lower(),
        })

    # -------------------------------------------------------------------------
    # Storage
    # -------------------------------------------------------------------------

    def _on_test_storage(self, event: ops.ActionEvent):
        """storage_list → storage_list(name) → storage_get."""
        all_storage = hookcmds.storage_list()
        data_storage = hookcmds.storage_list('data')

        if data_storage:
            info = hookcmds.storage_get(data_storage[0])
            event.set_results({
                'total-storage-count': str(len(all_storage)),
                'data-storage-count': str(len(data_storage)),
                'storage-id': data_storage[0],
                'storage-kind': info.kind,
                'storage-location': str(info.location),
                'has-location': str(bool(info.location)).lower(),
            })
        else:
            event.set_results({
                'total-storage-count': str(len(all_storage)),
                'data-storage-count': '0',
                'note': 'no data storage found',
            })

    # -------------------------------------------------------------------------
    # Action commands (action_get / action_log / action_set)
    # -------------------------------------------------------------------------

    def _on_test_action_params(self, event: ops.ActionEvent):
        """Use hookcmds action_get / action_log / action_set directly."""
        # Read all params via hookcmds (bypasses event.params).
        all_params = hookcmds.action_get()

        # Read a specific param.
        message = hookcmds.action_get('message')

        # Log progress via hookcmds.
        hookcmds.action_log(f'Echoing message: {message}')

        # Write results via hookcmds (bypasses event.set_results).
        hookcmds.action_set({
            'received': str(message),
            'param-count': str(len(all_params)),
        })

    # -------------------------------------------------------------------------
    # Action failure path
    # -------------------------------------------------------------------------

    def _on_fail_action(self, event: ops.ActionEvent):
        """Call hookcmds.action_fail to deliberately fail the action."""
        msg = event.params.get('message', 'deliberate failure from hookcmds test')
        hookcmds.action_fail(msg)


if __name__ == '__main__':
    ops.main(TestHookcmdsCharm)
