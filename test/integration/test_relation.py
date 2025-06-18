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
#
# Learn more about testing at
# https://ops.readthedocs.io/en/latest/explanation/testing.html

from __future__ import annotations

import json
import textwrap
from typing import Callable

import jubilant


def test_relation_units(build_relation_charm: Callable[[], str], juju: jubilant.Juju):
    """Ensure that the correct set of units are returned from relation.units."""
    charm_path = build_relation_charm()
    juju.deploy(charm_path)
    juju.add_unit('test-relation', num_units=2)

    db = 'test-db'
    db_src_overwrite = {
        'any_charm.py': textwrap.dedent(
            """
        import ops
        from any_charm_base import AnyCharmBase
        class AnyCharm(AnyCharmBase):
            def __init__(self, framework):
                super().__init__(framework)
                self.unit.status = ops.ActiveStatus('ok')
        """
        ),
    }
    juju.deploy(
        'any-charm',
        db,
        config={'src-overwrite': json.dumps(db_src_overwrite)},
        num_units=3,
        channel='latest/beta',
    )
    juju.integrate('test-relation:db', db)
    ingress = 'test-ingress'
    ingress_src_overwrite = {
        'any_charm.py': textwrap.dedent(
            """
        import ops
        from any_charm_base import AnyCharmBase
        class AnyCharm(AnyCharmBase):
            def __init__(self, framework):
                super().__init__(framework)
                self.unit.status = ops.ActiveStatus('ok')
        """
        ),
    }
    juju.deploy(
        'any-charm',
        ingress,
        config={'src-overwrite': json.dumps(ingress_src_overwrite)},
        num_units=2,
        channel='latest/beta',
    )
    juju.integrate('test-relation:ingress', ingress)

    juju.wait(jubilant.all_active)

    task = juju.run('test-relation/0', 'get-units')
    assert task.success, task.message

    assert task.results['units'] == {}
