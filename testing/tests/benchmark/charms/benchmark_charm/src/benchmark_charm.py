#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Basic benchmarking charm.

Note that this is named benchmark_charm rather than charm as is typical to
avoid conflicts with ops.charm in the testing runs.
"""

import logging

import ops

logger = logging.getLogger("__name__")


class BenchmarkCharm(ops.CharmBase):
    """Charm the service."""

    _stored = ops.StoredState()

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on.update_status, self._on_update_status)
        framework.observe(self.on.stop, self._on_stop)
        framework.observe(self.on.config_changed, self._on_config_changed)

    def _on_update_status(self, _: ops.UpdateStatusEvent):
        # Say a bunch of things.
        for level in ("debug", "info", "warning", "error"):
            for i in range(50):
                getattr(logger, level)("This is message %s", i)

    def _on_stop(self, _: ops.StopEvent):
        """Do nothing - this exists to benchmark having an observer."""

    def _on_config_changed(self, event: ops.ConfigChangedEvent):
        event.defer()


if __name__ == "__main__":  # pragma: nocover
    ops.main(BenchmarkCharm)
