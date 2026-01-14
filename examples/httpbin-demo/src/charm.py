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

import dataclasses
import logging
import time

import ops

# Log messages can be retrieved using juju debug-log.
logger = logging.getLogger(__name__)

CONTAINER_NAME = "httpbin"  # Name of workload container.
SERVICE_NAME = "httpbin"  # Name of Pebble service that runs in the workload container.


@dataclasses.dataclass(frozen=True)
class HttpbinConfig:
    """Schema for the configuration of the httpbin charm."""

    log_level: str = "info"
    """Configures the log level of gunicorn.

    Acceptable values are: "info", "debug", "warning", "error" and "critical".
    """

    def __post_init__(self):
        log_level = self.log_level.lower()
        valid_log_levels = {"info", "debug", "warning", "error", "critical"}
        if log_level not in valid_log_levels:
            raise ValueError(
                f"Invalid log level: '{self.log_level}'. "
                f"Valid values are: {', '.join(valid_log_levels)}."
            )
        object.__setattr__(self, "log_level", log_level)


class HttpbinDemoCharm(ops.CharmBase):
    """Charm the service."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on.collect_unit_status, self._on_collect_status)
        framework.observe(self.on[CONTAINER_NAME].pebble_ready, self._on_httpbin_pebble_ready)
        framework.observe(self.on.config_changed, self._on_config_changed)
        self.container = self.unit.get_container(CONTAINER_NAME)

    def _on_collect_status(self, event: ops.CollectStatusEvent):
        """Report the status of the workload (runs after each event)."""
        try:
            self.load_config(HttpbinConfig)
        except ValueError as e:
            event.add_status(ops.BlockedStatus(str(e)))
        try:
            service = self.container.get_service(SERVICE_NAME)
        except ops.ModelError:
            # We can connect to Pebble in the container, but the service doesn't exist. This is
            # most likely because we haven't added a layer yet.
            event.add_status(ops.MaintenanceStatus("waiting for workload container"))
        except ops.pebble.ConnectionError:
            # We can't connect to Pebble in the container. This is most likely because the
            # container hasn't started yet.
            event.add_status(ops.MaintenanceStatus("waiting for workload container"))
        except ops.pebble.APIError:
            # It's technically possible (but unlikely) for Pebble to have an internal error.
            logger.error("Unable to fetch service info from Pebble")
            raise
        else:
            if not service.is_running():
                # We can connect to Pebble in the container, but the service hasn't started yet.
                event.add_status(ops.MaintenanceStatus("waiting for workload"))
        event.add_status(ops.ActiveStatus())

    def _on_httpbin_pebble_ready(self, event: ops.PebbleReadyEvent):
        """Define and start a workload using the Pebble API."""
        try:
            config = self.load_config(HttpbinConfig)
        except ValueError:
            return
        # Add initial Pebble config layer using the Pebble API.
        self.container.add_layer(
            "httpbin", self._make_pebble_layer(config.log_level), combine=True
        )
        # Make Pebble reevaluate its plan, ensuring any services are started if enabled.
        self.container.replan()
        # In rare cases, these calls could fail because the workload container became unavailable.
        # If this happens, we'll let the unit go into error status. The hook will be retried, or
        # the Juju user can investigate.

    def _on_config_changed(self, event: ops.ConfigChangedEvent):
        """Handle changed configuration."""
        try:
            config = self.load_config(HttpbinConfig)
        except ValueError:
            return
        # Update the configuration of the workload.
        # We might not be able to access the workload container yet, so we'll try a few times.
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                self.container.add_layer(
                    "httpbin", self._make_pebble_layer(config.log_level), combine=True
                )
                self.container.replan()
            except (ops.pebble.APIError, ops.pebble.ConnectionError):  # noqa: PERF203 (try-except in loop)
                logger.info("Unable to reconfigure gunicorn (attempt %d)", attempt + 1)
                time.sleep(2**attempt)
            else:
                break
        else:
            logger.warning("Unable to reconfigure gunicorn after %d attempts.", max_attempts)
            # We expect that there'll be a pebble-ready event in the future,
            # which will configure and start the workload.
            return
        logger.debug("Log level for gunicorn changed to '%s'", config.log_level)

    def _make_pebble_layer(self, log_level: str) -> ops.pebble.Layer:
        """Return a Pebble layer that starts gunicorn with the specified log level."""
        environment = {"GUNICORN_CMD_ARGS": f"--log-level {log_level}"}
        layer: ops.pebble.LayerDict = {  # Typing as a LayerDict hints the layer's keys.
            "services": {
                SERVICE_NAME: {
                    "override": "replace",
                    "summary": "httpbin",
                    "command": "gunicorn -b 0.0.0.0:80 httpbin:app -k gevent",
                    "startup": "enabled",
                    "environment": environment,
                },
            },
        }
        return ops.pebble.Layer(layer)


if __name__ == "__main__":  # pragma: nocover
    ops.main(HttpbinDemoCharm)
