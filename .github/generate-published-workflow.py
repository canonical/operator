#! /usr/bin/env python

# /// script
# dependencies = [
#   "PyYAML",
#   "requests",
#   "rich",
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

import pathlib
import urllib.parse

import requests
import rich.console
import yaml

console = rich.console.Console()


URL_BASE = 'https://api.charmhub.io/v2/charms/info'
WORKFLOW = pathlib.Path(__file__).parent / 'workflows' / 'published-charms-tests.yaml'

SKIP = {
    # Handled by db-charm-tests.yaml
    'postgresql-operator',
    'postgresql-k8s-operator',
    'mysql-operator',
    'mysql-k8s-operator',
    # Handled by hello-charm-tests.yaml
    'hello-kubecon',  # Also not in the canonical org, but jnsgruk.
    'hello-juju-charm',  # Also not in the canonical org, but juju.
    # Handler by observability-charms-tests.yaml
    'alertmanager-k8s-operator',
    'prometheus-k8s-operator',
    'grafana-k8s-operator',
}


def packages(session: requests.Session):
    """Get the list of published charms from Charmhub."""
    console.log('Fetching the list of published charms')
    resp = session.get('https://charmhub.io/packages.json')
    return resp.json()['packages']


def get_source_url(charm: str, session: requests.Session):
    """Get the source URL for a charm."""
    console.log(f"Looking for a 'source' URL for {charm}")
    try:
        source = session.get(f'{URL_BASE}/{charm}?fields=result.links')
        source.raise_for_status()
        return source.json()['result']['links']['source'][0]
    except (requests.HTTPError, KeyError):
        pass
    console.log(f"Looking for a 'bugs-url' URL for {charm}")
    try:
        source = session.get(f'{URL_BASE}/{charm}?fields=result.bugs-url')
        source.raise_for_status()
        return source.json()['result']['bugs-url']
    except (requests.HTTPError, KeyError):
        pass
    # TODO: Can we try anything else?
    console.log(f'Could not find a source URL for {charm}')
    return None


def url_to_charm_name(url: str):
    """Get the charm name from a URL."""
    if not url:
        return None
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc != 'github.com':
        console.log(f'URL {url} is not a GitHub URL')
        return None
    if not parsed.path.startswith('/canonical'):
        # TODO: Maybe we can include some of these anyway?
        # 'juju-solutions' and 'charmed-kubernetes' seem viable, for example.
        console.log(f'URL {url} is not a Canonical charm')
    try:
        return urllib.parse.urlparse(url).path.split('/')[2]
    except IndexError:
        console.log(f'Could not get charm name from URL {url}')
        return None


def main():
    """Update the workflow file."""
    session = requests.Session()
    charms = (
        url_to_charm_name(get_source_url(package['name'], session))
        for package in packages(session)
    )
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
