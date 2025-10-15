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

import datetime
from typing import Any, TypedDict, cast

import ops


class InfoSnapshot(TypedDict):
    id: str
    label: str | None
    revision: int
    expires: str | None
    rotation: str | None
    rotates: str | None
    description: str | None


class SecretSnapshot(TypedDict):
    info: InfoSnapshot | None
    tracked: dict[str, Any]
    latest: dict[str, Any]


class Result(TypedDict, total=False):
    before: SecretSnapshot | None
    after: SecretSnapshot | None
    secretid: str | None
    exception: str | None


class SecretsCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on.start, self._on_start)
        framework.observe(self.on['add-secret'].action, self.add_secret)
        framework.observe(self.on['add-with-meta'].action, self.add_with_meta)

    def _on_start(self, event: ops.StartEvent):
        self.unit.status = ops.ActiveStatus()

    def add_secret(self, event: ops.ActionEvent):
        secret = self.app.add_secret({'foo': 'bar'})
        assert secret.id
        result: Result = {
            'secretid': secret.id,
            'after': self._snapshot(secret.id),
        }
        event.set_results(cast('dict[str, Any]', result))

    def add_with_meta(self, event: ops.ActionEvent):
        field_keys = event.params['fields'].split(',')
        full_meta = {
            'label': 'label1',
            'description': 'description1',
            'expire': datetime.datetime(2020, 1, 1, 0, 0, 0),
            'rotate': ops.SecretRotate.DAILY,
        }
        meta = {k: v for k, v in full_meta.items() if k in field_keys}
        secret = self.app.add_secret({'foo': 'bar'}, **meta)  # type: ignore
        assert secret.id
        result: Result = {
            'secretid': secret.id,
            'after': self._snapshot(secret.id),
        }
        event.set_results(cast('dict[str, Any]', result))

    def _snapshot(self, secret_id: str) -> SecretSnapshot:
        secret = self.model.get_secret(id=secret_id)
        # `expires` and `rotates` may need coercion to str
        info = cast('InfoSnapshot', secret.get_info().__dict__) if self.unit.is_leader() else None
        return {
            'info': info,
            'tracked': secret.get_content(),
            'latest': secret.peek_content(),
        }


if __name__ == '__main__':
    ops.main(SecretsCharm)
