# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Work out the post-release bump: which branch, and which version.

Called by the post-release workflow, which runs when a release is published.
Two questions have to be answered before anything can be rewritten:

- **Which branch was this released from?** It decides where the pull request
  goes, and whether the bump is a patch or a minor one. The release event
  carries a tag and a `target_commitish`, and the second of those is a commit
  SHA whenever the draft was made by the create-draft-release workflow. So
  the workflow hands over what git can tell it - which release branches exist
  and which of them contain the tag - and `resolve_branch` decides.
- **Which version does the branch go to now?** `next_dev_version` works it
  out from the released version, rather than from `ops/version.py`.

The version this prints is a placeholder, not a prediction. It stops the tree
claiming to be the version just released; nothing counts from it, because the
propose-release workflow counts from the last tag.

    python3 .github/post-release-version.py --tag 3.8.2 --target <sha> \
        --candidates main,2.23-maintenance --containing main

Prints `key=value` lines for `$GITHUB_OUTPUT`, and says what it decided and
why on stderr. Standard library only, so it runs on a runner with nothing
installed.
"""

from __future__ import annotations

import argparse
import re
import sys

# The versions this repository releases, taken apart. The same shape
# .github/update-release-versions.py accepts and .github/detect-release-bump.py
# reads back, because they are all looking at the same strings.
VERSION = re.compile(r'^(\d+)\.(\d+)\.(\d+)((?:a|b|rc)\d+)?(\.dev\d+)?$')

# The branch every release that is not a maintenance release comes from, and
# the answer when more than one branch contains the tag. See resolve_branch.
DEFAULT_BRANCH = 'main'

# What makes a branch a maintenance branch.
MAINTENANCE_SUFFIX = '-maintenance'


def next_dev_version(released: str, branch: str) -> str:
    """Return the development version the branch goes to after this release.

    The released version is passed in rather than read out of
    `ops/version.py`:

    - a pre-release goes back to its own base version, so publishing 3.4.0b3
      leaves the branch working towards `3.4.0.dev0`;
    - a maintenance branch bumps the patch, so 2.23.5 leaves
      `2.23.6.dev0`;
    - anything else bumps the minor, so 3.8.2 leaves `3.9.0.dev0`.

    The pre-release test comes first, so a release candidate cut from a
    maintenance branch drops its suffix rather than bumping the patch.
    """
    match = VERSION.match(released)
    if not match:
        raise ValueError(f'Not a version this script can take apart: {released!r}')
    major, minor, patch, pre, _dev = match.groups()

    if pre is not None:
        # Only the pre-release suffix is checked, never `.devN`, so a
        # development version falls through to the bumps below. Nothing can
        # reach that through this pipeline - the create-draft-release
        # workflow will not draft a release for a `.devN` version.
        return f'{major}.{minor}.{patch}.dev0'
    if branch.endswith(MAINTENANCE_SUFFIX):
        return f'{major}.{minor}.{int(patch) + 1}.dev0'
    return f'{major}.{int(minor) + 1}.0.dev0'


def resolve_branch(target: str, candidates: list[str], containing: list[str]) -> tuple[str, str]:
    """Return the branch a release was cut from, and why we think so.

    `target` is the event's `release.target_commitish`, `candidates` is every
    release branch that exists, and `containing` is the ones whose history has
    the released tag in it.

    A release drafted by the create-draft-release workflow carries a commit
    SHA as its `target_commitish`, so the name is usually no help and the
    containment answers it instead. A release made by hand through the web
    interface carries a branch name, and then the name is the better answer:
    it is what somebody chose.

    Containment on its own is ambiguous for a release cut from `main` before
    a maintenance branch was taken off it, because the tag is in the history
    of both. `main` is the right tie-break: a release really cut from a
    maintenance branch is never in `main`'s history, because that is what the
    branch is for.
    """
    if containing:
        if target in containing:
            return target, f'the release names {target}, which has the tag in it'
        if len(containing) == 1:
            return containing[0], f'{containing[0]} is the only branch with the tag in it'
        if DEFAULT_BRANCH in containing:
            names = ', '.join(containing)
            return DEFAULT_BRANCH, f'{names} all have the tag in it, and {DEFAULT_BRANCH} wins'
        names = ', '.join(containing)
        raise ValueError(
            f'{names} all have this tag in their history and none of them is '
            f'{DEFAULT_BRANCH}, so which branch was released is a guess. Open the '
            f'post-release pull request by hand.'
        )
    if target in candidates:
        # No tag in the checkout to place, but the release names a branch we
        # release from, so take it at its word.
        return target, f'the release names {target}, and the tag is not in the checkout'
    raise ValueError(
        f'No release branch has this tag in its history, and {target!r} is not one '
        f'of them ({", ".join(candidates) or "none found"}). Either the release was '
        f'cut from somewhere this workflow does not know about, or the checkout is '
        f'missing the tag.'
    )


def split(value: str) -> list[str]:
    """Return a comma-separated list, with the empties dropped."""
    return [item.strip() for item in value.split(',') if item.strip()]


def main(argv: list[str] | None = None) -> int:
    """Decide the branch and the version, and print them for $GITHUB_OUTPUT."""
    parser = argparse.ArgumentParser(description='Work out the post-release bump.')
    parser.add_argument(
        '--tag', required=True, metavar='X.Y.Z', help='The tag of the release that was published.'
    )
    parser.add_argument(
        '--target',
        default='',
        metavar='COMMITTISH',
        help="The release's target_commitish: a branch name, or a commit SHA.",
    )
    parser.add_argument(
        '--candidates',
        default='',
        metavar='A,B',
        help='Every branch this repository releases from.',
    )
    parser.add_argument(
        '--containing',
        default='',
        metavar='A,B',
        help='Those of them whose history contains the released tag.',
    )
    args = parser.parse_args(argv)

    try:
        branch, why = resolve_branch(args.target, split(args.candidates), split(args.containing))
        version = next_dev_version(args.tag, branch)
    except ValueError as exc:
        print(f'post-release-version: {exc}', file=sys.stderr)
        return 1

    print(f'{args.tag} was released from {branch}: {why}.', file=sys.stderr)
    print(f'{branch} goes to {version}.', file=sys.stderr)
    print(f'branch={branch}')
    print(f'version={version}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
