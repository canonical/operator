# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Check that a PR title follows the Conventional Commits specification.

Reads the PR title from the PR_TITLE environment variable.
Exits with a non-zero status and prints an error message if the title is invalid.

Reference: https://www.conventionalcommits.org/en/v1.0.0/

This repo defines a restricted set of commit types and disallows scopes in PR titles.
"""

from __future__ import annotations

import os
import re
import sys

_TYPES = frozenset({
    'chore',
    'ci',
    'docs',
    'feat',
    'fix',
    'perf',
    'refactor',
    'revert',
    'test',
})

# <type>[optional scope][optional !]: <description>
_PATTERN = re.compile(
    r'^(?p<type>[a-za-z]+)'  # lower-case only, but let this be validated by _TYPES
    r'(?:\((?P<scope>[^()]+)\))?'
    r'(?P<breaking>!)?'
    r': '
    r'(?P<description>.+)$'
)


def _main() -> None:
    title = os.environ.get('PR_TITLE', '').strip()
    if not title:
        print('PR_TITLE environment variable is not set or empty.', file=sys.stderr)
        sys.exit(1)

    match = _PATTERN.match(title)
    if not match:
        print(
            f'PR title does not follow Conventional Commits format.\n'
            f'Expected: <type>[!]: <description>\n'
            f'Got: {title!r}\n'
            'Read more: https://github.com/canonical/operator/blob/main/CONTRIBUTING.md#pull-requests',
            file=sys.stderr,
        )
        sys.exit(1)

    scope = match.group('scope')
    if scope is not None:
        print(
            f'Scopes are not used in PR titles.\n'
            f'Got: {title!r}\n'
            'Read more: https://github.com/canonical/operator/blob/main/CONTRIBUTING.md#pull-requests',
            file=sys.stderr,
        )
        sys.exit(1)

    commit_type = match.group('type')
    if commit_type not in _TYPES:
        print(
            f'Invalid type {commit_type!r} in PR title.\n'
            f'Valid types: {", ".join(sorted(_TYPES))}\n'
            f'Got: {title!r}\n'
            'Read more: https://github.com/canonical/operator/blob/main/CONTRIBUTING.md#pull-requests',
            file=sys.stderr,
        )
        sys.exit(1)

    print(f'OK: {title!r}')


if __name__ == '__main__':
    _main()
