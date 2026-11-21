#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""A charm that reports what it sees as its unit status."""

import os

import ops


class ReportCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on.install, self._on_install)
        framework.observe(self.on.config_changed, self._on_install)

    def _on_install(self, _event: ops.EventBase):
        try:
            self.model.get_cloud_spec()
        except ops.ModelError as e:
            trusted = 'not trusted' not in str(e)  # Trusted, but no cloud spec.
        else:
            trusted = True
        self.unit.status = ops.ActiveStatus(
            f'{self.unit.name} leader={self.unit.is_leader()} trusted={trusted} '
            f'juju={ops.JujuVersion.from_environ()} '
            f'name={self.config.get("name")} pid={os.getpid()}'
        )
