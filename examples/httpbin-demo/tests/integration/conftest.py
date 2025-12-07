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
import os
import pathlib
import sys
import time

import jubilant
import pytest

logger = logging.getLogger(__name__)


@pytest.fixture(scope="module")
def juju(request: pytest.FixtureRequest):
    """Create a temporary Juju model for running tests."""
    with jubilant.temp_model() as juju:
        yield juju

        if request.session.testsfailed:
            logger.info("Collecting Juju logs...")
            time.sleep(0.5)  # Wait for Juju to process logs.
            log = juju.debug_log(limit=1000)
            print(log, end="", file=sys.stderr)


@pytest.fixture(scope="session")
def charm():
    """Return the path of the charm under test."""
    if "CHARM_PATH" in os.environ:
        charm_path = pathlib.Path(os.environ["CHARM_PATH"])
        if not charm_path.exists():
            raise FileNotFoundError(f"Charm does not exist: {charm_path}")
        return charm_path
    charm_paths = list(pathlib.Path(".").glob("*.charm"))
    if not charm_paths:
        raise FileNotFoundError("No .charm file in current directory")
    if len(charm_paths) > 1:
        path_list = ", ".join(str(path) for path in charm_paths)
        raise ValueError(f"More than one .charm file in current directory: {path_list}")
    return charm_paths[0]
