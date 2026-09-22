# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Assemble the body of the draft release, out of two things already written.

Called by the create-draft-release workflow once it knows which version a
merge released and which pull request released it. Neither half of the body
is written here:

- The release notes come out of the merged pull request's description, from
  between the markers the propose-release workflow put there. A human has
  reviewed and probably rewritten them by then - that is what the review is
  for - so they are taken exactly as they stand at merge time, and not
  drafted again.
- The changelog entry is copied out of `CHANGES.md`. The propose-release
  workflow generated it from the commit range and the same human reviewed
  it, so it is copied rather than generated a second time: one source of
  truth, and the file and the release cannot drift apart.

The notes may be the placeholder that the propose-release workflow writes
when it cannot reach a model. That is not an error - somebody merged the
pull request with it in, which is their decision - so it goes into the
draft as it stands, with a line in the log saying so.

    python3 .github/build-release-body.py --version 3.8.3 \
        --description "$RUNNER_TEMP/pr-description.md" \
        --changelog CHANGES.md --output "$RUNNER_TEMP/release-body.md"

Standard library only, so it runs on a runner with nothing installed.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys

# The markers the propose-release workflow wraps the notes in. Each is on a
# line of its own and appears once; anything outside them is for the
# reviewers of that pull request and goes no further.
START = re.compile(r'^[ \t]*<!--\s*release-notes:start\s*-->[ \t]*$', re.MULTILINE)
END = re.compile(r'^[ \t]*<!--\s*release-notes:end\s*-->[ \t]*$', re.MULTILINE)

# The changelog's own section heading, `# 3.8.3 - 22 September 2026`.
SECTION_HEADING = re.compile(r'^# (?P<version>\S+) - (?P<date>.*)$')

# Any Markdown heading, for demoting the changelog's headings a level when
# they go under one of the release body's own. The generated changelog is
# headings and bullets with no code fences in it, so a `#` at the start of a
# line is always a heading.
HEADING = re.compile(r'^(#{1,5} )', re.MULTILINE)

# How .github/draft-release-notes.py starts the body it writes when there
# was no draft. Only a log line hangs off recognising it, so the two drifting
# apart costs nothing.
PLACEHOLDER = re.compile(r'^_No release notes were drafted for \S+:')


def release_notes(description: str) -> str:
    """Return the release notes from between the markers in a description.

    Anything other than one start marker and one end marker after it is an
    error: the notes are the half of the release body a human wrote, and
    guessing at where they begin would be guessing at what gets published.
    """
    starts = list(START.finditer(description))
    ends = list(END.finditer(description))
    for markers, name in ((starts, 'start'), (ends, 'end')):
        if len(markers) != 1:
            raise ValueError(
                f'the description has {len(markers)} `<!-- release-notes:{name} -->` markers,'
                ' and needs exactly one'
            )
    if ends[0].start() < starts[0].end():
        raise ValueError('the description ends the release notes before it starts them')
    notes = description[starts[0].end() : ends[0].start()].strip()
    if not notes:
        raise ValueError('there is nothing between the release-notes markers')
    return notes


def is_placeholder(notes: str) -> bool:
    """Return whether these notes are the "nobody drafted any" placeholder."""
    return bool(PLACEHOLDER.match(notes.strip()))


def changelog_section(changes: str, version: str) -> str:
    """Return the first section of CHANGES.md, checked against the version.

    The first section is the release being made: the propose-release
    workflow prepends it. It runs from its `# <version> - <date>` heading to
    the next `# ` heading, which is the previous release.
    """
    lines = changes.splitlines()
    first = next((i for i, line in enumerate(lines) if line.strip()), None)
    heading = SECTION_HEADING.match(lines[first]) if first is not None else None
    if not heading:
        raise ValueError('the changelog does not start with a `# <version> - <date>` heading')
    if heading.group('version') != version:
        raise ValueError(
            f"the changelog's first section is for {heading.group('version')},"
            f' but {version} is being released'
        )
    end = next(
        (i for i, line in enumerate(lines[first + 1 :], first + 1) if line.startswith('# ')),
        len(lines),
    )
    return '\n'.join(lines[first:end]).strip()


def release_body(notes: str, section: str) -> str:
    """Return the notes and the changelog section, as the release body.

    The notes come first and the changelog under them, which is the order
    they are read in: what this release is about, and then the complete
    list. The section keeps its own text exactly, and only its headings
    move: it arrives with a `# <version> - <date>` heading that the release
    already has as its title, and `## Category` headings that would outrank
    the `##` the notes are written in.
    """
    entries = HEADING.sub(r'#\1', '\n'.join(section.splitlines()[1:]).strip())
    return f'{notes.strip()}\n\n---\n\n## Changelog\n\n{entries}\n'


def main(argv: list[str] | None = None) -> int:
    """Write the release body, or say what is wrong with what it is made of."""
    parser = argparse.ArgumentParser(description='Assemble the body of a draft release.')
    parser.add_argument('--version', required=True, metavar='X.Y.Z')
    parser.add_argument(
        '--description',
        required=True,
        metavar='PATH',
        help="The merged pull request's description, with the notes in it.",
    )
    parser.add_argument(
        '--changelog',
        default='CHANGES.md',
        metavar='PATH',
        help='The changelog, whose first section is this release.',
    )
    parser.add_argument('--output', required=True, metavar='PATH', help='Where to write the body.')
    args = parser.parse_args(argv)

    try:
        notes = release_notes(pathlib.Path(args.description).read_text())
        section = changelog_section(pathlib.Path(args.changelog).read_text(), args.version)
    except (OSError, ValueError) as exc:
        print(f'build-release-body: {exc}', file=sys.stderr)
        return 1

    if is_placeholder(notes):
        print(
            f'::notice::The {args.version} pull request was merged with the release-notes'
            ' placeholder in it, so the draft carries that instead of notes.',
            file=sys.stderr,
        )

    body = release_body(notes, section)
    pathlib.Path(args.output).write_text(body)
    print(f'{args.output}: {len(body)} characters.', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
