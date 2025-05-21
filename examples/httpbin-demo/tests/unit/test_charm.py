# Copyright 2025 david.wilding@canonical.com
# See LICENSE file for licensing details.
#
# Learn more about testing at: https://juju.is/docs/sdk/testing

import ops
import ops.pebble
from ops import testing

from charm import HttpbinDemoCharm


def test_httpbin_pebble_ready():
    # Arrange:
    ctx = testing.Context(HttpbinDemoCharm)
    container = testing.Container("httpbin", can_connect=True)
    state_in = testing.State(containers={container})

    # Act:
    state_out = ctx.run(ctx.on.pebble_ready(container), state_in)

    # Assert:
    updated_plan = state_out.get_container(container.name).plan
    expected_plan = {
        "services": {
            "httpbin": {
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
        state_out.get_container(container.name).service_statuses["httpbin"]
        == ops.pebble.ServiceStatus.ACTIVE
    )
    assert state_out.unit_status == testing.ActiveStatus()


def test_config_changed_valid_can_connect():
    """Test a config-changed event when the config is valid and the container can be reached."""
    # Arrange:
    ctx = testing.Context(HttpbinDemoCharm)  # The default config will be read from charmcraft.yaml
    container = testing.Container("httpbin", can_connect=True)
    state_in = testing.State(
        containers={container},
        config={"log-level": "debug"},  # This is the config the charmer passed with `juju config`
    )

    # Act:
    state_out = ctx.run(ctx.on.config_changed(), state_in)

    # Assert:
    updated_plan = state_out.get_container(container.name).plan
    gunicorn_args = updated_plan.services["httpbin"].environment["GUNICORN_CMD_ARGS"]
    assert gunicorn_args == "--log-level debug"
    assert state_out.unit_status == testing.ActiveStatus()


def test_config_changed_valid_cannot_connect():
    """Test a config-changed event when the config is valid but the container cannot be reached.

    We expect to end up in MaintenanceStatus waiting for the deferred event to
    be retried.
    """
    # Arrange:
    ctx = testing.Context(HttpbinDemoCharm)
    container = testing.Container("httpbin", can_connect=False)
    state_in = testing.State(containers={container}, config={"log-level": "debug"})

    # Act:
    state_out = ctx.run(ctx.on.config_changed(), state_in)

    # Assert:
    assert isinstance(state_out.unit_status, testing.MaintenanceStatus)


def test_config_changed_invalid():
    """Test a config-changed event when the config is invalid."""
    # Arrange:
    ctx = testing.Context(HttpbinDemoCharm)
    container = testing.Container("httpbin", can_connect=True)
    invalid_level = "foobar"
    state_in = testing.State(containers={container}, config={"log-level": invalid_level})

    # Act:
    state_out = ctx.run(ctx.on.config_changed(), state_in)

    # Assert:
    assert isinstance(state_out.unit_status, testing.BlockedStatus)
    assert invalid_level in state_out.unit_status.message
