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
from pathlib import Path

import jubilant
import yaml

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path('./charmcraft.yaml').read_text())
APP_NAME = METADATA['name']


def test_deploy(charm: Path, juju: jubilant.Juju):
    """Build the charm-under-test and deploy it together with related charms.

    Assert on the unit status before any relations/configurations take place.
    """
    resources = {
        'demo-server-image': METADATA['resources']['demo-server-image']['upstream-source']
    }

    # Deploy the charm and wait for active/idle status
    juju.deploy(f'./{charm}', app=APP_NAME, resources=resources)
    juju.wait(jubilant.all_active)
