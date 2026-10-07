# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Work out which version to release, and write its changelog entry.

Called by the propose-release workflow, from its own checkout of the default
branch, with the branch being released as the working directory. Everything
it needs comes from the environment the workflow sets:

    BRANCH         The branch being released.
    VERSION_INPUT  An explicit version, or empty to infer one from the commits.
    DRY_RUN        'true' when nothing is going to be pushed.
    CHANGELOG      The uvx `--from` spec for the team's changelog tool.

It writes the changelog entry for the commits since the last tag to
`$RUNNER_TEMP/changes-entry.md`, for the later steps, and sets `previous` and
`version` as step outputs.
Every refusal is a workflow error annotation and a non-zero exit.
"""

from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys
import typing


def run(*args: str, input: str | None = None) -> str:
    """Run a command and return its stdout, leaving stderr to reach the log."""
    return subprocess.run(args, input=input, stdout=subprocess.PIPE, text=True, check=True).stdout


def succeeds(*args: str) -> bool:
    """Run a command quietly and say whether it exited zero."""
    return subprocess.run(args, capture_output=True).returncode == 0


def fail(message: str) -> typing.NoReturn:
    """Report an error annotation on the workflow run, and stop."""
    print(f'::error::{message}')
    sys.exit(1)


def main() -> None:
    """Pick the version, check it can be released, and write its entry."""
    branch = os.environ['BRANCH']
    version_input = os.environ['VERSION_INPUT']
    dry_run = os.environ['DRY_RUN'] == 'true'
    changelog = os.environ['CHANGELOG']
    repository = os.environ['GITHUB_REPOSITORY']
    runner_temp = pathlib.Path(os.environ['RUNNER_TEMP'])
    tool = ('uvx', '--from', changelog, 'changelog')

    # The last tag on this branch, and not the version in ops/version.py:
    # between releases that file holds the guess the post-release bump left
    # behind. The tag is also where the changelog range starts, so the two
    # cannot drift apart.
    try:
        previous = run(
            'git', 'describe', '--tags', '--abbrev=0', '--match', '[0-9]*.[0-9]*.[0-9]*', 'HEAD'
        ).strip()
    except subprocess.CalledProcessError:
        fail(f'No release tag in the history of {branch} to count from.')
    print(f'Last tag on {branch}: {previous}')

    log_format = run(*tool, 'git-log-format').strip()
    log = run(
        'git', 'log', '--reverse', '--no-merges', f'--format={log_format}', f'{previous}..HEAD'
    )

    if version_input:
        # An explicit version is used as it stands, with no inference: it is
        # the escape hatch for everything below that would otherwise refuse.
        version = version_input
        if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+((a|b|rc)[0-9]+)?', version):
            fail(f"'{version}' is not X.Y.Z or X.Y.Z{{a,b,rc}}N.")
    else:
        # `next-version` prints `version=` and `size=` lines, so the size the
        # maintenance check reads is the one the version was worked out from.
        output = dict(
            line.split('=', 1)
            for line in run(*tool, 'next-version', '--previous', previous, input=log).splitlines()
        )
        version, size = output['version'], output['size']
        print(f'The commits since {previous} are a {size} release.')
        # A feature or a breaking change on a maintenance branch has been put
        # on the wrong branch, and a patch release is not the place to find
        # that out quietly.
        if branch.endswith('-maintenance') and size != 'patch':
            fail(
                f'The commits since {previous} on {branch} are a {size} release: a feature or a breaking change has landed on a maintenance branch. Fix that, or pass an explicit version if this is really intended.'
            )

    if succeeds('git', 'rev-parse', '-q', '--verify', f'refs/tags/{version}'):
        if version_input:
            fail(f'{version} is already tagged.')
        # Inferred, the version can only be taken already if its tag is
        # somewhere this branch can't see: 3.8.3 was released from
        # 3.8-maintenance, so on main the last tag was still 3.8.2 and a patch
        # release came out as 3.8.3 again. Which version main should release
        # next is a person's call.
        fail(
            f"The commits since {previous} make this {version}, but {version} is already tagged outside {branch}'s history (it was probably released from a maintenance branch). Run this again with an explicit version."
        )

    # Checked here rather than at the push, so that a leftover branch costs
    # nothing: everything after this check writes files and spends a model
    # call. A dry run never pushes, so a leftover branch doesn't block one.
    if not dry_run and succeeds(
        'gh', 'api', f'repos/{repository}/git/ref/heads/release-prep-{version}'
    ):
        fail(
            f'A release-prep-{version} branch already exists. Delete it, or finish the pull request that goes with it, before proposing {version} again.'
        )

    entry = run(*tool, 'changes-entry', '--repo', repository, '--tag', version, input=log)
    (runner_temp / 'changes-entry.md').write_text(entry)
    print(entry, end='')

    count = run('git', 'rev-list', '--count', f'{previous}..HEAD').strip()
    print(f'Releasing {version}, from the {count} commits since {previous}.')
    with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
        f.write(f'previous={previous}\nversion={version}\n')


if __name__ == '__main__':
    main()
