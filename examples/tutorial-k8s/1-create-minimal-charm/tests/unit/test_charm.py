import ops
from ops import testing

from charm import FastAPIDemoCharm


def test_pebble_layer():
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
    # Check the unit status is active
    assert state_out.unit_status == testing.ActiveStatus()
    # Check the service was started:
    assert (
        state_out.get_container(container.name).service_statuses["fastapi-service"]
        == ops.pebble.ServiceStatus.ACTIVE
    )
