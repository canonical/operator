#! /usr/bin/env python

# /// script
# dependencies = [
#   "PyYAML",
# ]
# ///

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
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

import yaml


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
    # Not ops.
    'charm-prometheus-libvirt-exporter',
    'juju-dashboard',
    'charm-openstack-service-checks',
}


def packages():
    """Get the list of published charms from Charmhub."""
    logger.info('Fetching the list of published charms')
    url = 'https://charmhub.io/packages.json'
    with urllib.request.urlopen(url) as response:
        data = response.read().decode()
        packages = json.loads(data)['packages']
    return packages


def get_source_url(charm: str):
    """Get the source URL for a charm."""
    logger.info("Looking for a 'source' URL for %s", charm)
    try:
        with urllib.request.urlopen(f'{URL_BASE}/{charm}?fields=result.links') as response:
            data = json.loads(response.read().decode())
            return data['result']['links']['source'][0]
    except (urllib.error.HTTPError, KeyError):
        pass
    logger.info("Looking for a 'bugs-url' URL for %s", charm)
    try:
        with urllib.request.urlopen(f'{URL_BASE}/{charm}?fields=result.bugs-url') as response:
            data = json.loads(response.read().decode())
            return data['result']['bugs-url']
    except (urllib.error.HTTPError, KeyError):
        pass
    logger.warning('Could not find a source URL for %s', charm)
    return None


def url_to_charm_name(url: str):
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
    charms = (url_to_charm_name(get_source_url(package['name'])) for package in packages())
    with WORKFLOW.open('r') as f:
        workflow = yaml.safe_load(f)
    workflow['jobs']['charm-tests']['strategy']['matrix']['include'] = [
        {'charm-repo': f'canonical/{charm}'} for charm in charms if charm and charm not in SKIP
    ]
    with WORKFLOW.open('w') as f:
        yaml.dump(workflow, f)
    # yaml.safe_load/yaml.dump transforms "on" to "true". I'm not sure how to avoid that.
    with WORKFLOW.open('r') as f:
        content = f.read().replace('true:', 'on:')
    with WORKFLOW.open('w') as f:
        f.write(content)
    # TODO: the "Update 'ops' dependency in test charm to latest" run command also gets messed up
    # and has to get fixed.


if __name__ == '__main__':
    main()
