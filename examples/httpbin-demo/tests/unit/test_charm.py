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
from ops import pebble, testing

from charm import CONTAINER_NAME, SERVICE_NAME, HttpbinDemoCharm

layer = pebble.Layer(
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


def test_status_active():
    ctx = testing.Context(HttpbinDemoCharm)
    container = testing.Container(
        CONTAINER_NAME,
        layers={"base": layer},
        service_statuses={SERVICE_NAME: pebble.ServiceStatus.ACTIVE},
        can_connect=True,
    )
    state_in = testing.State(containers={container})
    state_out = ctx.run(ctx.on.update_status(), state_in)
    assert state_out.unit_status == testing.ActiveStatus()


def test_status_inactive():
    ctx = testing.Context(HttpbinDemoCharm)
    container = testing.Container(
        CONTAINER_NAME,
        layers={"base": layer},
        service_statuses={SERVICE_NAME: pebble.ServiceStatus.INACTIVE},
        can_connect=True,
    )
    state_in = testing.State(containers={container})
    state_out = ctx.run(ctx.on.update_status(), state_in)
    assert state_out.unit_status == testing.MaintenanceStatus("waiting for workload")


def test_status_container_down():
    ctx = testing.Context(HttpbinDemoCharm)
    container = testing.Container(CONTAINER_NAME, can_connect=False)
    state_in = testing.State(containers={container})
    state_out = ctx.run(ctx.on.update_status(), state_in)
    assert state_out.unit_status == testing.MaintenanceStatus("waiting for workload container")


def test_status_container_no_plan():
    ctx = testing.Context(HttpbinDemoCharm)
    container = testing.Container(CONTAINER_NAME, can_connect=True)
    state_in = testing.State(containers={container})
    state_out = ctx.run(ctx.on.update_status(), state_in)
    assert state_out.unit_status == testing.MaintenanceStatus("waiting for workload container")


def test_httpbin_pebble_ready():
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


@pytest.mark.parametrize(
    "user_log_level, gunicorn_log_level",
    [
        ("debug", "debug"),
        ("DEBUG", "debug"),
    ],
)
def test_config_changed(user_log_level: str, gunicorn_log_level: str):
    """Test a config-changed event when the config is valid."""
    # Arrange:
    ctx = testing.Context(HttpbinDemoCharm)
    container = testing.Container(CONTAINER_NAME, can_connect=True)
    state_in = testing.State(containers={container}, config={"log-level": user_log_level})
    # Act:
    state_out = ctx.run(ctx.on.config_changed(), state_in)
    # Assert:
    updated_plan = state_out.get_container(container.name).plan
    gunicorn_args = updated_plan.services[SERVICE_NAME].environment["GUNICORN_CMD_ARGS"]
    assert gunicorn_args == f"--log-level {gunicorn_log_level}"
    assert isinstance(state_out.unit_status, testing.ActiveStatus)


@pytest.mark.parametrize(
    "user_log_level",
    [
        "",
        "foobar",
    ],
)
def test_config_changed_invalid(user_log_level: str):
    """Test a config-changed event when the config is invalid."""
    # Arrange:
    ctx = testing.Context(HttpbinDemoCharm)
    container = testing.Container(CONTAINER_NAME, can_connect=True)
    state_in = testing.State(containers={container}, config={"log-level": user_log_level})
    # Act:
    state_out = ctx.run(ctx.on.config_changed(), state_in)
    # Assert:
    assert isinstance(state_out.unit_status, testing.BlockedStatus)
    assert f"'{user_log_level}'" in state_out.unit_status.message
