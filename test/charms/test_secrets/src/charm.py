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

import json
from typing import Any

import ops


class TestSecretsCharm(ops.CharmBase):
    _stored = ops.StoredState()

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self._stored.set_default(secret_id=None)
        framework.observe(self.on.start, self._on_start)
        framework.observe(self.on['exec'].action, self._on_exec)

    def _on_start(self, event: ops.StartEvent):
        self.unit.status = ops.ActiveStatus()

    def _on_exec(self, event: ops.ActionEvent):
        """Action to execute arbitrary Python code in specific context."""
        assert event.params['code']
        rv: dict[str, Any] = {}

        rv['_before'] = self._snapshot()

        try:
            exec(event.params['code'], globals(), locals())  # noqa
            rv.setdefault('_result', None)
        except Exception as e:
            rv['_exception'] = str(e)

        rv['_after'] = self._snapshot()

        event.set_results({'rv': json.dumps(rv)})

    def _snapshot(self):
        secret_id = self._stored.secret_id
        if not secret_id:
            return None
        secret = self.model.get_secret(id=secret_id)
        return {
            'info': _to_dict(secret_info=secret.get_info()),
            'tracked': secret.get_content(),
            'latest': secret.peek_content(),
        }


def _to_dict(secret_info: ops.SecretInfo):
    return {
        'id': secret_info.id,
        'label': secret_info.label,
        'revision': secret_info.revision,
        'expires': secret_info.expires,
        'rotation': secret_info.rotation,
        'rotates': secret_info.rotates,
        'description': secret_info.description,
    }


if __name__ == '__main__':
    ops.main(TestSecretsCharm)
