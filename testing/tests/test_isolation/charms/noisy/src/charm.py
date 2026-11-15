#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm that writes to file descriptor 1 without going through sys.stdout."""

import os
import subprocess
import sys

import ops


class NoisyCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on.install, self._on_install)

    def _on_install(self, _event: ops.EventBase):
        # Three ways past sys.stdout: a bare write to the descriptor, a
        # subprocess inheriting it, and a print for good measure.
        os.write(1, b'raw write to fd 1\n')
        subprocess.run([sys.executable, '-c', "print('from a subprocess')"], check=True)
        print('via print')
        self.unit.status = ops.ActiveStatus('survived')
