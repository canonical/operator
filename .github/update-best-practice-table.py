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

"""Update the best practices reference doc with the latest practices.

Given clones of the repositories in the charming ecosystem that contain best
practice notes (in the standard format, in either Markdown or reStructuredText
files), find all the best practice blocks (and the heading and reference that is
associated with them) and produce a suitable block of Markdown to include in the
Ops documentation.

## Local Usage

You'll need a clone of the `operator` repository (presumably the one you're running this command
from), and also the [canonical/charmcraft](https://github.com/canonical/charmcraft) repository,
ideally checked out to the main branch at HEAD.

```command
python3 .github/update-best-practice-table.py \
    --path-to-charmcraft=../charmcraft > docs/reuse/best-practices.txt

# Check the modifications in the current branch.
git diff
```
"""

import argparse
import pathlib
import re


def extract_best_practice_blocks_rst(file_path: pathlib.Path, content: str):
    """Extracts 'Best practice' blocks from a ReST file.

    Returns a tuple of (heading, reference, content).
    """
    lines = content.splitlines()
    results: list[tuple[str | None, str | None, str]] = []

    current_heading = None
    current_ref = None
    previous_line = ''
    inside_admonition = False
    admonition_lines: list[str] = []

    for line in lines:
        if line.strip() == ':class: hint':
            continue

        rst_match = re.match(r'^[-=]{3,}$', line.strip())
        if rst_match and previous_line.strip():
            current_heading = previous_line.strip()
            previous_line = line
            continue

        if inside_admonition:
            at_end = previous_line.strip() == '' and len(line) > 0 and line[0] != ' '
            if at_end:
                results.append((current_heading, current_ref, '\n'.join(admonition_lines)))
                inside_admonition = False
            else:
                admonition_lines.append(line)

        if re.match(r'^\.\. admonition:: Best practice', line):
            inside_admonition = True
            admonition_lines.clear()
            previous_line = line
            continue

        ref_match = re.match(r'.. _(.+?):', line)
        if ref_match:
            current_ref = ref_match.group(1)
            continue

        previous_line = line

    results.sort()
    return results


def extract_best_practice_blocks_md(file_path: pathlib.Path, content: str):
    """Extracts 'Best practice' blocks from a Markdown file.

    Returns a tuple of (heading, reference, content).
    """
    lines = content.splitlines()
    results: list[tuple[str | None, str | None, str]] = []

    current_heading = None
    current_ref = None
    inside_admonition = False
    admonition_lines: list[str] = []

    for line in lines:
        if line.strip() == ':class: hint':
            continue

        md_match = re.match(r'^(#{2,})\s+(.*)', line)
        if md_match:
            current_heading = md_match.group(2)
            continue

        if inside_admonition:
            at_end = line.strip() == '```'
            if at_end:
                results.append((current_heading, current_ref, '\n'.join(admonition_lines)))
                inside_admonition = False
            else:
                admonition_lines.append(line)

        if re.match(r'^```{admonition} Best practice', line):
            inside_admonition = True
            admonition_lines.clear()
            continue

        ref_match = re.match(r'\((.+?)\)=', line)
        if ref_match:
            current_ref = ref_match.group(1)
            continue

    results.sort()
    return results


def make_ops_ref(heading: str, raw: str):
    """Turn the raw reference into a link."""
    return f'[{heading}](#{raw})'


def make_charmcraft_ref(heading: str, raw: str):
    """Turn the charmcraft reference into an external intersphinx link."""
    return f'{{external+charmcraft:ref}}`{heading.replace("`", "")} <{raw}>`'


def main():
    """Extract the best practices, update the doc, and open a PR."""
    parser = argparse.ArgumentParser(
        description='Open a pull request to update the list of best practices. '
        'Run in a clone of the operator repository.'
    )
    parser.add_argument(
        '--path-to-charmcraft',
        type=pathlib.Path,
        required=True,
        help='Path to a clone of canonical/charmcraft',
    )
    args = parser.parse_args()
    path_to_ops = pathlib.Path(__file__).parent.parent
    for directory, base_url, make_ref, ref_sub in (
        (path_to_ops / 'docs', 'https://documentation.ubuntu.com/ops/latest/', make_ops_ref, None),
        (
            args.path_to_charmcraft / 'docs',
            'https://documentation.ubuntu.com/charmcraft/latest/',
            make_charmcraft_ref,
            '{external+charmcraft:ref}',
        ),
    ):
        for file_path in directory.rglob('*'):
            if file_path.suffix not in ('.md', '.rst'):
                continue
            text = file_path.read_text()
            # Get the title of the page. This will be the first heading in the file.
            if file_path.suffix == '.md':
                mo = re.search(r'^#\s+?(.*)', text, re.MULTILINE)
                if not mo:
                    continue
                title = mo.group(1).strip()
                practices = extract_best_practice_blocks_md(file_path, text)
            else:  # file_path.suffix == '.rst':
                mo = re.search(r'^(.+?)\n[-=]+\n', text, re.MULTILINE)
                if not mo:
                    continue
                title = mo.group(1).strip()
                practices = extract_best_practice_blocks_rst(file_path, text)
            link = f'{base_url}{file_path.relative_to(directory).with_suffix("")}/'
            if len(practices):
                print(f'**[{title}]({link})**')
            for heading, ref, practice in practices:
                ref = make_ref(heading, ref) if ref and heading else ref
                see_more = f' See {ref}.' if heading and ref else ''
                practice = re.sub(r'\s+', ' ', practice).strip()
                if ref_sub:
                    practice = re.sub(r':ref:', ref_sub, practice)
                print(f'- {practice}{see_more}')
            if len(practices):
                print()


if __name__ == '__main__':
    main()
