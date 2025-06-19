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
import time

import ops

# Log messages can be retrieved using juju debug-log.
logger = logging.getLogger(__name__)

VALID_LOG_LEVELS = ['info', 'debug', 'warning', 'error', 'critical']


class HttpbinDemoCharm(ops.CharmBase):
    """Charm the service."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on.collect_unit_status, self._on_collect_status)
        framework.observe(self.on['httpbin'].pebble_ready, self._on_httpbin_pebble_ready)
        framework.observe(self.on.config_changed, self._on_config_changed)
        self.log_level = str(self.config['log-level']).lower()  # str() is for the type checker.
        self.container = self.unit.get_container('httpbin')

    def _on_collect_status(self, event: ops.CollectStatusEvent):
        """Report the status of the workload (runs after each event)."""
        if self.log_level.lower() not in VALID_LOG_LEVELS:
            event.add_status(ops.BlockedStatus(f"invalid log level: '{self.log_level}'"))
            return
        try:
            if not self.container.get_service('httpbin').is_running():
                event.add_status(ops.MaintenanceStatus('waiting for workload'))
        except (ops.pebble.ConnectionError, ops.ModelError):
            event.add_status(ops.MaintenanceStatus('waiting for workload container'))
        event.add_status(ops.ActiveStatus())

    def _on_httpbin_pebble_ready(self, event: ops.PebbleReadyEvent):
        """Define and start a workload using the Pebble API."""
        # Add initial Pebble config layer using the Pebble API.
        self.container.add_layer('httpbin', self._pebble_layer, combine=True)
        # Make Pebble reevaluate its plan, ensuring any services are started if enabled.
        self.container.replan()
        # In rare cases, these calls could fail because the workload container became unavailable.
        # If this happens, we'll let the unit go into error status. The hook will be retried, or
        # the Juju user can investigate.

    def _on_config_changed(self, event: ops.ConfigChangedEvent):
        """Handle changed configuration."""
        if self.log_level.lower() not in VALID_LOG_LEVELS:
            return
        # Update the configuration of the workload.
        # We might not be able to access the workload container yet, so we'll try a few times.
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                self.container.add_layer('httpbin', self._pebble_layer, combine=True)
                self.container.replan()
            except (ops.pebble.APIError, ops.pebble.ConnectionError):  # noqa: PERF203 (try-except in loop)
                logger.info('Unable to reconfigure gunicorn (attempt %d)', attempt + 1)
                time.sleep(2**attempt)
            else:
                break
        else:
            logger.warning('Unable to reconfigure gunicorn after %d attempts.', max_attempts)
            # We expect that there'll be a pebble-ready event in the future,
            # which will configure and start the workload.
            return
        logger.debug("Log level for gunicorn changed to '%s'", self.log_level)

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
                    'environment': {'GUNICORN_CMD_ARGS': f'--log-level {self.log_level}'},
                }
            },
        }


if __name__ == '__main__':  # pragma: nocover
    ops.main(HttpbinDemoCharm)
