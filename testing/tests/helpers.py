# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from scenario.context import _DEFAULT_JUJU_VERSION, Context
from scenario.state import _Event

if TYPE_CHECKING:  # pragma: no cover
    from scenario.state import CharmType, State

logger = logging.getLogger()


def trigger(
    state: State,
    event: str | _Event,
    charm_type: type[CharmType],
    pre_event: Callable[[CharmType], None] | None = None,
    post_event: Callable[[CharmType], None] | None = None,
    meta: dict[str, Any] | None = None,
    actions: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
    charm_root: str | Path | None = None,
    juju_version: str = _DEFAULT_JUJU_VERSION,
) -> State:
    ctx = Context(
        charm_type=charm_type,
        meta=meta,
        actions=actions,
        config=config,
        charm_root=charm_root,
        juju_version=juju_version,
    )
    if isinstance(event, str):
        if event.startswith('relation_'):
            assert len(tuple(state.relations)) == 1, 'shortcut only works with one relation'
            event = getattr(ctx.on, event)(next(iter(state.relations)))
        elif event.startswith('pebble_'):
            assert len(tuple(state.containers)) == 1, 'shortcut only works with one container'
            event = getattr(ctx.on, event)(next(iter(state.containers)))
        else:
            event = getattr(ctx.on, event)()
    assert isinstance(event, _Event)
    with ctx(event, state=state) as mgr:
        if pre_event:
            pre_event(mgr.charm)
        state_out = mgr.run()
        if post_event:
            post_event(mgr.charm)
    return state_out


def _escape(key: str) -> str:
    # RFC 6902 JSON Pointer escaping: ~ -> ~0, / -> ~1 (order matters).
    return key.replace('~', '~0').replace('/', '~1')


def _dict_diff(a: Any, b: Any, path: str, out: list[dict[str, Any]]) -> None:
    # Emit RFC 6902-shaped patch ops describing how to transform `a` into `b`.
    # Recurses into dicts; treats list / scalar differences as whole-value replaces.
    if isinstance(a, dict) and isinstance(b, dict):
        ad = cast('dict[str, Any]', a)
        bd = cast('dict[str, Any]', b)
        for key in ad.keys() - bd.keys():
            out.append({'op': 'remove', 'path': f'{path}/{_escape(key)}'})
        for key in bd.keys() - ad.keys():
            out.append({'op': 'add', 'path': f'{path}/{_escape(key)}', 'value': bd[key]})
        for key in ad.keys() & bd.keys():
            _dict_diff(ad[key], bd[key], f'{path}/{_escape(key)}', out)
        return
    if a != b:
        out.append({'op': 'replace', 'path': path, 'value': b})


def state_delta(self: State, other: State) -> list[dict[str, Any]]:
    dict_other = dataclasses.asdict(other)
    dict_self = dataclasses.asdict(self)
    for attr in (
        'relations',
        'containers',
        'storages',
        'opened_ports',
        'secrets',
        'resources',
        'stored_states',
        'networks',
    ):
        dict_other[attr] = [dataclasses.asdict(o) for o in dict_other[attr]]
        dict_self[attr] = [dataclasses.asdict(o) for o in dict_self[attr]]
    patch: list[dict[str, Any]] = []
    _dict_diff(dict_other, dict_self, '', patch)
    return sorted(patch, key=lambda obj: obj['path'] + obj['op'])
