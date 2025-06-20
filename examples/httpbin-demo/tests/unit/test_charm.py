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

from charm import CONTAINER_NAME, SERVICE_NAME, HttpbinDemoCharm

from ops import pebble, testing

# Mocks the default Pebble layer in the workload container. We'll provide this layer to
# testing.Container() to ensure that our collect-status handler can always find the service.
layer = pebble.Layer({
    'services': {
        SERVICE_NAME: {
            'override': 'replace',
            'command': '/bin/foo',
            'startup': 'enabled',
        }
    },
})


def test_httpbin_pebble_ready():
    # Arrange:
    ctx = testing.Context(HttpbinDemoCharm)
    container = testing.Container(
        CONTAINER_NAME,
        can_connect=True,
        layers={'httpbin': layer},
        service_statuses={SERVICE_NAME: pebble.ServiceStatus.INACTIVE},
    )
    state_in = testing.State(containers={container})

    # Act:
    state_out = ctx.run(ctx.on.pebble_ready(container), state_in)

    # Assert:
    updated_plan = state_out.get_container(container.name).plan
    expected_plan = {
        'services': {
            SERVICE_NAME: {
                'override': 'replace',
                'summary': 'httpbin',
                'command': 'gunicorn -b 0.0.0.0:80 httpbin:app -k gevent',
                'startup': 'enabled',
                'environment': {'GUNICORN_CMD_ARGS': '--log-level info'},
            }
        },
    }
    assert expected_plan == updated_plan
    assert (
        state_out.get_container(container.name).service_statuses[SERVICE_NAME]
        == pebble.ServiceStatus.ACTIVE
    )
    assert state_out.unit_status == testing.ActiveStatus()


def test_config_changed_valid_can_connect():
    """Test a config-changed event when the config is valid and the container can be reached."""
    # Arrange:
    ctx = testing.Context(HttpbinDemoCharm)  # The default config will be read from charmcraft.yaml
    container = testing.Container(
        CONTAINER_NAME,
        can_connect=True,
        layers={'httpbin': layer},
        service_statuses={SERVICE_NAME: pebble.ServiceStatus.INACTIVE},
    )
    state_in = testing.State(
        containers={container},
        config={'log-level': 'debug'},  # This is the config the charmer passed with `juju config`
    )

    # Act:
    state_out = ctx.run(ctx.on.config_changed(), state_in)

    # Assert:
    updated_plan = state_out.get_container(container.name).plan
    gunicorn_args = updated_plan.services[SERVICE_NAME].environment['GUNICORN_CMD_ARGS']
    assert gunicorn_args == '--log-level debug'
    assert state_out.unit_status == testing.ActiveStatus()


def test_config_changed_valid_cannot_connect():
    """Test a config-changed event when the config is valid but the container cannot be reached.

    We expect to end up in MaintenanceStatus waiting for the deferred event to
    be retried.
    """
    # Arrange:
    ctx = testing.Context(HttpbinDemoCharm)
    container = testing.Container(CONTAINER_NAME, can_connect=False)
    state_in = testing.State(containers={container}, config={'log-level': 'debug'})

    # Act:
    state_out = ctx.run(ctx.on.config_changed(), state_in)

    # Assert:
    assert isinstance(state_out.unit_status, testing.MaintenanceStatus)


def test_config_changed_valid_uppercase():
    """Test a config-changed event when the config is valid and uppercase."""
    # Arrange:
    ctx = testing.Context(HttpbinDemoCharm)
    container = testing.Container(
        CONTAINER_NAME,
        can_connect=True,
        layers={'httpbin': layer},
        service_statuses={SERVICE_NAME: pebble.ServiceStatus.INACTIVE},
    )
    state_in = testing.State(containers={container}, config={'log-level': 'DEBUG'})

    # Act:
    state_out = ctx.run(ctx.on.config_changed(), state_in)

    # Assert:
    updated_plan = state_out.get_container(container.name).plan
    gunicorn_args = updated_plan.services[SERVICE_NAME].environment['GUNICORN_CMD_ARGS']
    assert gunicorn_args == '--log-level debug'
    assert isinstance(state_out.unit_status, testing.ActiveStatus)


def test_config_changed_invalid():
    """Test a config-changed event when the config is invalid."""
    # Arrange:
    ctx = testing.Context(HttpbinDemoCharm)
    container = testing.Container(
        CONTAINER_NAME,
        can_connect=True,
        layers={'httpbin': layer},
        service_statuses={SERVICE_NAME: pebble.ServiceStatus.INACTIVE},
    )
    invalid_level = 'foobar'
    state_in = testing.State(containers={container}, config={'log-level': invalid_level})

    # Act:
    state_out = ctx.run(ctx.on.config_changed(), state_in)

    # Assert:
    assert isinstance(state_out.unit_status, testing.BlockedStatus)
    assert invalid_level in state_out.unit_status.message
