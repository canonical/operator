# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

from __future__ import annotations

from typing import Any, ClassVar

import pytest
from scenario import Context, State, StoredState
from scenario.errors import InconsistentScenarioError

import ops
from tests.helpers import trigger


class Charm(ops.CharmBase):
    _read: ClassVar[dict[str, Any]] = {}
    _stored = ops.StoredState()
    _stored2 = ops.StoredState()

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self._stored.set_default(foo='bar', baz={12: 142})
        self._stored2.set_default(foo='bar', baz={12: 142})
        for evt in self.on.events().values():
            framework.observe(evt, self._on_event)

    def _on_event(self, _: ops.EventBase):
        Charm._read['foo'] = self._stored.foo
        Charm._read['baz'] = self._stored.baz


def test_stored_state_default():
    out = trigger(State(), 'start', Charm, meta={'name': 'mycharm'})
    assert out.get_stored_state('_stored', owner_path='Charm').content == {
        'foo': 'bar',
        'baz': {12: 142},
    }
    assert out.get_stored_state('_stored2', owner_path='Charm').content == {
        'foo': 'bar',
        'baz': {12: 142},
    }


def test_stored_state_initialized():
    out = trigger(
        State(
            stored_states={
                StoredState(owner_path='Charm', name='_stored', content={'foo': 'FOOX'}),
            }
        ),
        'start',
        Charm,
        meta={'name': 'mycharm'},
    )
    assert out.get_stored_state('_stored', owner_path='Charm').content == {
        'foo': 'FOOX',
        'baz': {12: 142},
    }
    assert out.get_stored_state('_stored2', owner_path='Charm').content == {
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


def test_stored_state_round_trip_has_no_duplicates():
    # The framework's own _stored has no owner, so its handle path has no
    # prefix. Writing it back with a leading '/' used to produce a second
    # entry with owner_path='' on the next run.
    ctx = Context(Charm, meta={'name': 'foo'})
    state_1 = ctx.run(ctx.on.start(), State())
    state_2 = ctx.run(ctx.on.update_status(), state_1)
    expected = {('_stored', None), ('_stored', 'Charm'), ('_stored2', 'Charm')}
    assert {(s.name, s.owner_path) for s in state_1.stored_states} == expected
    assert {(s.name, s.owner_path) for s in state_2.stored_states} == expected


def test_stored_state_without_owner_is_rejected():
    ctx = Context(Charm, meta={'name': 'foo'})
    state_in = State(stored_states={StoredState(content={'foo': 'bar'})})
    with pytest.raises(InconsistentScenarioError, match="owner_path='MyCharm'"):
        ctx.run(ctx.on.start(), state_in)
