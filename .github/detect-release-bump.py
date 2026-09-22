# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Decide whether a push to a release branch is a release.

Called by the create-draft-release workflow, which runs on every push to
`main` and to the maintenance branches. Almost none of those pushes are
releases, so the usual answer is "no": this prints nothing, exits 0, and
every step after it is skipped.

A release is a push that leaves `ops/version.py` holding a version it did
not hold before, with no `.devN` suffix on it. That is exactly the state
merging the version-bump pull request leaves behind. The post-release bump
writes a `.devN` version, so it reads as "not a release" here without this
having to know where the push came from.

The workflow hands over the two files rather than the two versions, because
reading the version out of that file is the fiddly half:

    python3 .github/detect-release-bump.py \
        --before "$RUNNER_TEMP/version-before.py" --after ops/version.py

Prints `key=value` lines for `$GITHUB_OUTPUT` when the push is a release,
and nothing at all when it is not. Either way it says which it decided, and
why, on stderr, so the run's log is readable when the answer is surprising.

Standard library only, so it runs on a runner with nothing installed.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys

# The one line in ops/version.py that matters.
VERSION_ASSIGNMENT = re.compile(r"^version: str = '(?P<version>[^']*)'$", re.MULTILINE)

# The versions this repository releases, taken apart. The same shape
# .github/update-release-versions.py accepts, because it is the script that
# wrote the string being read back here.
VERSION = re.compile(r'^(\d+)\.(\d+)\.(\d+)((?:a|b|rc)\d+)?(\.dev\d+)?$')


def version_in(source: str) -> str:
    """Return the version assigned in the text of an ops/version.py."""
    match = VERSION_ASSIGNMENT.search(source)
    if not match:
        raise ValueError('no `version: str = ...` line: is this ops/version.py?')
    return match.group('version')


def decide(before: str | None, after: str) -> tuple[str | None, str]:
    """Return the version this push releases, if it releases one, and why.

    `before` is the version the branch held before the push, or None when
    there was no file to read it from. The second half of the pair is a
    sentence for the log, and is there whichever way the decision went.
    """
    if before is None:
        # A branch with no ops/version.py before this push is a branch being
        # created, not a release being merged.
        return None, 'there was no ops/version.py before this push'
    if before == after:
        return None, f'the version is still {after}'
    match = VERSION.match(after)
    if not match:
        # Not a shape we can release, so not something to quietly release
        # anyway. Somebody hand-editing the file is the likely cause.
        return None, f'{after!r} is not a version this repository releases'
    if match.group(5):
        return None, f'{after} is a development version'
    return after, f'{before} became {after}'


def is_prerelease(version: str) -> bool:
    """Return whether a version is an alpha, a beta or a release candidate."""
    match = VERSION.match(version)
    return bool(match and match.group(4))


def main(argv: list[str] | None = None) -> int:
    """Decide, print the outputs if there are any, and say what was decided."""
    parser = argparse.ArgumentParser(description='Decide whether a push is a release.')
    parser.add_argument(
        '--after',
        required=True,
        metavar='PATH',
        help='The ops/version.py the push left behind.',
    )
    parser.add_argument(
        '--before',
        default=None,
        metavar='PATH',
        help='The ops/version.py from before the push. Leave it out if there was none.',
    )
    args = parser.parse_args(argv)

    try:
        after = version_in(pathlib.Path(args.after).read_text())
        before = version_in(pathlib.Path(args.before).read_text()) if args.before else None
    except (OSError, ValueError) as exc:
        print(f'detect-release-bump: {exc}', file=sys.stderr)
        return 1

    version, why = decide(before, after)
    if version is None:
        print(f'Not a release: {why}.', file=sys.stderr)
        return 0

    print(f'Releasing {version}: {why}.', file=sys.stderr)
    print(f'version={version}')
    print(f'prerelease={str(is_prerelease(version)).lower()}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
