# Copyright 2025 Canonical Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


from __future__ import annotations

import typing

import pytest

import ops
from ops import testing


def collect_filtered(
    *event_type: type[ops.EventBase], meta: dict[str, typing.Any] | None = None
) -> tuple[ops.EventBase, ...]:
    ctx = testing.Context(ops.CharmBase, meta={'name': 'ben', **(meta or {})})
    with ctx(ctx.on.update_status(), testing.State()) as mgr:
        return tuple(e.event_type for e in mgr.charm.on.events(*event_type).values())  # type: ignore


def test_filtering_null():
    base_events = set(
        subc
        for subc in ops.HookEvent.__subclasses__()
        # exclude non-leaves
        if not len(subc.__subclasses__()) > 1
    ).union(
        # only lifecycle event that is automatically added to charm.on
        {ops.CollectStatusEvent}
    )
    secret_events = set(subc for subc in ops.SecretEvent.__subclasses__())
    assert set(collect_filtered()) == base_events.union(secret_events)


def test_filtering_secret():
    secret_events = set(subc for subc in ops.SecretEvent.__subclasses__())
    assert set(collect_filtered(ops.SecretEvent)) == secret_events


@pytest.mark.parametrize(
    'evt_type', (ops.StartEvent, ops.UpgradeCharmEvent, ops.SecretExpiredEvent)
)
def test_filtering_single(evt_type: type[ops.EventBase]):
    assert set(collect_filtered(evt_type)) == {evt_type}


@pytest.mark.parametrize(
    'filter_arg, event_to_emit, expect_run',
    (
        ((ops.RelationEvent,), testing.CharmEvents.update_status(), False),
        ((ops.UpdateStatusEvent,), testing.CharmEvents.update_status(), True),
        ((ops.UpdateStatusEvent, ops.RelationEvent), testing.CharmEvents.update_status(), True),
        ((ops.HookEvent,), testing.CharmEvents.update_status(), True),
        ((ops.SecretExpiredEvent,), testing.CharmEvents.update_status(), False),
    ),
)
def test_filtered_observer(
    filter_arg: tuple[type[ops.EventBase]], event_to_emit: typing.Any, expect_run: bool
):
    class MyCharm(ops.CharmBase):
        run = False

        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            for e in self.on.events(*filter_arg).values():
                framework.observe(e, self._on_event)

        def _on_event(self, _: ops.EventBase):
            MyCharm.run = True

    ctx = testing.Context(MyCharm, meta={'name': 'ben'})
    ctx.run(event_to_emit, testing.State())
    assert MyCharm.run is expect_run
