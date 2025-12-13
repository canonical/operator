# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

from __future__ import annotations

from scenario import Context, State

import ops

META = {
    'name': 'traced_charm',
    'requires': {'charm-tracing': {'interface': 'tracing', 'limit': 1}},
}


class TracedCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self.tracing = ops.tracing.Tracing(self, 'charm-tracing')
        for evt in self.on.events().values():
            self.framework.observe(evt, self._on_event)

    def _on_event(self, event: ops.EventBase):
        pass


def test_trace_data():
    ctx = Context(TracedCharm, meta=META)
    ctx.run(ctx.on.start(), State(leader=True))

    assert {s.name for s in ctx.trace_data} == {
        # The entry point and root span.
        'ops.main',
        # The first-party charm library.
        'ops.tracing.Tracing',
        # Start event emitted on this charm.
        'start: TracedCharm',
        # Start event emitted on the first party charm lib.
        'start: Tracing',
        # Emitted on the leader.
        'collect_app_status: TracedCharm',
        # Emitted on all units.
        'collect_unit_status: TracedCharm',
    }

    main_span = next(s for s in ctx.trace_data if s.name == 'ops.main')
    assert not main_span.parent
    assert {e.name for e in main_span.events} == {
        'StartEvent',
        'CollectStatusEvent',
        'PreCommitEvent',
        'CommitEvent',
    }
