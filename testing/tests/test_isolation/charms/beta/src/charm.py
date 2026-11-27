#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.
# pyright: reportMissingImports=false, reportUnknownMemberType=false

"""A charm that needs confdep v2: ``NEW_NAME`` is only in that version."""

import confdep

import ops


class BetaCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on.install, self._on_install)

    def _on_install(self, _event: ops.EventBase):
        self.unit.status = ops.ActiveStatus(f'confdep={confdep.VERSION} {confdep.NEW_NAME}')
