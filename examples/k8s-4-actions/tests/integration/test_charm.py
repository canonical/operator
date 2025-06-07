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

import asyncio
import logging
from pathlib import Path

import pytest
import yaml
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path('./charmcraft.yaml').read_text())
APP_NAME = METADATA['name']


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest):
    """Build the charm-under-test and deploy it together with related charms.

    Assert on the unit status before integration or configuration.
    """
    # Build and deploy charm from local source folder
    charm = await ops_test.build_charm('.')
    resources = {
        'demo-server-image': METADATA['resources']['demo-server-image']['upstream-source']
    }

    # Deploy the charm and wait for blocked/idle status.
    # The app will not be in active status as this requires a database relation.
    await asyncio.gather(
        ops_test.model.deploy(charm, resources=resources, application_name=APP_NAME),
        ops_test.model.wait_for_idle(
            apps=[APP_NAME], status='blocked', raise_on_blocked=False, timeout=300
        ),
    )


@pytest.mark.abort_on_fail
async def test_database_integration(ops_test: OpsTest):
    """Verify that the charm integrates with the database.

    Assert that the charm is active if the integration is established.
    """
    await ops_test.model.deploy(
        application_name='postgresql-k8s',
        entity_url='postgresql-k8s',
        channel='14/stable',
    )
    await ops_test.model.integrate(f'{APP_NAME}', 'postgresql-k8s')
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME], status='active', raise_on_blocked=False, timeout=300
    )
