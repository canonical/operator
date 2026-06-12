#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
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
        framework.observe(
            self.on['trigger-relation-error'].action, self._on_trigger_relation_error
        )
        framework.observe(self.on['test-credential-get'].action, self._on_test_credential_get)
        framework.observe(self.on['test-juju-reboot'].action, self._on_test_juju_reboot)
        framework.observe(
            self.on['test-relation-model-get'].action, self._on_test_relation_model_get
        )
        framework.observe(self.on['test-resource-get'].action, self._on_test_resource_get)
        framework.observe(self.on['test-secret-grant'].action, self._on_test_secret_grant)
        framework.observe(self.on['test-secret-revoke'].action, self._on_test_secret_revoke)
        framework.observe(self.on['test-storage-add'].action, self._on_test_storage_add)

    # Lifecycle

    def _on_start(self, event: ops.StartEvent):
        self.unit.status = ops.ActiveStatus()

    # Status

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

    # Config

    def _on_get_all_config(self, event: ops.ActionEvent):
        """Return all config as a JSON string."""
        config = hookcmds.config_get()
        event.set_results({'config': json.dumps(config)})

    def _on_get_config_value(self, event: ops.ActionEvent):
        """Return a single config value and its Python type name."""
        key = event.params['key']
        value = hookcmds.config_get(key)
        event.set_results({'value': str(value), 'type': type(value).__name__})

    # Leadership

    def _on_check_leadership(self, event: ops.ActionEvent):
        leader = hookcmds.is_leader()
        event.set_results({'is-leader': str(leader).lower()})

    # Logging

    def _on_test_logging(self, event: ops.ActionEvent):
        """Call juju_log at every supported level; running without error is the check."""
        message = event.params.get('message', 'integration test log message')
        for level in ('TRACE', 'DEBUG', 'INFO', 'WARNING', 'ERROR'):
            hookcmds.juju_log(f'[{level}] {message}', level=level)  # type: ignore[arg-type]

    # Application version

    def _on_set_app_version(self, event: ops.ActionEvent):
        version = event.params['version']
        hookcmds.app_version_set(version)

    # Network

    def _on_get_network_info(self, event: ops.ActionEvent):
        """Return raw network data for the 'peer' binding."""
        network = hookcmds.network_get('peer')
        bind_addresses = [
            {
                'interface-name': ba.interface_name,
                'mac-address': ba.mac_address,
                'addresses': [
                    {'value': a.value, 'cidr': a.cidr, 'hostname': a.hostname}
                    for a in ba.addresses
                ],
            }
            for ba in network.bind_addresses
        ]
        event.set_results({
            'bind-addresses': json.dumps(bind_addresses),
            'egress-subnets': json.dumps(list(network.egress_subnets)),
            'ingress-addresses': json.dumps(list(network.ingress_addresses)),
        })

    # Ports

    def _on_test_ports(self, event: ops.ActionEvent):
        """Open TCP+UDP ports, capture port lists at each step, then close both."""
        port = int(event.params.get('port', 8877))

        def _ports_json(ports: list) -> str:
            return json.dumps([{'protocol': p.protocol, 'port': p.port} for p in ports])

        before = hookcmds.opened_ports()
        hookcmds.open_port('tcp', port)
        after_tcp = hookcmds.opened_ports()
        hookcmds.open_port('udp', port)
        after_both = hookcmds.opened_ports()
        hookcmds.close_port('tcp', port)
        after_close_tcp = hookcmds.opened_ports()
        hookcmds.close_port('udp', port)
        final = hookcmds.opened_ports()

        event.set_results({
            'before': _ports_json(before),
            'after-open-tcp': _ports_json(after_tcp),
            'after-open-both': _ports_json(after_both),
            'after-close-tcp': _ports_json(after_close_tcp),
            'final': _ports_json(final),
        })

    # Server-side state

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
            'all-state': json.dumps(all_state),
            'after-delete': json.dumps(after_delete),
        })

    # Secrets

    def _on_test_secret_crud(self, event: ops.ActionEvent):
        """Full secret lifecycle: add → ids → info_get → get → set → remove."""
        secret_id = hookcmds.secret_add(
            {'password': 'initial-secret', 'username': 'admin'},
            label='hookcmds-inttest',
            description='Created by ops.hookcmds integration test',
        )
        ids = hookcmds.secret_ids()
        info = hookcmds.secret_info_get(id=secret_id)
        content = hookcmds.secret_get(id=secret_id)

        hookcmds.secret_set(secret_id, content={'password': 'updated-secret', 'username': 'admin'})
        # Peek at the latest revision without updating the tracked revision.
        latest = hookcmds.secret_get(id=secret_id, peek=True)

        hookcmds.secret_set(secret_id, description='Updated by hookcmds test')
        updated_info = hookcmds.secret_info_get(id=secret_id)

        by_label = hookcmds.secret_get(label='hookcmds-inttest')

        hookcmds.secret_remove(secret_id, revision=1)
        hookcmds.secret_remove(secret_id)

        event.set_results({
            'secret-id': secret_id,
            'secret-ids': json.dumps(ids),
            'initial-label': info.label or '',
            'initial-description': info.description or '',
            'initial-revision': str(info.revision),
            'initial-password': content.get('password', ''),
            'updated-password': latest.get('password', ''),
            'updated-description': updated_info.description or '',
            'label-lookup-password': by_label.get('password', ''),
        })

    # Goal state

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

    # Relations

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
            'retrieved-value': retrieved_key,
            'all-data': json.dumps(all_data),
        })

    # Storage

    def _on_test_storage(self, event: ops.ActionEvent):
        """storage_list → storage_list(name) → storage_get."""
        all_storage = hookcmds.storage_list()
        data_storage = hookcmds.storage_list('data')

        if not data_storage:
            event.fail('no data storage found')
            return
        info = hookcmds.storage_get(data_storage[0])
        event.set_results({
            'total-storage-count': str(len(all_storage)),
            'data-storage-count': str(len(data_storage)),
            'storage-id': data_storage[0],
            'storage-kind': info.kind,
            'storage-location': str(info.location),
        })

    # Action commands (action_get / action_log / action_set)

    def _on_test_action_params(self, event: ops.ActionEvent):
        """Use hookcmds action_get / action_log / action_set directly, bypassing the event API."""
        all_params = hookcmds.action_get()
        message = hookcmds.action_get('message')
        hookcmds.action_log(f'Echoing message: {message}')
        hookcmds.action_set({
            'received': str(message),
            'param-count': str(len(all_params)),
        })

    # Action failure path

    def _on_fail_action(self, event: ops.ActionEvent):
        """Call hookcmds.action_fail to deliberately fail the action."""
        msg = event.params.get('message', 'deliberate failure from hookcmds test')
        hookcmds.action_fail(msg)

    # Error path

    def _on_trigger_relation_error(self, event: ops.ActionEvent):
        """relation_list on a bogus id should raise hookcmds.Error."""
        relation_id = int(event.params['relation-id'])
        try:
            hookcmds.relation_list(relation_id)
        except hookcmds.Error as exc:
            event.set_results({
                'raised': type(exc).__name__,
                'message': str(exc),
            })
        else:
            event.set_results({'raised': 'none'})

    # Credentials

    def _on_test_credential_get(self, event: ops.ActionEvent):
        """Call credential_get and return cloud type and name."""
        cloud = hookcmds.credential_get()
        event.set_results({'cloud-type': cloud.type, 'cloud-name': cloud.name})

    # Reboot

    def _on_test_juju_reboot(self, event: ops.ActionEvent):
        """Queue a machine reboot via juju_reboot(now=False)."""
        hookcmds.juju_reboot(now=False)

    # Relation model

    def _on_test_relation_model_get(self, event: ops.ActionEvent):
        """Return the model UUID for the peer relation."""
        ids = hookcmds.relation_ids('peer')
        if not ids:
            event.fail('No peer relation IDs - deploy 2+ units')
            return
        rel_id = int(ids[0].split(':')[-1])
        model = hookcmds.relation_model_get(id=rel_id, endpoint='peer')
        event.set_results({'uuid': model.uuid})

    # Resource

    def _on_test_resource_get(self, event: ops.ActionEvent):
        """Return the cached path for the test-file resource."""
        path = hookcmds.resource_get('test-file')
        event.set_results({'path': str(path)})

    # Secret grant / revoke

    def _on_test_secret_grant(self, event: ops.ActionEvent):
        """Create a secret and grant it to the peer relation."""
        ids = hookcmds.relation_ids('peer')
        if not ids:
            event.fail('No peer relation - deploy 2+ units')
            return
        rel_id = int(ids[0].split(':')[-1])
        secret_id = hookcmds.secret_add({'key': 'grant-test-value'}, label='grant-test')
        hookcmds.secret_grant(secret_id, rel_id)
        event.set_results({'secret-id': secret_id})

    def _on_test_secret_revoke(self, event: ops.ActionEvent):
        """Revoke access to a secret from the peer relation."""
        secret_id = event.params['secret-id']
        ids = hookcmds.relation_ids('peer')
        if not ids:
            event.fail('No peer relation - deploy 2+ units')
            return
        rel_id = int(ids[0].split(':')[-1])
        hookcmds.secret_revoke(secret_id, relation_id=rel_id)

    # Storage add

    def _on_test_storage_add(self, event: ops.ActionEvent):
        """Queue one additional data storage and return the current count."""
        current = hookcmds.storage_list('data')
        hookcmds.storage_add({'data': 1})
        event.set_results({'count-before-add': str(len(current))})


if __name__ == '__main__':
    ops.main(TestHookcmdsCharm)
