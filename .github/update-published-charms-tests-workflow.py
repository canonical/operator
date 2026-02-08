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

When running locally, you can bypass issues with fetching charmhub.io/packages.json
by saving the file locally and passing it via the `--packages` argument.

The most expensive part of the script is fetching the individual charm urls from Charmhub.
Make rerunning the script during development faster by directing the stdout of this script
to a file when running it for the first time, and passing the file via the `--charms`
argument on subsequent runs.
"""

from __future__ import annotations

import argparse
import json
import logging
import pathlib
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
    # Not ops.
    'charm-prometheus-libvirt-exporter',
    'juju-dashboard',
    'charm-openstack-service-checks',
    # Maintenance mode / archived.
    'charm-sysconfig',
    # A bundle, not a charm.
    'cos-lite-bundle',
    # Source is not public.
    'charm-weebl',
}
CHARM_ROOTS = {
    'argo-operators': ['charms/argo-controller'],
    'jimm': ['charms/jimm'],
    'k8s-operator': ['charms/worker', 'charms/worker/k8s'],
    'katib-operators': ['charms/katib-controller', 'charms/katib-db-manager', 'charms/katib-ui'],
    'kfp-operators': [
        'charms/kfp-api',
        'charms/kfp-metadata-writer',
        'charms/kfp-persistence',
        'charms/kfp-profile-controller',
        'charms/kfp-schedwf',
        'charms/kfp-ui',
        'charms/kfp-viewer',
        'charms/kfp-viz',
    ],
    'notebook-operators': ['charms/jupyter-controller', 'charms/jupyter-ui'],
    'vault-k8s-operator': ['k8s', 'machine'],
}


def get_packages_from_charmhub():
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
    except (urllib.error.HTTPError, KeyError, IndexError):
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


def url_to_charm_name(url: str | None):
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
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        '--packages',
        type=pathlib.Path,
        help='A JSON file matching the format served by Charmhub.',
    )
    group.add_argument(
        '--charms',
        type=pathlib.Path,
        help='A JSON file matching the format output by this script.',
    )
    args = parser.parse_args()
    # Load charm info from Charmhub or local files.
    if args.charms:
        charms = json.loads(args.charms.read_text())
    else:
        if args.packages:
            packages = json.loads(args.packages.read_text())['packages']
        else:
            packages = get_packages_from_charmhub()
        charms = [url_to_charm_name(get_source_url(pkg['name'])) for pkg in packages]
        charms = sorted({c for c in charms if c})
    print(json.dumps(charms))
    # Create new `include` entries for workflow.
    lines: list[str] = []
    indent = ' ' * 10
    for charm in charms:
        if charm in SKIP:
            continue
        for root in CHARM_ROOTS.get(charm, ['.']):
            lines.extend((
                f'{indent}- charm-repo: canonical/{charm}\n',
                f'{indent}  charm-root: {root}\n',
            ))
    # Replace old autogenerated content in workflow file.
    workflow = WORKFLOW.read_text().splitlines(keepends=True)
    begin = workflow.index('# BEGIN AUTOGENERATED CONTENT\n')
    end = workflow.index('# END AUTOGENERATED CONTENT\n')
    assert begin < end
    workflow[begin + 1 : end] = lines
    WORKFLOW.write_text(''.join(workflow))


if __name__ == '__main__':
    main()
