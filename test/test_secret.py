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

import ops
import ops.testing


class DifferentSecretRefreshesCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on.start, self._on_start)
        framework.observe(self.on.install, self._on_install)

    def _on_start(self, event: ops.StartEvent):
        self.unit.add_secret({'foo': 'bar'}, label='my-secret')

    def _on_install(self, event: ops.InstallEvent):
        secret1 = self.model.get_secret(label='my-secret')
        secret1.set_content({'foo': 'baz'})
        secret1.set_info(description='A bird in Ngārua Caves.')

        secret2 = self.model.get_secret(label='my-secret')

        info1 = secret1.get_info()
        info2 = secret2.get_info()
        assert info1.id == info2.id
        assert info1.label == info2.label
        assert info1.description == info2.description == 'A bird in Ngārua Caves.'

        content1 = secret1.get_content(refresh=True)
        content2 = secret2.get_content()
        assert content1 == content2 == {'foo': 'baz'}


def test_secret_values_are_in_sync():
    ctx = ops.testing.Context(DifferentSecretRefreshesCharm, meta={'name': 'foo'})
    state = ctx.run(ctx.on.start(), ops.testing.State())
    state = ctx.run(ctx.on.install(), state)
