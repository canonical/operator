#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""A charm that ends its worker on ``start``, exits on ``stop``, and behaves on ``install``."""

import os
import sys

import ops


class HardExitCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on.install, self._on_install)
        framework.observe(self.on.start, self._on_start)
        framework.observe(self.on.stop, self._on_stop)

    def _on_install(self, _event: ops.EventBase):
        self.unit.status = ops.ActiveStatus('installed')

    def _on_start(self, _event: ops.EventBase):
        os._exit(70)  # Not an exception, so the worker can't catch it.

    def _on_stop(self, _event: ops.EventBase):
        sys.exit(3)
