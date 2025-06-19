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

import collections
import json

import ops


class TestRelationCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on.start, self._on_start)
        framework.observe(self.on['get-units'].action, self._on_get_units)

    def _on_start(self, _: ops.StartEvent):
        self.unit.status = ops.ActiveStatus('ok')

    def _on_get_units(self, event: ops.ActionEvent):
        """Action to get the units of all relations."""
        if not self.model.relations:
            event.fail('No relations found')
            return

        units: dict[str, list[str]] = collections.defaultdict(list)
        for endpoint, relations in self.model.relations.items():
            assert len(relations) == 1
            relation = relations[0]
            for unit in relation.units:
                units[endpoint].append(unit.name)

        if not units:
            event.fail('No units found in relations')
            return

        event.set_results({'units': json.dumps(units)})


if __name__ == '__main__':
    ops.main(TestRelationCharm)
