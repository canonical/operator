# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Errors for running charms in worker processes.

These move to ``scenario.errors`` when the API that raises them is public.
"""

from __future__ import annotations


class IsolationError(RuntimeError):
    """A charm couldn't be run in its worker process.

    For example, the worker crashed or timed out, or the charm couldn't be
    imported. The message includes the worker's traceback, if it sent one.
    """
