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

import os
import pathlib
import subprocess

import jubilant
import pytest


@pytest.fixture(scope="module")
def juju(request: pytest.FixtureRequest):
    with jubilant.temp_model() as juju:
        yield juju

        if request.session.testsfailed:
            log = juju.debug_log(limit=1000)
            print(log, end="")


@pytest.fixture(scope="session")
def charm():
    charm_path = os.getenv("CHARM_PATH")
    if charm_path is not None:
        if not pathlib.Path(charm_path).exists():
            raise FileNotFoundError(f"Charm does not exist: {charm_path}")
        return pathlib.Path(charm_path)

    subprocess.check_call(["charmcraft", "pack"])
    return next(pathlib.Path(".").glob("*.charm"))
