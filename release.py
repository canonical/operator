# Copyright 2025 Canonical Ltd.
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

"""Release automation script."""

from __future__ import annotations

import argparse
import datetime
import logging
import os
import pathlib
import re
import subprocess
import sys
from collections.abc import Mapping

import github
import github.GitRelease
import github.Repository
import packaging.version
import rich.logging
import tomllib

logging.basicConfig(
    level=logging.INFO, format='%(message)s', handlers=[rich.logging.RichHandler()]
)
logger = logging.getLogger('release')

if 'GITHUB_TOKEN' not in os.environ:
    raise SystemExit('Environment variable GITHUB_TOKEN not set.')

auth = github.Auth.Token(os.environ['GITHUB_TOKEN'])
gh_client = github.Github(auth=auth)


VERSION_REGEX = r'(\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?(?:\.dev\d+)?)'
VERSION_FILES = {
    'ops/src': pathlib.Path('ops/version.py'),
    'ops/pyproject': pathlib.Path('pyproject.toml'),
    'testing': pathlib.Path('testing/pyproject.toml'),
    'tracing': pathlib.Path('tracing/pyproject.toml'),
    'uvlock': pathlib.Path('uv.lock'),
    'versions_doc': pathlib.Path('docs/explanation/versions.md'),
}
CHANGE_LINE_REGEX = (
    r'^\* (?P<category>\w+)(?P<breaking>!?): (?P<summary>.*) by [^ ]+ in (?P<pr>.*)'
)


def get_current_ops_version() -> packaging.version.Version:
    """Get the current ops version from ops/version.py."""
    content = VERSION_FILES['ops/src'].read_text()
    match = re.search(rf"version: str = '{VERSION_REGEX}'", content)
    if not match:
        raise ValueError('Could not find version string in ops/version.py')
    return packaging.version.Version(match.group(1))


def bump_minor_version(version: str) -> str:
    """Bump minor version."""
    major, minor, _ = map(int, version.split('.'))
    return f'{major}.{minor + 1}.0'


def bump_patch_version(version: str) -> str:
    """Bump patch version."""
    major, minor, patch = map(int, version.split('.'))
    return f'{major}.{minor}.{patch + 1}'


def get_new_tag_for_release(owner: str, repo_name: str, branch_name: str) -> str:
    """Get a new tag for release.

    Suggests a version based on the current version in source files:
    - For maintenance branches: bump the patch version
    - For pre-releases (a/b/rc): suggest the base version (the final release)
    - For dev versions: drop the .devN suffix
    - For final releases: bump the minor version

    Can be overridden with a user-provided version.
    """
    current_version = get_current_ops_version()
    logger.info('Current version in source: %s', current_version)

    base_version = current_version.base_version
    suggested_tag = ''

    if current_version.pre or current_version.dev:
        logger.info('Dropping pre-release qualifiers and suggesting base version.')
        suggested_tag = base_version
    elif branch_name.endswith('-maintenance'):
        logger.info('Bumping patch version since this is a maintenance branch.')
        suggested_tag = bump_patch_version(base_version)
    else:
        logger.info('Bumping minor version.')
        suggested_tag = bump_minor_version(base_version)

    logger.info('Suggested new version: %s', suggested_tag)

    tag_prompt = f' (press enter to use the tag {suggested_tag})' if suggested_tag else ''
    prompt = f'\033[1mInput the new tag for the release{tag_prompt}:\n> \033[0m'
    while True:
        user_input = input(prompt).strip()

        new_tag = user_input or suggested_tag

        if not new_tag:
            logger.error('No tag specified and no suggestion available')
            continue

        if not re.match(r'^\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?$', new_tag):
            logger.error('Tag must be in format X.Y.Z or X.Y.Z{a|b|rc}N')
            continue

        release_page = f'https://github.com/{owner}/{repo_name}/releases'
        logger.warning('Check out the releases page: %s before confirming!', release_page)

        confirm = (
            input(
                f'\033[1mConfirm creating tag {new_tag!r} on branch {branch_name!r}? '
                f'[y/N]: \n> \033[0m'
            )
            .strip()
            .lower()
        )

        if confirm == 'y':
            break

        logger.info("Let's try again...")

    return new_tag


def create_draft_release(
    repo: github.Repository.Repository, tag: str, branch: str
) -> github.GitRelease.GitRelease | None:
    """Create a draft release with auto-generated notes."""
    release = repo.create_git_release(
        tag=tag,
        name=tag,
        draft=True,
        generate_release_notes=True,
        target_commitish=branch,
    )
    return release


def parse_release_notes(release_notes: str) -> tuple[dict[str, list[tuple[str, str]]], str | None]:
    """Parse auto-generated release notes into categories.

    The "New Contributors" section is removed.
    The PRs are categorised by the conventional commit type.
    The full changelog line is returned separately.

    Returns:
        A tuple containing:
        - A dict with conventional commit types as keys and lists of tuples (description, PR link)
          as values.
        - The full changelog line if present, or ``None`` if not found.
    """
    release_notes = re.sub(
        r'(## New Contributors.*?)(\n|$)', r'\2', release_notes, flags=re.DOTALL
    )
    categories: Mapping[str, list[tuple[str, str]]] = {
        'breaking': [],  # a meta category for breaking changes
        'feat': [],
        'fix': [],
        'docs': [],
        'test': [],
        'refactor': [],
        'perf': [],
        'ci': [],
        'revert': [],
    }
    full_changelog_line = None

    for line in release_notes.splitlines():
        if match := re.match(CHANGE_LINE_REGEX, line.strip()):
            category = match.group('category').strip()
            if category in categories:
                description = match.group('summary').strip()
                description = description[0].upper() + description[1:]
                pr_link = match.group('pr').strip()
                if match.group('breaking') == '!':
                    categories['breaking'].append((
                        f'{category.capitalize()}: {description}',
                        pr_link,
                    ))
                else:
                    categories[category].append((description, pr_link))

        elif line.startswith('**Full Changelog**'):
            full_changelog_line = line

    return categories, full_changelog_line


def format_release_notes(
    categories: Mapping[str, list[tuple[str, str]]], full_changelog: str | None
) -> str:
    """Format for release notes.

    Results in a Markdown formatted string with sections for each commit type.
    If `full_changelog` is provided, it is appended at the end.
    """
    lines = ["## What's Changed", '']
    if categories['breaking']:
        lines.append('### Breaking Changes')
        lines.append('There are breaking changes in this release. Please review them carefully:\n')
        for description, pr_link in categories['breaking']:
            lines.append(f'* {description} in {pr_link}')
        lines.append('')
        logger.info(
            'Breaking changes detected in the release notes. '
            'Please ensure there are sufficient instructions for users to handle them.'
        )
    for commit_type, items in categories.items():
        if commit_type == 'breaking':
            continue
        if items:
            lines.append(f'### {commit_type_to_category(commit_type)}')
            for description, pr_link in items:
                lines.append(f'* {description} in {pr_link}')
            lines.append('')
    if full_changelog:
        lines.append(full_changelog)
    return '\n'.join(lines)


def print_release_notes(notes: str):
    """Print formatted release notes.

    So that user can review them and use them to write the title and summary.
    """
    sys.stdout.flush()
    sys.stderr.flush()
    print('=' * 80)
    print('Formatted release notes:')
    print('=' * 80)
    print(notes)
    print('=' * 80)


def input_title_and_summary(release: github.GitRelease.GitRelease) -> tuple[str, str]:
    """Ask user to input the release title and summary."""
    logger.info('The automatically generated title is: %s', release.title)
    title = input(
        '\033[1mEnter release title, press Enter to keep the auto-generated title:\n> \033[0m'
    ).strip()
    if not title:
        title = release.title

    print(
        '\n\033[1mEnter release summary (multi-line supported; type "." on a new line '
        'to finish):\n> \033[0m'
    )

    lines: list[str] = []
    while True:
        line = input()
        if line.strip() == '.':
            break
        lines.append(line)

    summary = '\n'.join(lines).strip() + '\n'

    return title, summary


def update_draft_release(release: github.GitRelease.GitRelease, title: str, notes: str):
    """Update the release with the provided title and notes."""
    release = release.update_release(name=title, message=notes, draft=True)
    logger.info('Release updated: %s', release.html_url)


def format_changes(categories: Mapping[str, list[tuple[str, str]]], tag: str) -> str:
    """Format for CHANGES.md.

    The header is formatted as a top-level heading with the tag and date.
    The content is a Markdown formatted string with sections for each commit type.
    Each item is formatted as a bullet point with the description and PR number in parentheses.
    """
    today = datetime.datetime.now().strftime('%d %B %Y')
    lines = [f'# {tag} - {today}\n']
    for commit_type, items in categories.items():
        if items:
            lines.append(f'## {commit_type_to_category(commit_type)}\n')
            for description, pr_link in items:
                pr_num = '?'
                match = re.match(r'https?://[^ ]+/pull/(\d+)', pr_link)
                if match:
                    pr_num = match.group(1)
                lines.append(f'* {description} (#{pr_num})')
            lines.append('')
    return '\n'.join(lines) + '\n'


def update_changes_file(changes: str, file: str):
    """Update the changes file with new release notes."""
    file_path = pathlib.Path(file)
    existing_content = file_path.read_text() if file_path.exists() else ''
    file_path.write_text(changes + existing_content)
    logger.info('Updated %s with new release notes.', file)


def commit_type_to_category(commit_type: str) -> str:
    """Map commit type to a human-readable category.

    If the commit type is not recognized, it returns the capitalized commit type.
    """
    mapping = {
        'feat': 'Features',
        'fix': 'Fixes',
        'docs': 'Documentation',
        'test': 'Tests',
        'ci': 'CI',
        'perf': 'Performance',
        'refactor': 'Refactoring',
        'revert': 'Reverted',
        'breaking': 'Breaking Changes',
    }
    return mapping.get(commit_type, commit_type.capitalize())


def update_pyproject_versions(path: pathlib.Path, version: str, deps: dict[str, str]) -> None:
    """Update versions in pyproject.toml."""
    content = path.read_text()
    updated = re.sub(rf'version = "{VERSION_REGEX}"', f'version = "{version}"', content)
    for pkg, pkg_version in deps.items():
        updated = re.sub(rf'{pkg}=={VERSION_REGEX}', f'{pkg}=={pkg_version}', updated)
    if content == updated:
        logger.error('No changes made to %s. Check the versions.', path)
        exit(1)
    path.write_text(updated)
    logger.info('Updated %s to version %s', path, version)


def update_ops_version(ops_version: str, testing_version: str):
    """Update the ops version in version.py and pyproject.toml."""
    # version.py
    ops_src_file_path = VERSION_FILES['ops/src']
    content = ops_src_file_path.read_text()
    updated = re.sub(
        rf"^version: str = '{VERSION_REGEX}'$",
        f"version: str = '{ops_version}'",
        content,
        flags=re.MULTILINE,
    )
    ops_src_file_path.write_text(updated)
    logger.info('Updated %s to version %s', ops_src_file_path, ops_version)

    # pyproject.toml, update both ops-scenario and ops-tracing versions.
    update_pyproject_versions(
        VERSION_FILES['ops/pyproject'],
        testing_version,
        deps={'ops-scenario': testing_version, 'ops-tracing': ops_version},
    )


def update_testing_version(ops_version: str, testing_version: str):
    """Update the testing pyproject version."""
    update_pyproject_versions(VERSION_FILES['testing'], testing_version, deps={'ops': ops_version})


def update_tracing_version(ops_version: str):
    """Update the tracing pyproject version."""
    update_pyproject_versions(VERSION_FILES['tracing'], ops_version, deps={'ops': ops_version})


def update_versions_doc(version: str):
    """Update the Ops version table in docs/explanation/versions.md.

    Updates the row for the current major version with:
    - The new major.minor version
    - Today's date as the release date
    - One year from today as the end of life date
    """
    parsed_version = packaging.version.Version(version)
    major, minor, _ = parsed_version.release
    major_minor = f'{major}.{minor}'

    today = datetime.date.today()
    release_date = today.strftime('%Y-%m-%d')

    # Calculate end of life (one year from today)
    # Handle Feb 29 -> Mar 1 for non-leap years
    try:
        eol_date = today.replace(year=today.year + 1)
    except ValueError:
        # Feb 29 in a leap year -> Mar 1 in non-leap year
        eol_date = datetime.date(today.year + 1, 3, 1)

    eol_date_str = eol_date.strftime('%Y-%m-%d')

    versions_doc_path = VERSION_FILES['versions_doc']
    if not versions_doc_path.exists():
        logger.info('Skipping version doc update: doc does not exist')
        return
    content = versions_doc_path.read_text()

    # Find and replace the Ops major version row
    # Pattern matches: | Ops X.Y | status | date | date |
    pattern = rf'(\| Ops {major})\.\d+ (\| [^|]+ \|) [^|]+ \| [^|]+ \|'
    replacement = rf'\1.{minor} \2 {release_date} | {eol_date_str} |'

    updated = re.sub(pattern, replacement, content)

    if content == updated:
        logger.error('No changes made to %s. Check the Ops version row.', versions_doc_path)
        exit(1)

    versions_doc_path.write_text(updated)
    logger.info(
        'Updated %s: Ops %s with release date %s and EOL %s',
        versions_doc_path,
        major_minor,
        release_date,
        eol_date_str,
    )


def update_uv_lock():
    """Update the uv.lock file with the new versions."""
    subprocess.run(['uv', 'lock'], check=True)  # noqa: S607


def get_scenario_version() -> packaging.version.Version:
    """Get the current scenario version from pyproject.toml."""
    pyproject_toml = tomllib.loads(VERSION_FILES['testing'].read_text())
    return packaging.version.Version(pyproject_toml['project']['version'])


def get_new_scenario_version(ops_version: str) -> str:
    """Get a new version for scenario based on ops version.

    We want the scenario version to always be exactly ops major version+5,
    like ops 3.1.2 -> scenario 8.1.2, and ops 3.1.2.dev0 -> scenario 8.1.2.dev0.
    Pre-release versions are also preserved, like ops 3.1.2b1 -> scenario 8.1.2b1.
    """
    version = packaging.version.Version(ops_version)
    major, minor, patch = version.release
    new_version = f'{major + 5}.{minor}.{patch}'
    if version.pre is not None:  # then it's in the form ('a', 0)
        new_version += f'{version.pre[0]}{version.pre[1]}'
    if version.dev is not None:  # then it's the dev version number
        new_version += f'.dev{version.dev}'
    return new_version


def update_versions_for_release(tag: str):
    """Update version files to the specified release version."""
    scenario_version = get_new_scenario_version(tag)
    update_ops_version(tag, scenario_version)
    update_testing_version(tag, scenario_version)
    update_tracing_version(tag)
    update_versions_doc(tag)
    update_uv_lock()


def get_new_version_post_release(branch_name: str) -> str:
    """Get the new version after the release.

    Based on the current version in source files:
    - For pre-releases (alpha, beta, rc): use base version + .dev0
    - For maintenance branches: bump patch version + .dev0
    - Otherwise: bump minor version + .dev0
    """
    current_version = get_current_ops_version()
    logger.info('Current version in source: %s', current_version)

    base_version = current_version.base_version

    # For pre-releases (alpha, beta, rc), use base version + .dev0
    # For final releases, bump the version and add .dev0
    if current_version.pre is not None:
        logger.info('Current version is a pre-release, using base version for next dev version.')
        new_version = base_version + '.dev0'
    elif branch_name.endswith('-maintenance'):
        logger.info('Branch is a maintenance branch, bumping patch version.')
        new_version = bump_patch_version(base_version) + '.dev0'
    else:
        logger.info('Branch is main, bumping minor version.')
        new_version = bump_minor_version(base_version) + '.dev0'

    logger.info('Suggested new version: %s', new_version)
    return new_version


def update_versions_for_post_release(branch_name: str):
    """Update version files to the post-release version with '.dev0' suffix."""
    ops_version = get_new_version_post_release(branch_name)
    scenario_version = get_new_scenario_version(ops_version)
    update_ops_version(ops_version, scenario_version)
    update_testing_version(ops_version, scenario_version)
    update_tracing_version(ops_version)
    update_uv_lock()


def check_update_charm_pins_prs(repo: github.Repository.Repository):
    """Check for open PRs that update charm pins."""
    prs = repo.get_pulls(state='open')
    open_prs = [pr for pr in prs if pr.title == 'chore: update charm pins']
    if open_prs:
        logger.info('Please merge "update charm pins" PRs first:')
        pr = open_prs[0]
        pr_url = f'#{pr.number} - {pr.html_url}'
        logger.info('  %s', pr_url)
        if len(open_prs) > 1:
            logger.info(
                'Note that there are %s more open update charm pins PRs.', len(open_prs) - 1
            )
            exit(1)


def draft_release(
    owner: str, repo_name: str, base_branch: str, canonical_remote: str, fork_remote: str
):
    """Create a draft release, update changelog, and create a PR for the release."""
    local_branch = subprocess.check_output(['/usr/bin/git', 'branch', '--list', base_branch])
    if local_branch:
        subprocess.run(['/usr/bin/git', 'checkout', base_branch], check=True)
        subprocess.run(['/usr/bin/git', 'pull', canonical_remote, base_branch], check=True)
    else:
        subprocess.run(['/usr/bin/git', 'fetch', canonical_remote], check=True)
        subprocess.run(
            ['/usr/bin/git', 'checkout', '--track', f'{canonical_remote}/{base_branch}'],
            check=True,
        )

    org = gh_client.get_organization(owner)
    repo = org.get_repo(repo_name)

    check_update_charm_pins_prs(repo)

    tag = get_new_tag_for_release(owner, repo_name, base_branch)
    release = create_draft_release(repo, tag, base_branch)
    if not release:
        logger.error('Failed to create draft release.')
        exit(1)
    logger.info('Draft release created: %s', release.html_url)

    categories, full_changelog = parse_release_notes(release.body)
    notes = format_release_notes(categories, full_changelog)
    print_release_notes(notes)

    title, summary = input_title_and_summary(release)
    if not title:
        title = tag
    notes = f'{summary}\n{notes}'

    update_draft_release(release, title, notes)

    changes = format_changes(categories, tag)
    update_changes_file(changes, 'CHANGES.md')

    update_versions_for_release(tag)

    new_branch = f'release-prep-{tag}'
    subprocess.run(['/usr/bin/git', 'checkout', '-b', new_branch], check=True)
    changed_files = [
        'CHANGES.md',
        *[str(path) for path in VERSION_FILES.values() if path.exists()],
    ]
    subprocess.run(['/usr/bin/git', 'add', *changed_files], check=True)
    subprocess.run(['/usr/bin/git', 'commit', '-m', f'chore: prepare release {tag}'], check=True)
    subprocess.run(['/usr/bin/git', 'push', fork_remote, new_branch], check=True)
    pr = repo.create_pull(
        title=f'chore: update changelog and versions for {tag} release',
        body=f'This PR prepares the release of version {tag}.',
        head=f'{gh_client.get_user().login}:{new_branch}',  # "your_username:new_branch"
        base=base_branch,
    )
    logger.info('Created PR: %s', pr.html_url)


def post_release(
    owner: str, repo_name: str, base_branch: str, canonical_remote: str, fork_remote: str
):
    """Post-release actions: update version files and create a PR."""
    # Get current version for branch naming
    current_version = get_current_ops_version()
    new_branch = f'post-release-{current_version}'
    local_branch = subprocess.check_output(['/usr/bin/git', 'branch', '--list', new_branch])
    remote_branch = subprocess.check_output([
        '/usr/bin/git',
        'ls-remote',
        '--heads',
        fork_remote,
        new_branch,
    ])
    if local_branch or remote_branch:
        logger.error(
            'Branch %r already exists. '
            'Please double check and delete it first before post release',
            new_branch,
        )
        exit(1)

    subprocess.run(['/usr/bin/git', 'checkout', base_branch], check=True)
    subprocess.run(['/usr/bin/git', 'pull', canonical_remote, base_branch], check=True)

    org = gh_client.get_organization(owner)
    repo = org.get_repo(repo_name)

    update_versions_for_post_release(base_branch)

    subprocess.run(['/usr/bin/git', 'checkout', '-b', new_branch], check=True)
    files = [str(path) for path in VERSION_FILES.values() if path.exists()]
    subprocess.run(['/usr/bin/git', 'add', *files], check=True)
    subprocess.run(
        ['/usr/bin/git', 'commit', '-m', 'chore: update versions after release'], check=True
    )
    subprocess.run(['/usr/bin/git', 'push', fork_remote, new_branch], check=True)
    pr = repo.create_pull(
        title='chore: adjust versions after release',
        body='This PR updates the version files after the release.',
        head=f'{gh_client.get_user().login}:{new_branch}',  # "your_username:new_branch"
        base=base_branch,
    )
    logger.info('Created PR: %s', pr.html_url)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--repo',
        '-r',
        help='Repository name (e.g. "operator")',
        default='operator',
    )
    parser.add_argument(
        '--owner',
        '-o',
        help='Owner name (e.g. "canonical")',
        default='canonical',
    )
    parser.add_argument(
        '--canonical-remote',
        '-c',
        help='Remote name of canonical/operator (e.g. "upstream")',
        default='upstream',
    )
    parser.add_argument(
        '--fork-remote',
        '-f',
        help='Remote name of the forked operator repo (e.g. "origin")',
        default='origin',
    )
    parser.add_argument('--branch', '-b', help='Branch to create the release from', default='main')
    parser.add_argument(
        '--post-release',
        action='store_true',
        help='After release, bump version and add .dev0 suffix',
    )
    args = parser.parse_args()

    if args.post_release:
        post_release(
            owner=args.owner,
            repo_name=args.repo,
            base_branch=args.branch,
            canonical_remote=args.canonical_remote,
            fork_remote=args.fork_remote,
        )
        logger.info(
            'Post-release actions completed. Please check and merge the created PR '
            'for version updates.'
        )
        exit(0)

    draft_release(
        owner=args.owner,
        repo_name=args.repo,
        base_branch=args.branch,
        canonical_remote=args.canonical_remote,
        fork_remote=args.fork_remote,
    )
    logger.info(
        'Draft release created. Please merge the version bump PR, review and publish the draft '
        'release, then run this script with --post-release to perform post-release actions.'
    )
