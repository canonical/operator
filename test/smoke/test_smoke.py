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

from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)


async def test_smoke(ops_test: OpsTest):
    # Verify that we can deploy charms from supported series.

    # Build the charm. (We just build it for focal -- it *should* work to deploy it on
    # older versions of Juju.)
    charm = await ops_test.build_charm("./test/charms/test_smoke/")

    for series in ['focal', 'bionic', 'xenial']:
        app = await ops_test.model.deploy(
            charm, series=series, application_name=f"{series}-smoke")
        await ops_test.model.wait_for_idle(timeout=600)

        assert app.status == "active", f"Series {series} failed with '{app.status}' status"
