# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Rewrite the version strings across the repository for a release.

Called by the propose-release workflow, which has already worked out which
version is being released, and again by the post-release workflow, which has
worked out which development version the branch goes back to. This script only
writes files: it does not decide the version, run git, or talk to GitHub, and
it deliberately does not run `uv lock` either, so that the lockfile update is
a visible workflow step rather than something buried in here.

The ops-to-scenario relationship and the fan-out over the four packages are
the parts of the release that are specific to this repository, so they stay
here rather than moving to the shared changelog package.

Reads nothing but the files it rewrites:

    python3 .github/update-release-versions.py --version 3.9.0
    python3 .github/update-release-versions.py --version 3.9.0.dev0 --post-release

The two differ in one thing: `--post-release` leaves the tool-versions table
alone. That table records when a major.minor was released and when it goes
out of support, and a post-release bump is neither - it is the tree saying it
is no longer the version that just shipped. Writing a row for a development
version would put a release date on a release that has not happened.
"""

from __future__ import annotations

import argparse
import datetime
import pathlib
import re
import sys

# Matches the version strings already written into the files, which may carry
# a pre-release or a dev suffix even when the version being released does not.
EXISTING_VERSION = r'(\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?(?:\.dev\d+)?)'

# Matches a version this script will accept, and takes it apart.
VERSION = re.compile(r'^(\d+)\.(\d+)\.(\d+)((?:a|b|rc)\d+)?(\.dev\d+)?$')

VERSION_FILES = {
    'ops/src': pathlib.Path('ops/version.py'),
    'ops/pyproject': pathlib.Path('pyproject.toml'),
    'testing': pathlib.Path('testing/pyproject.toml'),
    'tracing': pathlib.Path('tracing/pyproject.toml'),
    'versions_doc': pathlib.Path('docs/explanation/versions.md'),
}

# How far ahead of ops the ops-scenario version runs. Exactly, and forever:
# ops 3.1.2 is scenario 8.1.2, and any pre-release or dev suffix is carried
# across unchanged.
SCENARIO_MAJOR_OFFSET = 5


def scenario_version(ops_version: str) -> str:
    """Return the ops-scenario version that goes with an ops version."""
    match = VERSION.match(ops_version)
    if not match:
        raise ValueError(f'Not a version this script can take apart: {ops_version!r}')
    major, minor, patch, pre, dev = match.groups()
    return f'{int(major) + SCENARIO_MAJOR_OFFSET}.{minor}.{patch}{pre or ""}{dev or ""}'


def update_pyproject(path: pathlib.Path, version: str, deps: dict[str, str]) -> None:
    """Rewrite a pyproject.toml's own version and its pins on our own packages."""
    content = path.read_text()
    updated = re.sub(rf'version = "{EXISTING_VERSION}"', f'version = "{version}"', content)
    for package, pinned in deps.items():
        updated = re.sub(rf'{package}=={EXISTING_VERSION}', f'{package}=={pinned}', updated)
    if content == updated:
        raise ValueError(f'Nothing changed in {path}: is it already at {version}?')
    path.write_text(updated)
    print(f'{path}: version {version}, pins {deps}')


def update_ops(ops_version: str, testing_version: str) -> None:
    """Rewrite ops/version.py and the top-level pyproject.toml."""
    path = VERSION_FILES['ops/src']
    content = path.read_text()
    updated = re.sub(
        rf"^version: str = '{EXISTING_VERSION}'$",
        f"version: str = '{ops_version}'",
        content,
        flags=re.MULTILINE,
    )
    if content == updated:
        raise ValueError(f'Nothing changed in {path}: is it already at {ops_version}?')
    path.write_text(updated)
    print(f'{path}: version {ops_version}')

    update_pyproject(
        VERSION_FILES['ops/pyproject'],
        ops_version,
        deps={'ops-scenario': testing_version, 'ops-tracing': ops_version},
    )


def update_testing(ops_version: str, testing_version: str) -> None:
    """Rewrite testing/pyproject.toml."""
    update_pyproject(VERSION_FILES['testing'], testing_version, deps={'ops': ops_version})


def update_tracing(ops_version: str) -> None:
    """Rewrite tracing/pyproject.toml."""
    update_pyproject(VERSION_FILES['tracing'], ops_version, deps={'ops': ops_version})


def update_versions_doc(ops_version: str, released: datetime.date) -> None:
    """Rewrite this major version's row in the tool-versions table.

    The row carries the release date and an end-of-life date a year later.
    A missing doc is not an error: it is documentation rather than something
    the release depends on.
    """
    match = VERSION.match(ops_version)
    if not match:
        raise ValueError(f'Not a version this script can take apart: {ops_version!r}')
    major, minor = match.group(1), match.group(2)

    try:
        eol = released.replace(year=released.year + 1)
    except ValueError:
        # 29 February has no anniversary in a non-leap year.
        eol = datetime.date(released.year + 1, 3, 1)

    path = VERSION_FILES['versions_doc']
    if not path.exists():
        print(f'{path}: not present, skipping')
        return
    content = path.read_text()
    pattern = rf'(\| Ops {major})\.\d+ (\| [^|]+ \|) [^|]+ \| [^|]+ \|'
    replacement = rf'\1.{minor} \2 {released:%Y-%m-%d} | {eol:%Y-%m-%d} |'
    updated = re.sub(pattern, replacement, content)
    if content == updated:
        raise ValueError(f'Nothing changed in {path}: is there an "Ops {major}.x" row?')
    path.write_text(updated)
    print(f'{path}: Ops {major}.{minor}, released {released:%Y-%m-%d}, EOL {eol:%Y-%m-%d}')


def main(argv: list[str] | None = None) -> int:
    """Rewrite every version file for the release, and say what changed."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--version',
        required=True,
        metavar='X.Y.Z',
        help='The ops version being released. The scenario version follows from it.',
    )
    parser.add_argument(
        '--date',
        type=datetime.date.fromisoformat,
        default=None,
        metavar='YYYY-MM-DD',
        help="The release date for the versions doc. Defaults to today's date, in UTC.",
    )
    parser.add_argument(
        '--post-release',
        action='store_true',
        help='Bump back to a development version: the same fan-out, without the versions doc.',
    )
    args = parser.parse_args(argv)

    released = args.date or datetime.datetime.now(datetime.timezone.utc).date()
    try:
        testing_version = scenario_version(args.version)
        update_ops(args.version, testing_version)
        update_testing(args.version, testing_version)
        update_tracing(args.version)
        if args.post_release:
            print(f'{VERSION_FILES["versions_doc"]}: post-release, leaving it alone')
        else:
            update_versions_doc(args.version, released)
    except ValueError as exc:
        print(f'update-release-versions: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
