# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

from __future__ import annotations

import sys
from collections.abc import Callable

from scenario import Context, Relation, State

import ops

META = {'name': 'local', 'requires': {'db': {'interface': 'db'}}}
ACTIONS: dict[str, dict[str, object]] = {'back-up': {}}


class Charm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self.error: ops.ModelError | None = None
        self.call: Callable[[ops.CharmBase], object] = lambda charm: None
        framework.observe(self.on.update_status, self._on_event)
        framework.observe(self.on.back_up_action, self._on_event)

    def _on_event(self, event: ops.EventBase):
        try:
            self.call(self)
        except ops.ModelError as e:
            self.error = e


def _run(event_name: str, call: Callable[[ops.CharmBase], object], state: State) -> ops.ModelError:
    ctx = Context(Charm, meta=META, actions=ACTIONS, juju_version='3.6.0')
    event = ctx.on.action('back-up') if event_name == 'back_up_action' else ctx.on.update_status()
    with ctx(event, state) as mgr:
        mgr.charm.call = call
        mgr.run()
        assert mgr.charm.error is not None
        return mgr.charm.error


def _notes(error: Exception) -> list[str]:
    return list(getattr(error, '__notes__', []))


def test_secret_not_found():
    error = _run('update_status', lambda charm: charm.model.get_secret(label='missing'), State())
    assert isinstance(error, ops.SecretNotFoundError)
    assert error.hook_command == 'secret-get'
    assert error.hook_command_args == {'label': 'missing', 'refresh': False, 'peek': False}
    assert error.current_hook == 'update-status'
    assert error.current_event == 'update_status'
    assert error.current_event_deferred is False
    if sys.version_info >= (3, 11):
        assert _notes(error) == [
            "Hook command 'secret-get' (label='missing', refresh=False, peek=False) "
            "failed during the 'update-status' hook."
        ]


def test_renamed_args():
    relation = Relation('db')
    error = _run(
        'update_status',
        lambda charm: charm.model.get_relation('db', relation.id).remote_model,  # type: ignore
        State(relations={relation}),
    )
    # Context's juju_version is too old for relation-model-get.
    assert error.hook_command == 'relation-model-get'
    assert error.hook_command_args == {'relation_id': relation.id, 'endpoint': 'db'}


def test_action():
    error = _run('back_up_action', lambda charm: charm.model.get_cloud_spec(), State())
    assert error.hook_command == 'credential-get'
    assert error.hook_command_args == {}
    assert error.current_hook is None
    assert error.current_event == 'back_up_action'
    if sys.version_info >= (3, 11):
        assert _notes(error) == [
            "Hook command 'credential-get' failed during the 'back-up' action."
        ]
