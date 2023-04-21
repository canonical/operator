#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
class SnapshotError(RuntimeError):
    """Base class for errors raised by snapshot."""


class InvalidTargetUnitName(SnapshotError):
    """Raised if the unit name passed to snapshot is invalid."""


class InvalidTargetModelName(SnapshotError):
    """Raised if the model name passed to snapshot is invalid."""


class StateApplyError(SnapshotError):
    """Raised when the state-apply juju command fails."""
