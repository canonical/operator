#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm whose install hook prints a line and then never returns."""

import time

import ops


class SlowCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on.install, self._on_install)

    def _on_install(self, _event: ops.EventBase):
        print('about to hang')
        time.sleep(300)
