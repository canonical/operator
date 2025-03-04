#! /usr/bin/env python

# Copyright 2024 Canonical Ltd.
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

"""Update a GitHub workload that runs `tox -e unit` on all published charms.

Charms that are not hosted on GitHub are skipped, as well as any charms where
the source URL could not be found.
"""

import json
import logging
import pathlib
import re
import typing
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)


URL_BASE = 'https://api.charmhub.io/v2/charms/info'
WORKFLOW = pathlib.Path(__file__).parent / 'workflows' / 'published-charms-tests.yaml'

SKIP = {
    # Handled by db-charm-tests.yaml
    'postgresql-operator',
    'postgresql-k8s-operator',
    'mysql-operator',
    'mysql-k8s-operator',
    # Handled by hello-charm-tests.yaml
    'hello-kubecon',  # Not in the canonical org anyway (jnsgruk).
    'hello-juju-charm',  # Not in the canonical org anyway (juju).
    # Handled by observability-charms-tests.yaml
    'alertmanager-k8s-operator',
    'prometheus-k8s-operator',
    'grafana-k8s-operator',
    # This has a redirect, which is too complicated to handle for now.
    'bundle-jupyter',
    # The charms are in a subfolder, which this can't handle yet.
    'jimm',
    'notebook-operators',
    'argo-operators',
    'k8s-operator',
    # Not ops.
    'charm-prometheus-libvirt-exporter',
    'juju-dashboard',
    'charm-openstack-service-checks',
    # Maintenance mode / archived.
    'charm-sysconfig',
}


def packages():
    """Get the list of published charms from Charmhub."""
    logger.info('Fetching the list of published charms')
    url = 'https://charmhub.io/packages.json'
    with urllib.request.urlopen(url, timeout=120) as response:  # noqa: S310 (unsafe URL)
        data = response.read().decode()
        packages = json.loads(data)['packages']
    return packages


def get_source_url(charm: str):
    """Get the source URL for a charm."""
    logger.info("Looking for a 'source' URL for %s", charm)
    try:
        with urllib.request.urlopen(  # noqa: S310 (unsafe URL)
            f'{URL_BASE}/{charm}?fields=result.links', timeout=30
        ) as response:
            data = json.loads(response.read().decode())
            return data['result']['links']['source'][0]
    except (urllib.error.HTTPError, KeyError):
        pass
    logger.info("Looking for a 'bugs-url' URL for %s", charm)
    try:
        with urllib.request.urlopen(  # noqa: S310 (unsafe URL)
            f'{URL_BASE}/{charm}?fields=result.bugs-url', timeout=30
        ) as response:
            data = json.loads(response.read().decode())
            return data['result']['bugs-url']
    except (urllib.error.HTTPError, KeyError):
        pass
    logger.warning('Could not find a source URL for %s', charm)
    return None


def url_to_charm_name(url: typing.Optional[str]):
    """Get the charm name from a URL."""
    if not url:
        return None
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc != 'github.com':
        logger.info('URL %s is not a GitHub URL', url)
        return None
    if not parsed.path.startswith('/canonical'):
        # TODO: Maybe we can include some of these anyway?
        # 'juju-solutions' and 'charmed-kubernetes' seem viable, for example.
        logger.info('URL %s is not a Canonical charm', url)
        return None
    try:
        return urllib.parse.urlparse(url).path.split('/')[2]
    except IndexError:
        logger.warning('Could not get charm name from URL %s', url)
        return None


def main():
    """Update the workflow file."""
    logging.basicConfig(level=logging.INFO)
    charms = [url_to_charm_name(get_source_url(package['name'])) for package in packages()]
    charms = [charm for charm in charms if charm and charm not in SKIP]
    charms.sort()
    with WORKFLOW.open('r') as f:
        workflow = f.read()
    repos = '\n'.join(f'          - charm-repo: canonical/{charm}' for charm in charms)
    workflow = re.sub(r'(\s{10}- charm-repo: \S+\n)+', repos + '\n', workflow, count=1)
    with WORKFLOW.open('w') as f:
        f.write(workflow)


if __name__ == '__main__':
    main()
