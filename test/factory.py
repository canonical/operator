# Copyright 2020 Canonical Ltd.
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

"""Functions to create useful objects for testing."""

import os
from unittest.mock import patch

from ops.framework import Framework
from ops.model import Model, ModelBackend
from ops.charm import CharmMeta


def create_framework(testcase, *, model=None, tmpdir=None):
    """Create a Framework object.

    By default operate in-memory; pass a temporary directory through 'tmpdir' parameter if
    whish to instantiate several frameworks sharing the same dir (e.g. for storing state).
    """
    if tmpdir is None:
        data_fpath = ":memory:"
        charm_dir = 'non-existant'
    else:
        data_fpath = tmpdir / "framework.data"
        charm_dir = tmpdir

    framework = Framework(data_fpath, charm_dir, meta=None, model=model)
    testcase.addCleanup(framework.close)
    return framework


def create_model(testcase):
    """Create a Model object."""
    unit_name = 'myapp/0'
    patcher = patch.dict(os.environ, {'JUJU_UNIT_NAME': unit_name})
    patcher.start()
    testcase.addCleanup(patcher.stop)

    backend = ModelBackend()
    meta = CharmMeta()
    model = Model('myapp/0', meta, backend)
    return model
