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

import logging
import pathlib

import jubilant
import yaml

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(pathlib.Path("charmcraft.yaml").read_text())
APP_NAME = METADATA["name"]


def test_deploy(charm: pathlib.Path, juju: jubilant.Juju):
    """Build the charm-under-test and deploy it together with related charms.

    Assert on the unit status before any relations/configurations take place.
    """
    resources = {"httpbin-image": METADATA["resources"]["httpbin-image"]["upstream-source"]}

    # Deploy the charm and wait for active/idle status
    juju.deploy(charm.resolve(), app=APP_NAME, resources=resources)
    juju.wait(jubilant.all_active)


def test_block_on_invalid_config(charm: pathlib.Path, juju: jubilant.Juju):
    """Check that the charm goes into blocked status if log-level is invalid."""
    # The value of log-level should be one of info, debug, and so on.
    juju.config(APP_NAME, {"log-level": "foo"})
    juju.wait(jubilant.all_blocked)
    juju.config(APP_NAME, reset="log-level")
