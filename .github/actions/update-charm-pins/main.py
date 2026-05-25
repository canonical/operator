# Copyright 2024 Canonical Ltd.

"""Updates pinned versions of charms in tests."""

import logging
import os
import sys

from httpx import Client
from ruamel.yaml import YAML  # ty:ignore[unresolved-import]

yaml = YAML(typ='rt')
yaml.indent(mapping=2, sequence=4, offset=2)

github = Client(
    base_url='https://api.github.com/repos',
    headers={
        'Authorization': f'token {os.getenv("GITHUB_TOKEN")}',
        'Accept': 'application/vnd.github.v3+json',
    },
)


def update_charm_pins(workflow):
    """Update pinned versions of charms in the given GitHub Actions workflow."""
    with open(workflow) as file:
        doc = yaml.load(file)

    # Find the job parameterised with charm repos (skips helper jobs like build-wheels).
    job_name = next(
        name
        for name, job in doc['jobs'].items()
        if 'charm-repo' in (job.get('strategy', {}).get('matrix', {}).get('include', [{}])[0])
    )

    for idx, item in enumerate(doc['jobs'][job_name]['strategy']['matrix']['include']):
        charm_repo = item['charm-repo']
        commit = github.get(f'{charm_repo}/commits').raise_for_status().json()[0]
        data = github.get(f'{charm_repo}/tags').raise_for_status().json()
        comment = ' '.join(
            [tag['name'] for tag in data if tag['commit']['sha'] == commit['sha']]
            + [commit['commit']['committer']['date']]
        )

        # A YAML node, as opposed to a plain value, can be updated in place to tweak comments
        node = doc.mlget(['jobs', job_name, 'strategy', 'matrix', 'include', idx], list_ok=True)
        node['commit'] = commit['sha']
        node.yaml_add_eol_comment(comment, key='commit')

    with open(workflow, 'w') as file:
        yaml.dump(doc, file)


if __name__ == '__main__':
    logging.basicConfig(level='INFO')
    for workflow in ' '.join(sys.argv[1:]).split():
        update_charm_pins(workflow)
