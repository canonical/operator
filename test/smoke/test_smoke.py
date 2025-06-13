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
# Learn more about testing at
# https://ops.readthedocs.io/en/latest/explanation/testing.html

from __future__ import annotations

import grp
import logging
import os
import pathlib
import subprocess

import pytest
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)


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


def pack(charm_dir: pathlib.Path):
    """Pack the charm.

    The pytest-operator plugin has a pack method, but it doesn't work out of the
    box in GitHub actions, and there isn't really any reason that it should be
    part of the plugin, so we just have a simple subprocess here.
    """
    cmd = ['charmcraft', 'pack', '--verbose']
    # We need to use `sudo` in the GitHub actions environment, just as in
    # the pack test. `sg lxd -c` should work, but does not - perhaps because of
    # the way we are installing LXD?
    if 'lxd' not in {grp.getgrgid(g).gr_name for g in os.getgroups()}:
        cmd.insert(0, 'sudo')

    logger.info('Building charm with %r', cmd)
    subprocess.run(cmd, cwd=charm_dir, check=True)
    logger.info('Built charm')

    # Move the packed charm to the charm directory.
    dest_name = None
    for charm in charm_dir.glob('*.charm'):
        dest_name = charm_dir / charm.name
        charm.rename(dest_name)
    # With the way we use charmcraft, we know that there will only be one.
    return dest_name.absolute()


@pytest.mark.parametrize(
    'base,charmcraft_version,name',
    (
        ('20.04', 3, 'focal'),
        ('22.04', 3, 'jammy'),
        ('24.04', 3, 'noble'),
    ),
)
async def test_smoke(ops_test: OpsTest, base: str, charmcraft_version: int, name: str):
    """Verify that we can build and deploy charms from supported bases."""
    available_charmcraft_version = (
        subprocess.run(['charmcraft', 'version'], check=True, capture_output=True)  # noqa: S607
        .stdout.decode()
        .strip()
        .rsplit()[-1]
        .split('.')
    )
    if int(available_charmcraft_version[0]) < charmcraft_version:
        pytest.skip(f'charmcraft version {available_charmcraft_version} is too old for this test')
        return
    charmcraft_yaml = {
        3: CHARMCRAFT3_YAML,
    }[charmcraft_version].format(base=base)
    with open('./test/charms/test_smoke/charmcraft.yaml', 'w') as outf:
        outf.write(charmcraft_yaml)
    charm = pack(pathlib.Path('./test/charms/test_smoke/'))

    app = await ops_test.model.deploy(
        charm, base=f'ubuntu@{base}', application_name=f'{name}-smoke'
    )
    await ops_test.model.wait_for_idle(timeout=600)

    assert app.status == 'active', f"Base ubuntu@{base} failed with '{app.status}' status"


@pytest.fixture
def setup_tracing():
    """Stub out the top-level fixture."""
    pass
