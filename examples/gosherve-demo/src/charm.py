#!/usr/bin/env python3
# Copyright 2021 Jon Seager
# See LICENSE file for licensing details.
#
# Learn more at: https://juju.is/

"""Charm the service.

Refer to the following tutorial for a quick-start guide that will help you
develop a new K8s charm using Ops:

    https://ops.readthedocs.io/en/latest/tutorial/from-zero-to-hero-write-your-first-kubernetes-charm/index.html
"""

import dataclasses
import logging
import urllib.request

import ops
from charms.traefik_k8s.v1.ingress import IngressPerAppRequirer

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True, kw_only=True)
class GosherveConfig:
    """Configuration for the Gosherve charm."""

    redirect_map: str = (
        'https://github.com/canonical/operator/tree/main/examples/gosherve-demo/demo-routes'
    )
    """A URL pointing to a list of redirects for Gosherve."""

    def __post_init__(self):
        """Validate the configuration."""
        if not self.redirect_map:
            raise ValueError('redirect-map must be set in the configuration.')
        if not self.redirect_map.startswith('http'):
            raise ValueError(
                f'Invalid redirect-map URL: {self.redirect_map}. '
                "It must start with 'http' or 'https'."
            )
        try:
            with urllib.request.urlopen(self.redirect_map) as response:  # noqa: S310
                content_type = response.headers.get('Content-Type', '')
                if 'application/json' not in content_type:
                    raise ValueError(
                        f'Invalid redirect-map URL: {self.redirect_map}. '
                        f"Content-Type is '{content_type}', expected 'application/json'."
                    )
        except Exception as e:
            raise ValueError(
                f'Failed to validate redirect-map URL {self.redirect_map!r}: {e}'
            ) from e


class HelloKubeconCharm(ops.CharmBase):
    """Charm the service."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on.install, self._on_install)
        framework.observe(self.on.config_changed, self._on_config_changed)
        framework.observe(self.on['gosherve'].pebble_ready, self._on_config_changed)
        framework.observe(self.on['pull_site'].action, self._pull_site_action)
        self.ingress = IngressPerAppRequirer(
            self,
            port=8080,
            host=f'{self.app.name}-endpoints.{self.model.name}.svc.cluster.local',
            strip_prefix=True,
        )

    def _on_install(self, _: ops.InstallEvent):
        # Download the site:
        self._fetch_site()

    def _on_config_changed(self, _: ops.ConfigChangedEvent | ops.PebbleReadyEvent):
        """Handle the config-changed and pebble-ready events."""
        # Get the gosherve container so we can configure/manipulate it:
        container = self.unit.get_container('gosherve')
        # Create a new config layer:
        layer = self._gosherve_layer()

        try:
            container.add_layer('gosherve', layer, combine=True)
            logging.info("Added updated layer 'gosherve' to Pebble plan.")
            # Tell Pebble to load the new layer and restart the service if needed:
            container.replan()
            logging.info('Replanned gosherve service.')
        except ops.pebble.ConnectionError:
            self.unit.status = ops.WaitingStatus('waiting for Pebble in workload container')
            # We assume here that we'll get a pebble-ready event later, and we
            # will add the layer then.
        else:
            # All is well, set an ActiveStatus
            self.unit.status = ops.ActiveStatus()

    def _gosherve_layer(self) -> ops.pebble.LayerDict:
        """Returns a Pebble configuration layer for Gosherve."""
        config = self.load_config(GosherveConfig, errors='blocked')
        return {
            'summary': 'gosherve layer',
            'description': 'pebble config layer for gosherve',
            'services': {
                'gosherve': {
                    'override': 'replace',
                    'summary': 'gosherve',
                    'command': '/gosherve',
                    'startup': 'enabled',
                    'environment': {
                        'REDIRECT_MAP_URL': config.redirect_map,
                        'WEBROOT': '/srv',
                    },
                }
            },
        }

    def _fetch_site(self):
        """Fetch latest copy of website from GitHub and move into webroot."""
        # Set the site URL:
        site_src = 'https://github.com/canonical/kubecon-2021/blob/main/index.html'
        # Set some status and do some logging:
        self.unit.status = ops.MaintenanceStatus('Fetching web site')
        logger.info('Downloading site from %s', site_src)
        # Download the site:
        urllib.request.urlretrieve(site_src, '/srv/index.html')  # noqa: S310
        # Set the unit status back to Active:
        self.unit.status = ops.ActiveStatus()

    def _pull_site_action(self, event: ops.ActionEvent):
        """Action handler that pulls the latest site archive and unpacks it."""
        self._fetch_site()
        event.set_results({'result': 'site pulled'})


if __name__ == '__main__':  # pragma: nocover
    ops.main(HelloKubeconCharm)
