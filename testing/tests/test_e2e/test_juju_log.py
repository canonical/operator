# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import pytest
from scenario import Context
from scenario.state import JujuLogLine, State

import ops

logger = logging.getLogger('testing logger')


@pytest.fixture(scope='function')
def mycharm():
    class MyCharm(ops.CharmBase):
        META: Mapping[str, Any] = {'name': 'mycharm'}

        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            for evt in self.on.events().values():
                framework.observe(evt, self._on_event)

        def _on_event(self, event: ops.EventBase):
            if isinstance(event, ops.CollectStatusEvent):
                return
            print('foo!')
            logger.warning('bar!')

    return MyCharm


def test_juju_log(mycharm: Any):
    ctx = Context(mycharm, meta=mycharm.META)
    ctx.run(ctx.on.start(), State())
    assert JujuLogLine(level='DEBUG', message='Emitting Juju event start.') in ctx.juju_log
    assert JujuLogLine(level='WARNING', message='bar!') in ctx.juju_log
    # prints are not juju-logged.
