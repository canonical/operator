# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

from __future__ import annotations

import logging
import sys
import unittest.mock

import pytest
from scenario import Context
from scenario.state import State

import ops

logger = logging.getLogger('testing logger')


META = {'name': 'mycharm'}


class MyCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        breakpoint()


def test_breakpoint_calls_sys_breakpointhook(monkeypatch: pytest.MonkeyPatch):
    """breakpoint() in charm code calls through to sys.breakpointhook during tests."""
    mock_hook = unittest.mock.MagicMock()
    monkeypatch.setattr(sys, 'breakpointhook', mock_hook)
    ctx = Context(MyCharm, meta=META)
    ctx.run(ctx.on.install(), State())
    mock_hook.assert_called_once()


def test_breakpoint_suppressed_by_pythonbreakpoint_env_var(monkeypatch: pytest.MonkeyPatch):
    """When ``PYTHONBREAKPOINT=0``, ``breakpoint()`` should be a no-op.

    Note that since we use pytest-xdist, we would get a BdbQuit exception if sys.breakpointhook
    was called. If we run with ``-n0 --dist=no``, we would land in an interactive session.
    But since we set ``PYTHONBREAKPOINT=0``, neither happens and the test completes successfully.
    """
    monkeypatch.setenv('PYTHONBREAKPOINT', '0')
    ctx = Context(MyCharm, meta=META)
    ctx.run(ctx.on.update_status(), State())
