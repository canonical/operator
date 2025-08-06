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


from __future__ import annotations

import grp
import logging
import os
import pathlib
import subprocess

import jubilant_backports
import pytest

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
    assert dest_name
    return dest_name.absolute()


@pytest.mark.parametrize('base', ['22.04', '24.04'])
def test_smoke(juju: jubilant_backports.Juju, base: str):
    """Verify that we can build and deploy charms from supported bases."""
    available_charmcraft_version = (
        subprocess.run(['charmcraft', 'version'], check=True, capture_output=True)  # noqa: S607
        .stdout.decode()
        .strip()
        .rsplit()[-1]
        .split('.')
    )
    if int(available_charmcraft_version[0]) < 3:
        pytest.skip('This test requires charmcraft 3')

    charmcraft_yaml = CHARMCRAFT3_YAML.format(base=base)
    with open('./test/charms/test_smoke/charmcraft.yaml', 'w') as outf:
        outf.write(charmcraft_yaml)
    charm = pack(pathlib.Path('./test/charms/test_smoke/'))

    app = f'smoke{base.replace(".", "")}'
    juju.deploy(charm, app=app, base=f'ubuntu@{base}')
    juju.wait(lambda status: jubilant_backports.all_active(status, app), timeout=600)


@pytest.fixture(scope='module')
def juju():
    with jubilant_backports.temp_model() as juju:
        yield juju


@pytest.fixture
def setup_tracing():
    """Stub out the top-level fixture."""
    pass
