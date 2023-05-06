#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
from pathlib import Path

from scenario.scripts.errors import InvalidTargetUnitName


class JujuUnitName(str):
    """This class represents the name of a juju unit that can be snapshotted."""

    def __init__(self, unit_name: str):
        super().__init__()
        app_name, _, unit_id = unit_name.rpartition("/")
        if not app_name or not unit_id:
            raise InvalidTargetUnitName(f"invalid unit name: {unit_name!r}")
        self.unit_name = unit_name
        self.app_name = app_name
        self.unit_id = int(unit_id)
        self.normalized = f"{app_name}-{unit_id}"
        self.remote_charm_root = Path(
            f"/var/lib/juju/agents/unit-{self.normalized}/charm",
        )
