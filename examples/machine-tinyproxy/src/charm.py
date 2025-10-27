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

"""Charm the application."""

import logging
import time

import ops
import pydantic

# A standalone module for workload-specific logic (no charming concerns):
import tinyproxy

logger = logging.getLogger(__name__)

PORT = 8000


class TinyproxyConfig(pydantic.BaseModel):
    """Schema for the charm's config options."""

    slug: str = pydantic.Field(
        "example",
        pattern=r"^[a-z0-9-]+$",
        description="Configures the path of the reverse proxy. Must match the regex [a-z0-9-]+",
    )


class TinyproxyCharm(ops.CharmBase):
    """Charm the application."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on.collect_unit_status, self._on_collect_status)
        framework.observe(self.on.install, self._on_install)
        framework.observe(self.on.start, self._on_start)
        framework.observe(self.on.config_changed, self._on_config_changed)
        framework.observe(self.on.stop, self._on_stop)
        framework.observe(self.on.remove, self._on_remove)

    def _on_collect_status(self, event: ops.CollectStatusEvent) -> None:
        """Report the status of tinyproxy (runs after each event)."""
        try:
            self.load_config(TinyproxyConfig)
        except pydantic.ValidationError as e:
            (slug_error,) = e.errors()  # 'slug' is the first and only option validated.
            slug_value = slug_error["input"]
            message = f"Invalid slug: '{slug_value}'. Slug must match the regex [a-z0-9-]+"
            event.add_status(ops.BlockedStatus(message))
        if not tinyproxy.is_installed():
            event.add_status(ops.MaintenanceStatus("Waiting for tinyproxy to be installed"))
        if not tinyproxy.is_running():
            event.add_status(ops.MaintenanceStatus("Waiting for tinyproxy to start"))
        event.add_status(ops.ActiveStatus())

    def _on_install(self, event: ops.InstallEvent) -> None:
        """Install tinyproxy on the machine."""
        if not tinyproxy.is_installed():
            tinyproxy.install()
            version = tinyproxy.get_version()
            self.unit.set_workload_version(version)

    def _on_start(self, event: ops.StartEvent) -> None:
        """Handle start event."""
        self.configure_and_run()

    def _on_config_changed(self, event: ops.ConfigChangedEvent) -> None:
        """Handle config-changed event."""
        self.configure_and_run()

    def _on_stop(self, event: ops.StopEvent) -> None:
        """Handle stop event."""
        tinyproxy.stop()
        self.wait_for_not_running()

    def _on_remove(self, event: ops.RemoveEvent) -> None:
        """Handle remove event."""
        tinyproxy.uninstall()

    def configure_and_run(self) -> None:
        """Ensure that tinyproxy is running with the correct config."""
        try:
            config = self.load_config(TinyproxyConfig)
        except pydantic.ValidationError:
            # The collect-status handler will run next and will set status for the user to see.
            return
        if not tinyproxy.is_installed():
            return
        changed = tinyproxy.ensure_config(PORT, config.slug)
        if not tinyproxy.is_running():
            tinyproxy.start()
            self.wait_for_running()
        elif changed:
            logger.info("Config changed while tinyproxy is running. Updating tinyproxy config")
            tinyproxy.reload_config()

    def wait_for_running(self) -> None:
        """Wait for tinyproxy to be running."""
        for _ in range(3):
            if tinyproxy.is_running():
                return
            time.sleep(1)
        raise RuntimeError("tinyproxy was not running within the expected time")
        # Raising a runtime error will put the charm into error status.
        # The Juju logs will show the error message, to help you debug the error.

    def wait_for_not_running(self) -> None:
        """Wait for tinyproxy to not be running."""
        for _ in range(3):
            if not tinyproxy.is_running():
                return
            time.sleep(1)
        raise RuntimeError("tinyproxy was still running after the expected time")


if __name__ == "__main__":  # pragma: nocover
    ops.main(TinyproxyCharm)
