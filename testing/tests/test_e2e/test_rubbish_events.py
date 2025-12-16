# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

from __future__ import annotations

from typing import ClassVar

import pytest
from scenario.state import State, _CharmSpec, _Event

from ops.charm import CharmBase, CharmEvents
from ops.framework import EventBase, EventSource, Framework, Object

from ..helpers import trigger


class QuxEvent(EventBase):
    pass


class SubEvent(EventBase):
    pass


@pytest.fixture(scope='function')
def mycharm():
    class MyCharmEvents(CharmEvents):
        qux = EventSource(QuxEvent)

    class MySubEvents(CharmEvents):
        sub = EventSource(SubEvent)

    class Sub(Object):
        on = MySubEvents()

    class MyCharm(CharmBase):
        on = MyCharmEvents()
        evts: ClassVar[list[EventBase]] = []

        def __init__(self, framework: Framework):
            super().__init__(framework)
            self.sub = Sub(self, 'sub')
            self.framework.observe(self.sub.on.sub, self._on_event)
            self.framework.observe(self.on.qux, self._on_event)

        def _on_event(self, e):
            MyCharm.evts.append(e)

    return MyCharm


@pytest.mark.parametrize('evt_name', ('rubbish', 'foo', 'bar'))
def test_rubbish_event_raises(mycharm: CharmBase, evt_name: str):
    with pytest.raises(AttributeError):
        trigger(State(), evt_name, mycharm, meta={'name': 'foo'})


def test_rubbish_pebble_ready_event_raises(mycharm: CharmBase, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv('SCENARIO_SKIP_CONSISTENCY_CHECKS', '1')
    # else it will whine about the container not being in state and meta;
    # but if we put the container in meta, it will actually register an event!
    with pytest.raises(AttributeError):
        trigger(State(), 'kazoo_pebble_ready', mycharm, meta={'name': 'foo'})


@pytest.mark.parametrize('evt_name', ('qux',))
def test_custom_events_fail(mycharm, evt_name):
    with pytest.raises(AttributeError):
        trigger(State(), evt_name, mycharm, meta={'name': 'foo'})


# cfr: https://github.com/PietroPasotti/ops-scenario/pull/11#discussion_r1101694961
@pytest.mark.parametrize('evt_name', ('sub',))
def test_custom_events_sub_raise(mycharm, evt_name):
    with pytest.raises(AttributeError):
        trigger(State(), evt_name, mycharm, meta={'name': 'foo'})


@pytest.mark.parametrize(
    'evt_name, expected',
    (
        ('qux', False),
        ('sub', False),
        ('start', True),
        ('install', True),
        ('config-changed', True),
        ('foo-relation-changed', True),
        ('bar-relation-changed', True),
    ),
)
def test_is_custom_event(mycharm, evt_name, expected):
    spec = _CharmSpec(charm_type=mycharm, meta={'name': 'mycharm', 'requires': {'foo': {}}})
    assert _Event(evt_name)._is_builtin_event(spec) is expected
