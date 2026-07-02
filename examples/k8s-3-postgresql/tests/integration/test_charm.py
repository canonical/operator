# Copyright 2026 Canonical Ltd.
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
# The integration tests use the Jubilant library and the pytest-jubilant plugin.
# See https://canonical.com/juju/docs/ops/latest/howto/write-integration-tests-for-a-charm/
#
# pytest-jubilant provides a module-scoped `juju` fixture that creates a temporary Juju model.
# The `charm` fixture is defined in conftest.py.

import logging
import pathlib

import jubilant
import pytest
import yaml

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(pathlib.Path("./charmcraft.yaml").read_text())
APP_NAME = METADATA["name"]


@pytest.mark.juju_setup
def test_deploy(charm: pathlib.Path, juju: jubilant.Juju):
    """Deploy the charm under test.

    Assert on the unit status before any relations/configurations take place.
    """
    resources = {
        "demo-server-image": METADATA["resources"]["demo-server-image"]["upstream-source"]
    }

    # Deploy the charm and wait for it to report blocked, as it needs Postgres.
    juju.deploy(charm, app=APP_NAME, resources=resources)
    juju.wait(jubilant.all_blocked)


@pytest.mark.juju_setup
def test_database_integration(charm: pathlib.Path, juju: jubilant.Juju):
    """Verify that the charm integrates with the database.

    Assert that the charm is active if the integration is established.
    """
    juju.deploy("postgresql-k8s", channel="14/stable", trust=True)
    juju.integrate(APP_NAME, "postgresql-k8s")
    juju.wait(jubilant.all_active, timeout=10 * 60)

    version = juju.status().apps[APP_NAME].version
    # Hardcoded version for simplicity. Ideally we'd get the version directly from the workload.
    assert version == "1.0.4"
