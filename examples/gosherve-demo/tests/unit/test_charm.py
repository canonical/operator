# Copyright 2021 Jon Seager
# See LICENSE file for licensing details.
#
# Learn more about testing at: https://ops.readthedocs.io/en/latest/explanation/testing.html

"""Unit tests for the Gosherve demo charm."""

import ops
import pytest
from ops import testing

from charm import HelloKubeconCharm


@pytest.mark.parametrize('config', [None, {'redirect-map': 'https://example.com/routes'}])
def test_gosherve_layer(config: dict[str, str | int | float | bool] | None):
    """Test that the layer has the right environment."""
    ctx = testing.Context(HelloKubeconCharm)
    state_in = testing.State.from_context(ctx, config=config)
    state_out = ctx.run(ctx.on.config_changed(), state_in)
    expected = {
        'summary': 'gosherve layer',
        'description': 'pebble config layer for gosherve',
        'services': {
            'gosherve': {
                'override': 'replace',
                'summary': 'gosherve',
                'command': '/gosherve',
                'startup': 'enabled',
                'environment': {
                    'REDIRECT_MAP_URL': config['redirect-map']
                    if config
                    else 'https://github.com/canonical/operator/tree/main/examples/gosherve-demo/demo-routes',
                    'WEBROOT': '/srv',
                },
            }
        },
    }
    layer = state_out.get_container('gosherve').layers['gosherve']
    assert layer.to_dict() == expected


@pytest.mark.parametrize('event_name', ['config_changed', 'pebble_ready'])
def test_on_config_changed(event_name: str):
    """Test the config-changed and pebble-ready hooks."""
    ctx = testing.Context(HelloKubeconCharm)

    # Trigger a config-changed hook. Since there was no plan initially, the
    # "gosherve" service in the container won't be running.
    container = testing.Container(
        'gosherve',
        service_statuses={'gosherve': ops.pebble.ServiceStatus.INACTIVE},
        can_connect=True,
    )
    state_in = testing.State(containers={container})
    event = (
        ctx.on.pebble_ready(container) if event_name == 'pebble_ready' else ctx.on.config_changed()
    )
    state_out = ctx.run(event, state_in)
    assert state_out.unit_status == testing.ActiveStatus()
    assert (
        state_out.get_container('gosherve').service_statuses['gosherve']
        == ops.pebble.ServiceStatus.ACTIVE
    )


def test_on_config_changed_container_not_ready():
    """Test the config-changed hook when the container is not ready."""
    ctx = testing.Context(HelloKubeconCharm)

    # Trigger a config-changed hook. Since the container is not ready, it should
    # set the unit status to WaitingStatus.
    container = testing.Container('gosherve')
    state_in = testing.State(containers={container})
    state_out = ctx.run(ctx.on.config_changed(), state_in)
    assert state_out.unit_status == testing.WaitingStatus(
        'waiting for Pebble in workload container'
    )


@pytest.mark.parametrize(
    'protocol,success',
    [
        ('http://', True),
        ('https://', True),
        ('file:///', False),
    ],
)
def test_config_values(protocol: str, success: bool):
    """Test that the charm blocks if the redirect-map is invalid."""
    ctx = testing.Context(HelloKubeconCharm)
    state_in = testing.State.from_context(
        ctx, config={'redirect-map': f'{protocol}example.com/routes'}
    )
    if success:
        state_out = ctx.run(ctx.on.config_changed(), state_in)
        assert state_out.unit_status == testing.ActiveStatus()
    else:
        # TODO: this is not a great testing experience. Can we improve it?
        with pytest.raises(testing.errors.UncaughtCharmError) as exc_info:
            ctx.run(ctx.on.config_changed(), state_in)
        assert '_Abort' in str(exc_info.value)


def test_no_config():
    """Test that the charm blocks if the redirect-map is missing."""
    ctx = testing.Context(HelloKubeconCharm)
    state_in = testing.State.from_context(ctx, config={'redirect-map': ''})
    # TODO: this is not a great testing experience. Can we improve it?
    with pytest.raises(testing.errors.UncaughtCharmError) as exc_info:
        ctx.run(ctx.on.config_changed(), state_in)
    assert '_Abort' in str(exc_info.value)


def test_on_install(monkeypatch: pytest.MonkeyPatch):
    """Test the install hook."""
    called: dict[str, bool] = {}

    def mock_fetch_site(self: HelloKubeconCharm):
        called['fetch_site'] = True

    monkeypatch.setattr('charm.HelloKubeconCharm._fetch_site', mock_fetch_site)
    ctx = testing.Context(HelloKubeconCharm)
    ctx.run(ctx.on.install(), testing.State())
    assert called.get('fetch_site')


def test_pull_site_action(monkeypatch: pytest.MonkeyPatch):
    """Test the pull_site action."""
    called: dict[str, bool] = {}

    def mock_fetch_site(self: HelloKubeconCharm):
        called['fetch_site'] = True

    monkeypatch.setattr('charm.HelloKubeconCharm._fetch_site', mock_fetch_site)
    ctx = testing.Context(HelloKubeconCharm)
    ctx.run(ctx.on.action('pull-site'), testing.State())
    assert called.get('fetch_site')
