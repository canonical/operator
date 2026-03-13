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
# The integration tests use the Jubilant library. See https://documentation.ubuntu.com/jubilant/
# To learn more about testing, see https://documentation.ubuntu.com/ops/latest/explanation/testing/

import logging
import pathlib

import jubilant
import yaml

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(pathlib.Path("./charmcraft.yaml").read_text())
APP_NAME = METADATA["name"]


def test_deploy(charm: pathlib.Path, juju: jubilant.Juju):
    """Deploy the charm under test.

    Assert on the unit status before any relations/configurations take place.
    """
    resources = {
        "demo-server-image": METADATA["resources"]["demo-server-image"]["upstream-source"]
    }

    # Deploy the charm and wait for it to report blocked, as it needs Postgres.
    juju.deploy(f"./{charm}", app=APP_NAME, resources=resources)
    juju.wait(jubilant.all_blocked)


def test_database_integration(juju: jubilant.Juju):
    """Verify that the charm integrates with the database.

    Assert that the charm is active if the integration is established.
    """
    juju.deploy("postgresql-k8s", channel="14/stable", trust=True)
    juju.integrate(APP_NAME, "postgresql-k8s")
    juju.wait(jubilant.all_active)


def test_cos_lite(cos_juju: jubilant.Juju):
    """Deploy COS Lite and verify a Loki offer is created.

    Waits for all COS Lite applications to settle down, then offers the
    Loki logging endpoint for cross-model integration.
    """
    cos_juju.deploy("cos-lite", trust=True)
    cos_juju.wait(jubilant.all_active)

    cos_juju.offer("loki", endpoint="logging")

    # Verify the Loki offer was created; raises CLIError if not found.
    cos_juju.cli("find-offers", "--interface", "loki_push_api", include_model=False)


def test_loki_integration(juju: jubilant.Juju, cos_juju: jubilant.Juju):
    """Verify that the charm integrates with Loki.

    Assert that the charm remains active after the Loki integration is established.
    """
    juju.integrate(APP_NAME, f"admin/{cos_juju.model}.loki")
    juju.wait(jubilant.all_active)
