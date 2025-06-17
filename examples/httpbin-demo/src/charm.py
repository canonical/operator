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

"""Charm the service."""

import logging
from typing import cast

import ops

# Log messages can be retrieved using juju debug-log
logger = logging.getLogger(__name__)

VALID_LOG_LEVELS = ['info', 'debug', 'warning', 'error', 'critical']


class HttpbinDemoCharm(ops.CharmBase):
    """Charm the service."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on['httpbin'].pebble_ready, self._on_httpbin_pebble_ready)
        framework.observe(self.on.config_changed, self._on_config_changed)
        self.container = self.unit.get_container('httpbin')

    def _on_httpbin_pebble_ready(self, event: ops.PebbleReadyEvent):
        """Define and start a workload using the Pebble API."""
        # Add initial Pebble config layer using the Pebble API
        self.container.add_layer('httpbin', self._pebble_layer, combine=True)
        # Make Pebble reevaluate its plan, ensuring any services are started if enabled.
        self.container.replan()
        self.unit.status = ops.ActiveStatus()

    def _on_config_changed(self, event: ops.ConfigChangedEvent):
        """Handle changed configuration."""
        # Fetch the new config value
        log_level = cast('str', self.model.config['log-level']).lower()

        # Do some validation of the configuration option
        if log_level in VALID_LOG_LEVELS:
            # The config is good, so update the configuration of the workload
            # Push an updated layer with the new config
            try:
                self.container.add_layer('httpbin', self._pebble_layer, combine=True)
                self.container.replan()
            except ops.pebble.ConnectionError:
                # We were unable to connect to the Pebble API, so we defer this event
                self.unit.status = ops.MaintenanceStatus('waiting for Pebble API')
                event.defer()
                return

            logger.debug("Log level for gunicorn changed to '%s'", log_level)
            self.unit.status = ops.ActiveStatus()
        else:
            # In this case, the config option is bad, so block the charm and notify the operator.
            self.unit.status = ops.BlockedStatus(f"invalid log level: '{log_level}'")

    @property
    def _pebble_layer(self) -> ops.pebble.LayerDict:
        """Return a dictionary representing a Pebble layer."""
        return {
            'summary': 'httpbin layer',
            'description': 'pebble config layer for httpbin',
            'services': {
                'httpbin': {
                    'override': 'replace',
                    'summary': 'httpbin',
                    'command': 'gunicorn -b 0.0.0.0:80 httpbin:app -k gevent',
                    'startup': 'enabled',
                    'environment': {
                        'GUNICORN_CMD_ARGS': f'--log-level {self.model.config["log-level"]}'
                    },
                }
            },
        }


if __name__ == '__main__':  # pragma: nocover
    ops.main(HttpbinDemoCharm)
