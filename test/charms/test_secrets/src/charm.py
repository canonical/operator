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

from typing import Any

import ops


class TestSecretsCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on.start, self._on_start)
        framework.observe(self.on['add-secret'].action, self.add_secret)

    def _on_start(self, event: ops.StartEvent):
        self.unit.status = ops.ActiveStatus()

    def add_secret(self, event: ops.ActionEvent):
        rv: dict[str, Any] = {}
        rv['before'] = None
        secret: ops.Secret = self.app.add_secret({'foo': 'bar'})
        assert secret.id
        rv['secretid'] = secret.id
        rv['after'] = self._snapshot(secret.id)
        event.set_results(rv)

    def _snapshot(self, secret_id: str):
        secret = self.model.get_secret(id=secret_id)
        info = secret.get_info().__dict__ if self.unit.is_leader() else None
        return {
            'info': info,
            'tracked': secret.get_content(),
            'latest': secret.peek_content(),
        }


if __name__ == '__main__':
    ops.main(TestSecretsCharm)
