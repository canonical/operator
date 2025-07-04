# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.
#
# Learn more about testing at: https://ops.readthedocs.io/en/latest/explanation/testing.html

"""Integration tests for the Gosherve demo charm."""

import jubilant
import pytest


@pytest.fixture(scope='module')
def juju():
    """Fixture to provide a Juju environment for testing."""
    with jubilant.temp_model() as juju:
        yield juju


def test_deploy(juju: jubilant.Juju):
    """Deploy the Gosherve demo charm."""
    juju.deploy('gosherve-demo-k8s', resource={'gosherve-image': 'jnsgruk/gosherve:latest'})
    juju.wait(jubilant.all_active)


def test_with_traefik(juju: jubilant.Juju):
    """Integrate the Gosherve demo charm to Traefik."""
    juju.deploy('traefik-k8s', trust=True)
    juju.config('traefik-k8s', external_hostname='juju.local', routing_mode='subdomain')
    juju.integrate('gosherve-demo-k8s', 'traefik-k8s')
    juju.wait(jubilant.all_active)
