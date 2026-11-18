# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Errors for driving several charms together.

These move to ``scenario.errors`` when the API that raises them is public.
"""

from __future__ import annotations


class JujuError(RuntimeError):
    """A ``Juju`` operation was rejected, or ``settle()`` could not converge."""
