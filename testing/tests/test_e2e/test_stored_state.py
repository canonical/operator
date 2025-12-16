# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar

import pytest
from scenario.state import State, StoredState

import ops
from tests.helpers import trigger


@pytest.fixture(scope='function')
def mycharm() -> type[ops.CharmBase]:
    class MyCharm(ops.CharmBase):
        META: Mapping[str, Any] = {'name': 'mycharm'}

        _read: ClassVar[dict[str, Any]] = {}
        _stored = ops.StoredState()
        _stored2 = ops.StoredState()

        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            self._stored.set_default(foo='bar', baz={12: 142})
            self._stored2.set_default(foo='bar', baz={12: 142})
            for evt in self.on.events().values():
                self.framework.observe(evt, self._on_event)

        def _on_event(self, _: ops.EventBase):
            self._read['foo'] = self._stored.foo
            self._read['baz'] = self._stored.baz

    return MyCharm


def test_stored_state_default(mycharm: type[ops.CharmBase]):
    out = trigger(State(), 'start', mycharm, meta=mycharm.META)  # type: ignore
    assert out.get_stored_state('_stored', owner_path='MyCharm').content == {
        'foo': 'bar',
        'baz': {12: 142},
    }
    assert out.get_stored_state('_stored2', owner_path='MyCharm').content == {
        'foo': 'bar',
        'baz': {12: 142},
    }


def test_stored_state_initialized(mycharm: type[ops.CharmBase]):
    out = trigger(
        State(
            stored_states={
                StoredState(owner_path='MyCharm', name='_stored', content={'foo': 'FOOX'}),
            }
        ),
        'start',
        mycharm,
        meta=mycharm.META,  # type: ignore
    )
    assert out.get_stored_state('_stored', owner_path='MyCharm').content == {
        'foo': 'FOOX',
        'baz': {12: 142},
    }
    assert out.get_stored_state('_stored2', owner_path='MyCharm').content == {
        'foo': 'bar',
        'baz': {12: 142},
    }


def test_positional_arguments():
    with pytest.raises(TypeError):
        StoredState('_stored', '')  # type: ignore


def test_default_arguments():
    s = StoredState()
    assert s.name == '_stored'
    assert s.owner_path is None
    assert s.content == {}
    assert s._data_type_name == 'StoredStateData'
