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
import time
from collections.abc import Callable

import jubilant


def test_relation_units(build_relation_charm: Callable[[], str], juju: jubilant.Juju):
    """Ensure that the correct set of units are returned from relation.units."""
    # Build and deploy a simple charm, and scale it up to have two units, so
    # the peer relation has multiple units.
    charm_path = build_relation_charm()
    juju.deploy(charm_path)
    charm_name = 'test-relation'
    juju.add_unit(charm_name, num_units=2)

    # Deploy two instances of the dummy 'any-charm', which can provide many
    # types of relation. Scale them up to have multiple units as well.
    db = 'test-db'
    juju.deploy(
        'any-charm',
        db,
        num_units=3,
        channel='latest/beta',
    )
    juju.integrate(f'{charm_name}:db', db)
    ingress = 'test-ingress'
    juju.deploy(
        'any-charm',
        ingress,
        num_units=2,
        channel='latest/beta',
    )
    juju.integrate(f'{charm_name}:ingress', ingress)

    # Let everything settle. This should be reasonably quick, since the charms
    # aren't actually doing anything.
    status = juju.wait(jubilant.all_active)

    # Verify that relation.units returns the expected set of units.
    peer_units = set(status.get_units(charm_name))
    # The unit running the action will not be included in the peer relation list.
    peer_units.remove(f'{charm_name}/0')
    db_units = set(status.get_units(db))
    ingress_units = set(status.get_units(ingress))

    # Relation membership propagates to each unit asynchronously, even after
    # all units report active, so retry until Juju has caught up.
    deadline = time.time() + 300
    while True:
        task = juju.run(f'{charm_name}/0', 'get-units')
        assert task.success, task.message
        # The keys in the action results are the endpoint names, and the
        # values are the unit names received from Juju. An endpoint whose
        # relation has no remote units yet is absent entirely.
        ops_units: dict[str, list[str]] = json.loads(task.results['units'])
        complete = (
            set(ops_units.get('db', [])) == db_units
            and set(ops_units.get('ingress', [])) == ingress_units
            and set(ops_units.get('peer', [])) == peer_units
        )
        if complete or time.time() > deadline:
            break
        time.sleep(10)

    assert set(ops_units.get('db', [])) == db_units
    assert set(ops_units.get('ingress', [])) == ingress_units
    assert set(ops_units.get('peer', [])) == peer_units
