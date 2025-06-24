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

from charm import FastAPIDemoCharm

import ops
from ops import testing


def test_pebble_layer():
    ctx = testing.Context(FastAPIDemoCharm)
    container = testing.Container(name='demo-server', can_connect=True)
    state_in = testing.State(
        containers={container},
        leader=True,
    )
    state_out = ctx.run(ctx.on.pebble_ready(container), state_in)
    # Expected plan after Pebble ready with default config
    expected_plan = {
        'services': {
            'fastapi-service': {
                'override': 'replace',
                'summary': 'fastapi demo',
                'command': 'uvicorn api_demo_server.app:app --host=0.0.0.0 --port=8000',
                'startup': 'enabled',
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
        state_out.get_container(container.name).service_statuses['fastapi-service']
        == ops.pebble.ServiceStatus.ACTIVE
    )


def test_config_changed():
    ctx = testing.Context(FastAPIDemoCharm)
    container = testing.Container(name='demo-server', can_connect=True)
    state_in = testing.State(
        containers={container},
        config={'server-port': 8080},
        leader=True,
    )
    state_out = ctx.run(ctx.on.config_changed(), state_in)
    command = (
        state_out.get_container(container.name)
        .layers['fastapi_demo']
        .services['fastapi-service']
        .command
    )
    assert '--port=8080' in command


def test_config_changed_invalid_port():
    ctx = testing.Context(FastAPIDemoCharm)
    container = testing.Container(name='demo-server', can_connect=True)
    state_in = testing.State(
        containers={container},
        config={'server-port': 22},
        leader=True,
    )
    state_out = ctx.run(ctx.on.config_changed(), state_in)
    assert state_out.unit_status == testing.BlockedStatus(
        'Invalid port number, 22 is reserved for SSH'
    )
