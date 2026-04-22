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

import json
import logging
import pathlib
import time

import jubilant
import pytest
import pytest_jubilant
import requests
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
    juju.deploy(charm.resolve(), app=APP_NAME, resources=resources)
    juju.wait(jubilant.all_blocked)


def test_database_integration(juju: jubilant.Juju):
    """Verify that the charm integrates with the database.

    Assert that the charm is active if the integration is established.
    """
    juju.deploy("postgresql-k8s", channel="14/stable", trust=True)
    juju.integrate(APP_NAME, "postgresql-k8s")
    juju.wait(jubilant.all_active)


@pytest.fixture(scope="module")
def cos(juju_factory: pytest_jubilant.JujuFactory):
    yield juju_factory.get_juju(suffix="cos")


def test_deploy_cos(cos: jubilant.Juju):
    """Deploy COS Lite in a separate model."""
    cos.deploy("cos-lite", trust=True)
    cos.wait(jubilant.all_active, timeout=10 * 60)  # Allow time for the bundle to deploy.


def test_integrate_loki(juju: jubilant.Juju, cos: jubilant.Juju):
    """Integrate our app with Loki from COS Lite."""
    cos.offer("loki", endpoint="logging")
    juju.integrate(APP_NAME, f"{cos.model}.loki")
    juju.wait(jubilant.all_active)
    cos.wait(jubilant.all_active)


def test_loki_data(cos: jubilant.Juju):
    """Use Loki's HTTP API to verify that Loki has a label for our app.

    COS Lite exposes Loki's API through the Traefik load balancer. Traefik comes with an action
    that tells us the base URL of Loki's API.
    """
    task = cos.run("traefik/0", "show-proxied-endpoints")
    results = json.loads(task.results["proxied-endpoints"])
    loki_url = results["loki/0"]["url"]
    loki_api_url = f"{loki_url}/loki/api/v1/label/juju_application/values"
    juju_applications = _get_loki_logs(loki_api_url)
    assert juju_applications is not None, "No logs available from Loki"
    assert APP_NAME in juju_applications


def _get_loki_logs(loki_api_url: str) -> list[str] | None:
    """Wait for logs to be available from Loki and return them."""
    for attempt in range(60):
        if attempt:  # If not the first attempt, wait before retrying.
            time.sleep(1)
        response = requests.get(loki_api_url)
        if response.status_code == 200:
            response_decoded = response.json()
            if "data" in response_decoded:
                return response_decoded["data"]
    return None
