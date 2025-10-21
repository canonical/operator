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
from collections.abc import Generator
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
        framework.observe(self.on['set-secret-flow'].action, self.set_secret_flow)

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

    def set_secret_flow(self, event: ops.ActionEvent):
        result: Result = {}
        contentiter = iter(contents())
        labeliter = iter(labels())
        descriptioniter = iter(descriptions())
        expireiter = iter(expires())
        rotateiter = iter(rotates())

        try:
            secretid = event.params.get('secretid')
            secretlabel = event.params.get('secretlabel')

            for field in event.params['flow'].split(','):
                assert secretid or secretlabel
                assert not (secretid and secretlabel)
                secret = self.model.get_secret(
                    **({'id': secretid} if secretid else {}),
                    **({'label': secretlabel} if secretlabel else {}),
                )

                match field:
                    case 'content':
                        secret.set_content(next(contentiter))
                    case 'label':
                        new_label = next(labeliter)
                        secret.set_info(label=new_label)
                        if secretlabel:
                            # So that we can find the secret again
                            secretlabel = new_label
                    case 'description':
                        secret.set_info(description=next(descriptioniter))
                    case 'expire':
                        secret.set_info(expire=next(expireiter))
                    case 'rotate':
                        secret.set_info(rotate=next(rotateiter))
                    case _:
                        raise ValueError(f'Unsupported {field=}')

            if not secretid:
                secretid = self.model.get_secret(label=secretlabel).get_info().id
            result['secretid'] = secretid
            result['after'] = self._snapshot(secretid)
        except Exception as e:
            result['exception'] = str(e)

        event.set_results(cast('dict[str, Any]', result))

    def _snapshot(self, secret_id: str) -> SecretSnapshot:
        secret = self.model.get_secret(id=secret_id)
        # The `expires` and `rotates` fields are coerced to strings by hook command invocation.
        info = cast('InfoSnapshot', secret.get_info().__dict__) if self.unit.is_leader() else None
        return {
            'info': info,
            'tracked': secret.get_content(),
            'latest': secret.peek_content(),
        }


def contents() -> Generator[dict[str, str]]:
    """Generate predictable, but different content values every time."""
    for i in range(1, 10):
        yield {'val': f'{i}'}


def labels() -> Generator[str]:
    """Generate predictable, but different content values every time."""
    for i in range(1, 10):
        yield f'label{i}'


def descriptions() -> Generator[str]:
    """Generate predictable, but different content values every time."""
    for i in range(1, 10):
        yield f'description{i}'


def expires() -> Generator[datetime.datetime]:
    """Generate predictable, but different content values every time."""
    for i in range(1, 10):
        yield datetime.datetime(2010 + i, 1, 1, 0, 0, 0)


def rotates() -> Generator[ops.SecretRotate]:
    """Generate predictable, but different `rotate` values every time."""
    yield from ops.SecretRotate.__members__.values()


if __name__ == '__main__':
    ops.main(SecretsCharm)
