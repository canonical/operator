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
# See https://documentation.ubuntu.com/ops/latest/howto/write-integration-tests-for-a-charm/
#
# pytest-jubilant provides a module-scoped `juju` fixture that creates a temporary Juju model.
# The `charm` fixture is defined in conftest.py.

import logging
import pathlib

import jubilant
import pytest
import yaml

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(pathlib.Path("charmcraft.yaml").read_text())
APP_NAME = METADATA["name"]


@pytest.mark.juju_setup
def test_deploy(charm: pathlib.Path, juju: jubilant.Juju):
    """Deploy the charm under test."""
    resources = {
        "demo-server-image": METADATA["resources"]["demo-server-image"]["upstream-source"]
    }
    juju.deploy(charm, app=APP_NAME, resources=resources)
    juju.wait(jubilant.all_active)


@pytest.mark.juju_setup
def test_invalid_server_port_blocks_unit(juju: jubilant.Juju):
    """Verify that invalid config blocks the charm.

    This integration test goes beyond the tutorial instructions.
    """
    juju.config(APP_NAME, {"server-port": "22"})
    juju.wait(jubilant.all_blocked)

    juju.config(APP_NAME, reset="server-port")
    juju.wait(jubilant.all_active)
