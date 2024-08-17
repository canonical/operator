# Copyright 2022 Canonical Ltd.
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
# Learn more about testing at: https://juju.is/docs/sdk/testing

import logging

import pytest
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)


CHARMCRAFT2_YAML = """
type: "charm"
bases:
  - build-on:
    - name: "ubuntu"
      channel: "{base}"
    run-on:
    - name: "ubuntu"
      channel: "{base}"
"""

CHARMCRAFT3_YAML = """
type: "charm"
base: ubuntu@{base}
platforms:
  amd64:
parts:
    charm:
        plugin: charm
        source: .
"""


@pytest.mark.parametrize(
    'base,charmcraft_version,name',
    (
        ('20.04', 2, 'focal'),
        ('22.04', 2, 'jammy'),
        ('24.04', 3, 'noble'),
    ),
)
async def test_smoke(ops_test: OpsTest, base: str, charmcraft_version: int, name: str):
    """Verify that we can build and deploy charms from supported bases."""
    charmcraft_yaml = {
        2: CHARMCRAFT2_YAML,
        3: CHARMCRAFT3_YAML,
    }[charmcraft_version].format(base=base)
    with open('./test/charms/test_smoke/charmcraft.yaml', 'w') as outf:
        outf.write(charmcraft_yaml)
    charm = await ops_test.build_charm('./test/charms/test_smoke/')

    app = await ops_test.model.deploy(
        charm, base=f'ubuntu@{base}', application_name=f'{name}-smoke'
    )
    await ops_test.model.wait_for_idle(timeout=600)

    assert app.status == 'active', f"Base ubuntu@{base} failed with '{app.status}' status"
