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
# The integration tests use the Jubilant library. See https://documentation.ubuntu.com/jubilant/
# To learn more about testing, see https://documentation.ubuntu.com/ops/latest/explanation/testing/

import logging
import pathlib

import jubilant

logger = logging.getLogger(__name__)


def test_deploy(charm: pathlib.Path, juju: jubilant.Juju):
    """Deploy the charm under test."""
    juju.deploy(charm.resolve(), app="tinyproxy")
    juju.wait(jubilant.all_active, timeout=600)


def test_workload_version_is_set(charm: pathlib.Path, juju: jubilant.Juju):
    """Check that the correct version of the workload is running."""
    version = juju.status().apps["tinyproxy"].version
    assert version == "1.11.0"  # The version installed by tinyproxy.install.


def test_block_on_invalid_config(charm: pathlib.Path, juju: jubilant.Juju):
    """Check that the charm goes into blocked status if slug is invalid."""
    juju.config("tinyproxy", {"slug": "foo/bar"})
    juju.wait(jubilant.all_blocked)
    juju.config("tinyproxy", reset="slug")
