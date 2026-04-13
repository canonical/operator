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

import ops
import pytest
from ops import testing

from charm import CONTAINER_NAME, SERVICE_NAME, HttpbinDemoCharm

# A mock Pebble layer - useful for testing the charm's status reporting code. The status reporting
# code shouldn't care how the service is started, so the layer doesn't need the real command.
MOCK_LAYER = ops.pebble.Layer(
    {
        "services": {
            SERVICE_NAME: {
                "override": "replace",
                "command": "mock-command",
                "startup": "enabled",
            },
        },
    }
)


def test_pebble_ready():
    """Check that the charm correctly starts the service in the container."""
    # Arrange:
    ctx = testing.Context(HttpbinDemoCharm)
    container = testing.Container(CONTAINER_NAME, can_connect=True)
    state_in = testing.State(containers={container})
    # Act:
    state_out = ctx.run(ctx.on.pebble_ready(container), state_in)
    # Assert:
    updated_plan = state_out.get_container(container.name).plan
    expected_plan = {
        "services": {
            SERVICE_NAME: {
                "override": "replace",
                "summary": "httpbin",
                "command": "gunicorn -b 0.0.0.0:80 httpbin:app -k gevent",
                "startup": "enabled",
                "environment": {"GUNICORN_CMD_ARGS": "--log-level info"},
            }
        },
    }
    assert expected_plan == updated_plan
    assert (
        state_out.get_container(container.name).service_statuses[SERVICE_NAME]
        == ops.pebble.ServiceStatus.ACTIVE
    )
    assert state_out.unit_status == testing.ActiveStatus()


def test_status_service_active():
    """Check that the charm goes into active status if the service is active.

    This test is useful in addition to ``test_pebble_ready()`` because it checks that the charm
    consistently sets active status, regardless of which event was handled.
    """
    ctx = testing.Context(HttpbinDemoCharm)
    container = testing.Container(
        CONTAINER_NAME,
        layers={"base": MOCK_LAYER},
        service_statuses={SERVICE_NAME: ops.pebble.ServiceStatus.ACTIVE},
        can_connect=True,
    )
    state_in = testing.State(containers={container})
    state_out = ctx.run(ctx.on.update_status(), state_in)
    assert state_out.unit_status == testing.ActiveStatus()


def test_status_service_inactive():
    """Check that the charm goes into maintenance status if the service isn't active."""
    ctx = testing.Context(HttpbinDemoCharm)
    container = testing.Container(
        CONTAINER_NAME,
        layers={"base": MOCK_LAYER},
        service_statuses={SERVICE_NAME: ops.pebble.ServiceStatus.INACTIVE},
        can_connect=True,
    )
    state_in = testing.State(containers={container})
    state_out = ctx.run(ctx.on.update_status(), state_in)
    assert state_out.unit_status == testing.MaintenanceStatus("waiting for workload")


def test_status_no_service():
    """Check that the charm goes into maintenance status if the service hasn't been defined."""
    ctx = testing.Context(HttpbinDemoCharm)
    container = testing.Container(CONTAINER_NAME, can_connect=True)
    state_in = testing.State(containers={container})
    state_out = ctx.run(ctx.on.update_status(), state_in)
    assert state_out.unit_status == testing.MaintenanceStatus("waiting for workload container")


def test_status_no_pebble():
    """Check that the charm goes into maintenance status if the container is down."""
    ctx = testing.Context(HttpbinDemoCharm)
    container = testing.Container(CONTAINER_NAME, can_connect=False)
    state_in = testing.State(containers={container})
    state_out = ctx.run(ctx.on.update_status(), state_in)
    assert state_out.unit_status == testing.MaintenanceStatus("waiting for workload container")


@pytest.mark.parametrize(
    "user_log_level, gunicorn_log_level",
    [
        ("debug", "debug"),
        ("DEBUG", "debug"),
    ],
)
def test_config_changed(user_log_level: str, gunicorn_log_level: str):
    """Test a config-changed event when the config is valid."""
    ctx = testing.Context(HttpbinDemoCharm)
    container = testing.Container(CONTAINER_NAME, can_connect=True)
    state_in = testing.State(containers={container}, config={"log-level": user_log_level})
    state_out = ctx.run(ctx.on.config_changed(), state_in)
    updated_plan = state_out.get_container(container.name).plan
    gunicorn_args = updated_plan.services[SERVICE_NAME].environment["GUNICORN_CMD_ARGS"]
    assert gunicorn_args == f"--log-level {gunicorn_log_level}"
    assert state_out.unit_status == testing.ActiveStatus()


@pytest.mark.parametrize(
    "user_log_level",
    [
        "",
        "foobar",
    ],
)
def test_config_changed_invalid(user_log_level: str):
    """Test a config-changed event when the config is invalid."""
    ctx = testing.Context(HttpbinDemoCharm)
    container = testing.Container(CONTAINER_NAME, can_connect=True)
    state_in = testing.State(containers={container}, config={"log-level": user_log_level})
    state_out = ctx.run(ctx.on.config_changed(), state_in)
    assert isinstance(state_out.unit_status, testing.BlockedStatus)
    assert state_out.unit_status.message.startswith(f"Invalid log level: '{user_log_level}'.")
