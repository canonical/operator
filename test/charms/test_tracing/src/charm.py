#!/usr/bin/env python3
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

import opentelemetry.trace

import ops

tracer = opentelemetry.trace.get_tracer('TestTracing')


class TestTracingCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self.tracing = ops.tracing.Tracing(
            self, 'charm-tracing', ca_relation_name='receive-ca-cert'
        )
        self.framework.observe(self.on.start, self._on_start)
        self.framework.observe(self.on.one_action, self._on_action)
        self.framework.observe(self.on.two_action, self._on_action)
        self.framework.observe(self.on.one_action, self._on_action)

    @tracer.start_as_current_span('start')
    def _on_start(self, event: ops.StartEvent):
        if self.unit.is_leader():
            self.app.status = ops.ActiveStatus('ok')
        self.unit.status = ops.ActiveStatus('ok')

    @tracer.start_as_current_span('custom trace on any action')
    def _on_action(self, event: ops.ActionEvent):
        opentelemetry.trace.get_current_span().set_attribute('arg', event.params.get('arg') or '')
        event.set_results({'ok': True})


if __name__ == '__main__':
    ops.main(TestTracingCharm)
