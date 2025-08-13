#! /usr/bin/env python3

# Copyright 2025 Canonical Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Open a PR to update the best practices reference doc with the latest practices."""

import argparse
import pathlib
import re

BEST_PRACTICE_RE_MD = re.compile(
    r'```{admonition} Best practice\s*(?:.*?\n)?([\s\S]*?)```',
    re.MULTILINE,
)
BEST_PRACTICE_RE_REST = re.compile(
    r'^\.\. admonition:: Best practice\s*\n\s*:class: hint\s*\n\s*\n([\s\S]*?)(?=\n\.\. |\n\n|\Z)',
    re.MULTILINE,
)


def extract_best_practice_blocks(file_path: pathlib.Path):
    """Extracts 'Best practice' blocks from a file."""
    remove_pattern: str | None = None
    matches: list[str] = []
    content = file_path.read_text()
    if file_path.suffix == '.md':
        matches = BEST_PRACTICE_RE_MD.findall(content)
        remove_pattern = r'^:class: hint\s*\n'
    elif file_path.suffix == '.rst':
        matches = BEST_PRACTICE_RE_REST.findall(content)
        remove_pattern = r'^\s+'
    assert remove_pattern is not None, 'Unsupported file type for best practices extraction.'
    if not matches:
        return matches
    return [
        re.sub(remove_pattern, '', match, flags=re.MULTILINE).strip().replace('\n', ' ')
        for match in matches
    ]


def find_best_practices(path_to_ops: pathlib.Path, path_to_charmcraft: pathlib.Path):
    """Recursively located best practice blocks in Ops and Charmcraft."""
    checklist: list[tuple[pathlib.Path, str]] = []
    for directory, base_url in (
        (path_to_ops, 'https://documentation.ubuntu.com/ops/latest/'),
        (path_to_charmcraft, 'https://documentation.ubuntu.com/charmcraft/stable/'),
    ):
        for file_path in directory.rglob('*'):
            if file_path.suffix in ('.md', '.rst'):
                practices = extract_best_practice_blocks(file_path)
                # TODO: It would be even nicer if we found the closest reference link rather than
                # just the file path.
                link = f'{base_url}{file_path.relative_to(directory).with_suffix("")}/'
                checklist.extend((link, practice) for practice in practices)
    return checklist


def main():
    """Extract the best practices, update the doc, and open a PR."""
    parser = argparse.ArgumentParser(
        description='Open a pull request to update the list of best practices.'
    )
    parser.add_argument(
        '--path-to-ops',
        type=pathlib.Path,
        default=pathlib.Path(__file__).parent.parent / 'operator',
        help='Path to a clone of canonical/operator',
    )
    parser.add_argument(
        '--path-to-charmcraft',
        type=pathlib.Path,
        default=pathlib.Path(__file__).parent.parent / 'charmcraft',
        help='Path to a clone of canonical/charmcraft',
    )
    args = parser.parse_args()
    practices = find_best_practices(args.path_to_ops / 'docs', args.path_to_charmcraft / 'docs')
    for link, practice in practices:
        print(f'- {practice.strip()} [See more]({link}).')


if __name__ == '__main__':
    main()
