# Copyright 2026 Canonical Ltd.
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
# To learn more about testing, see https://canonical.com/juju/docs/ops/latest/explanation/testing/

import ops
import pytest
from ops import testing

from charm import FastAPIDemoCharm


def mock_get_version(port: int):
    """Get a mock version string without executing the workload code."""
    return "0.0.1"


@pytest.fixture
def mock_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("fastapi_demo.get_version", mock_get_version)


def test_pebble_layer(mock_version):
    ctx = testing.Context(FastAPIDemoCharm)
    container = testing.Container(name="demo-server", can_connect=True)
    state_in = testing.State(
        containers={container},
        leader=True,
    )
    state_out = ctx.run(ctx.on.pebble_ready(container), state_in)
    # Expected plan after Pebble ready with default config
    expected_plan = {
        "services": {
            "fastapi-service": {
                "override": "replace",
                "summary": "fastapi demo",
                "command": "uvicorn api_demo_server.app:app --host=0.0.0.0 --port=8000",
                "startup": "enabled",
                # Since the environment is empty, Layer.to_dict() will not
                # include it.
            }
        }
    }

    # Check that we have the plan we expected:
    assert state_out.get_container(container.name).plan == expected_plan
    # Check the unit is active:
    assert state_out.unit_status == testing.ActiveStatus()
    # Check the service was started:
    assert (
        state_out.get_container(container.name).service_statuses["fastapi-service"]
        == ops.pebble.ServiceStatus.ACTIVE
    )
    # Check the workload version is set
    assert state_out.workload_version is not None
