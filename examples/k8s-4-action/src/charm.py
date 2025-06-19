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

"""Kubernetes charm for a demo app."""

from __future__ import annotations

import logging

# Import the 'data_interfaces' library.
# The import statement omits the top-level 'lib' directory
# because 'charmcraft pack' copies its contents to the project root.
from charms.data_platform_libs.v0.data_interfaces import DatabaseCreatedEvent, DatabaseRequires

import ops

# Log messages can be retrieved using juju debug-log
logger = logging.getLogger(__name__)


class FastAPIDemoCharm(ops.CharmBase):
    """Charm the service."""

    def __init__(self, framework: ops.Framework) -> None:
        super().__init__(framework)
        # See 'containers' in charmcraft.yaml.
        self.container = self.unit.get_container('demo-server')
        self.pebble_service_name = 'fastapi-service'
        framework.observe(self.on.demo_server_pebble_ready, self._on_demo_server_pebble_ready)
        framework.observe(self.on.config_changed, self._on_config_changed)
        # Report the unit status after each event.
        framework.observe(self.on.collect_unit_status, self._on_collect_status)
        # The 'relation_name' comes from the 'charmcraft.yaml file'.
        # The 'database_name' is the name of the database that our application requires.
        self.database = DatabaseRequires(self, relation_name='database', database_name='names_db')
        # See https://charmhub.io/data-platform-libs/libraries/data_interfaces
        framework.observe(self.database.on.database_created, self._on_database_created)
        framework.observe(self.database.on.endpoints_changed, self._on_database_created)
        # Events on charm actions that are run via 'juju run'.
        framework.observe(self.on.get_db_info_action, self._on_get_db_info_action)

    def _on_demo_server_pebble_ready(self, event: ops.PebbleReadyEvent) -> None:
        self._update_layer_and_restart()

    def _on_config_changed(self, event: ops.ConfigChangedEvent) -> None:
        port = self.config['server-port']  # See charmcraft.yaml

        if port == 22:
            # The collect-status handler will set the status to blocked.
            logger.debug('Invalid port number: 22 is reserved for SSH')
            return

        logger.debug('New application port is requested: %s', port)
        self._update_layer_and_restart()

    def _on_collect_status(self, event: ops.CollectStatusEvent) -> None:
        port = self.config['server-port']
        if port == 22:
            event.add_status(ops.BlockedStatus('Invalid port number, 22 is reserved for SSH'))
        if not self.model.get_relation('database'):
            # We need the user to do 'juju integrate'.
            event.add_status(ops.BlockedStatus('Waiting for database relation'))
        elif not self.database.fetch_relation_data():
            # We need the charms to finish integrating.
            event.add_status(ops.WaitingStatus('Waiting for database relation'))
        try:
            status = self.container.get_service(self.pebble_service_name)
        except (ops.pebble.APIError, ops.pebble.ConnectionError, ops.ModelError):
            event.add_status(ops.MaintenanceStatus('Waiting for Pebble in workload container'))
        else:
            if not status.is_running():
                event.add_status(ops.MaintenanceStatus('Waiting for the service to start up'))
        # If nothing is wrong, then the status is active.
        event.add_status(ops.ActiveStatus())

    def _on_database_created(self, event: DatabaseCreatedEvent) -> None:
        """Event is fired when postgres database is created."""
        self._update_layer_and_restart()

    def _on_get_db_info_action(self, event: ops.ActionEvent) -> None:
        """Return information about the integrated database.

        This method is called when "get_db_info" action is called. It shows information about
        database access points by calling the `fetch_postgres_relation_data` method and creates
        an output dictionary containing the host, port, if show_password is True, then include
        username, and password of the database.

        If the PostgreSQL charm is not integrated, the output is set to "No database connected".

        Learn more about actions at https://ops.readthedocs.io/en/latest/howto/manage-actions.html
        """
        show_password = event.params['show-password']  # see charmcraft.yaml
        db_data = self.fetch_postgres_relation_data()
        if not db_data:
            event.fail('No database connected')
            return
        output = {
            'db-host': db_data.get('db_host', None),
            'db-port': db_data.get('db_port', None),
        }
        if show_password:
            output.update({
                'db-username': db_data.get('db_username', None),
                'db-password': db_data.get('db_password', None),
            })
        event.set_results(output)

    def _update_layer_and_restart(self) -> None:
        """Define and start a workload using the Pebble API.

        You'll need to specify the right entrypoint and environment
        configuration for your specific workload. Tip: you can see the
        standard entrypoint of an existing container using docker inspect
        Learn more about interacting with Pebble at
            https://ops.readthedocs.io/en/latest/reference/pebble.html
        Learn more about Pebble layers at
            https://documentation.ubuntu.com/pebble/how-to/use-layers/
        """
        # Learn more about statuses at
        # https://documentation.ubuntu.com/juju/3.6/reference/status/
        self.unit.status = ops.MaintenanceStatus('Assembling Pebble layers')
        try:
            self.container.add_layer('fastapi_demo', self._pebble_layer, combine=True)
            logger.info("Added updated layer 'fastapi_demo' to Pebble plan")

            # Tell Pebble to incorporate the changes, including restarting the
            # service if required.
            self.container.replan()
            logger.info(f"Replanned with '{self.pebble_service_name}' service")

            self.unit.status = ops.ActiveStatus()
        except (ops.pebble.APIError, ops.pebble.ConnectionError) as e:
            logger.info('Unable to connect to Pebble: %s', e)

    @property
    def _pebble_layer(self) -> ops.pebble.Layer:
        """A Pebble layer for the FastAPI demo services."""
        command = ' '.join([
            'uvicorn',
            'api_demo_server.app:app',
            '--host=0.0.0.0',
            f'--port={self.config["server-port"]}',
        ])
        pebble_layer: ops.pebble.LayerDict = {
            'summary': 'FastAPI demo service',
            'description': 'pebble config layer for FastAPI demo server',
            'services': {
                self.pebble_service_name: {
                    'override': 'replace',
                    'summary': 'fastapi demo',
                    'command': command,
                    'startup': 'enabled',
                    'environment': self.app_environment,
                }
            },
        }
        return ops.pebble.Layer(pebble_layer)

    @property
    def app_environment(self) -> dict[str, str]:
        """Prepare environment variables for the application.

        This property method creates a dictionary containing environment variables
        for the application. It retrieves the database authentication data by calling
        the `fetch_postgres_relation_data` method and uses it to populate the dictionary.
        If any of the values are not present, it will be set to None.
        The method returns this dictionary as output.
        """
        db_data = self.fetch_postgres_relation_data()
        if not db_data:
            return {}
        env = {
            key: value
            for key, value in {
                'DEMO_SERVER_DB_HOST': db_data.get('db_host', None),
                'DEMO_SERVER_DB_PORT': db_data.get('db_port', None),
                'DEMO_SERVER_DB_USER': db_data.get('db_username', None),
                'DEMO_SERVER_DB_PASSWORD': db_data.get('db_password', None),
            }.items()
            if value is not None
        }
        return env

    def fetch_postgres_relation_data(self) -> dict[str, str]:
        """Fetch postgres relation data.

        This function retrieves relation data from a postgres database using
        the `fetch_relation_data` method of the `database` object. The retrieved data is
        then logged for debugging purposes, and any non-empty data is processed to extract
        endpoint information, username, and password. This processed data is then returned as
        a dictionary. If no data is retrieved, the unit is set to waiting status and
        the program exits with a zero status code.
        """
        relations = self.database.fetch_relation_data()
        logger.debug('Got following database data: %s', relations)
        for data in relations.values():
            if not data:
                continue
            logger.info('New PSQL database endpoint is %s', data['endpoints'])
            host, port = data['endpoints'].split(':')
            db_data = {
                'db_host': host,
                'db_port': port,
                'db_username': data['username'],
                'db_password': data['password'],
            }
            return db_data
        return {}


if __name__ == '__main__':  # pragma: nocover
    ops.main(FastAPIDemoCharm)
