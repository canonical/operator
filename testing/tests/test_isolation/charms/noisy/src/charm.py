#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm that writes to file descriptor 1 without going through sys.stdout.

On ``start``, it writes a long run of output with no newline, then ends its
worker, so the test can check how much of that output is kept.
"""

import os
import subprocess
import sys

import ops


class NoisyCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on.install, self._on_install)
        framework.observe(self.on.start, self._on_start)

    def _on_install(self, _event: ops.EventBase):
        # Three ways past sys.stdout: a bare write to the descriptor, a
        # subprocess inheriting it, and a print for good measure.
        os.write(1, b'raw write to fd 1\n')
        subprocess.run([sys.executable, '-c', "print('from a subprocess')"], check=True)
        print('via print')
        self.unit.status = ops.ActiveStatus('survived')

    def _on_start(self, _event: ops.EventBase):
        os.write(1, b'x' * (4 * 1024 * 1024) + b'end of output')
        os._exit(70)
