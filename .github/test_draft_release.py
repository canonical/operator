# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Tests for the two scripts the create-draft-release workflow runs.

pytest does not collect this with the rest of the suite: its default
`norecursedirs` skips dotted directories, so nothing under `.github/` is
found by `tox -e unit`. Run it by naming it:

    uv run --group unit pytest .github/test_draft_release.py

The scripts have hyphens in their names, following the other scripts here,
which means they cannot be imported by name; `load` below does it by path.
"""

from __future__ import annotations

import importlib.util
import pathlib
import re
import types

import pytest

HERE = pathlib.Path(__file__).parent


def load(name: str) -> types.ModuleType:
    """Import one of this directory's scripts by file name."""
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), HERE / f'{name}.py')
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


detect = load('detect-release-bump')
build = load('build-release-body')


def version_file(version: str) -> str:
    """Return an ops/version.py holding this version, as the real one is written."""
    return (
        '"""Package version."""\n\nfrom __future__ import annotations\n\n'
        f'version: str = {version!r}\n'
    )


# The shape the propose-release workflow writes, down to the blank lines
# around the markers. Everything outside them is for the reviewers.
DESCRIPTION = """Prepares the 3.8.3 release from `main`.

* `CHANGES.md` has a new entry for 3.8.3.
* The version strings are updated across ops, ops-scenario, ops-tracing and the
  tool-versions table.
* [Commits since 3.8.2](https://github.com/canonical/operator/compare/3.8.2...main)

The release notes below become the body of the GitHub release. Edit them here: this description is
where they are read from.

<!-- release-notes:start -->

A routine maintenance release: three fixes and a documentation pass.

## Fixes

Duplicate notices are compared by their full event path now.

<!-- release-notes:end -->
"""

PLACEHOLDER_DESCRIPTION = """Prepares the 3.8.3 release from `main`.

<!-- release-notes:start -->

_No release notes were drafted for 3.8.3: no OPENROUTER_API_KEY is configured._

Write them here before merging. They become the body of the GitHub
release, above the changelog entry for this version.

<!-- release-notes:end -->
"""

# Two sections, so that the slice has somewhere to stop. The 3.8.2 entry is
# the one this repository shipped.
CHANGES = """# 3.8.3 - 22 September 2026

## Fixes

* Compare full event paths when skipping duplicate notices ([#2684](https://example.com/2684))

## Documentation

* Give each best-practice admonition a stable anchor ([#2524](https://example.com/2524))

# 3.8.2 - 31 August 2026

## Fixes

* In `ops.testing`, don't pass a message when converting an unknown status by name (#2700)
"""


class TestVersionIn:
    """Reading the version out of an ops/version.py."""

    def test_reads_the_assignment(self):
        """The line the release scripts write is the line this reads back."""
        assert detect.version_in(version_file('3.8.3')) == '3.8.3'

    def test_reads_a_development_version(self):
        """A .devN version is read as it is written, and judged later."""
        assert detect.version_in(version_file('3.9.0.dev0')) == '3.9.0.dev0'

    def test_rejects_a_file_without_one(self):
        """A file with no version line is an error rather than a quiet no."""
        with pytest.raises(ValueError, match=re.escape('ops/version.py')):
            detect.version_in('"""Package version."""\n')


class TestDecide:
    """Deciding whether a push released something."""

    def test_a_release(self):
        """The merge of a version-bump pull request is the case that matters."""
        assert detect.decide('3.9.0.dev0', '3.9.0')[0] == '3.9.0'

    def test_a_patch_release_on_a_maintenance_branch(self):
        """The LTS branch releases the same way, and this does not know the difference."""
        assert detect.decide('2.23.5.dev0', '2.23.6')[0] == '2.23.6'

    def test_a_release_candidate(self):
        """A release candidate is a release: it gets a draft, marked as a pre-release."""
        assert detect.decide('3.9.0.dev0', '3.9.0rc1')[0] == '3.9.0rc1'
        assert detect.is_prerelease('3.9.0rc1')
        assert not detect.is_prerelease('3.9.0')

    def test_the_post_release_bump_is_not_a_release(self):
        """Workflow 3's bump changes the version, and must not draft anything."""
        version, why = detect.decide('3.9.0', '3.10.0.dev0')
        assert version is None
        assert 'development version' in why

    def test_an_unchanged_version_is_not_a_release(self):
        """Nearly every push here: the file was touched, the version was not."""
        assert detect.decide('3.9.0.dev0', '3.9.0.dev0')[0] is None

    def test_a_new_branch_is_not_a_release(self):
        """Nothing to compare against means nothing was released."""
        assert detect.decide(None, '3.9.0')[0] is None

    def test_an_unreleasable_version_is_not_a_release(self):
        """A hand-edited version of some other shape is left alone."""
        version, why = detect.decide('3.9.0.dev0', '3.9')
        assert version is None
        assert 'not a version' in why


class TestMain:
    """The command line, which is what the workflow step actually runs."""

    def test_prints_the_outputs_for_a_release(self, tmp_path: pathlib.Path, capsys):
        """A release prints the two lines the step appends to $GITHUB_OUTPUT."""
        before = tmp_path / 'before.py'
        before.write_text(version_file('3.9.0.dev0'))
        after = tmp_path / 'after.py'
        after.write_text(version_file('3.9.0'))

        assert detect.main(['--before', str(before), '--after', str(after)]) == 0
        assert capsys.readouterr().out == 'version=3.9.0\nprerelease=false\n'

    def test_prints_nothing_for_an_ordinary_merge(self, tmp_path: pathlib.Path, capsys):
        """Doing nothing quietly means no output at all, and success."""
        before = tmp_path / 'before.py'
        before.write_text(version_file('3.9.0.dev0'))

        assert detect.main(['--before', str(before), '--after', str(before)]) == 0
        assert capsys.readouterr().out == ''

    def test_prints_nothing_without_a_before(self, tmp_path: pathlib.Path, capsys):
        """The workflow leaves --before out when the commit is not in the checkout."""
        after = tmp_path / 'after.py'
        after.write_text(version_file('3.9.0'))

        assert detect.main(['--after', str(after)]) == 0
        assert capsys.readouterr().out == ''

    def test_fails_on_a_file_it_cannot_read(self, tmp_path: pathlib.Path):
        """A missing ops/version.py is a broken checkout, not a quiet no."""
        assert detect.main(['--after', str(tmp_path / 'nope.py')]) == 1


class TestReleaseNotes:
    """Lifting the notes back out of the merged pull request's description."""

    def test_takes_what_is_between_the_markers(self):
        """The notes, and none of the text written for the reviewers."""
        notes = build.release_notes(DESCRIPTION)
        assert notes.startswith('A routine maintenance release')
        assert notes.endswith('full event path now.')
        assert 'Prepares the 3.8.3 release' not in notes
        assert 'release-notes:' not in notes

    def test_takes_a_human_edited_body(self):
        """The point of the gate is that somebody rewrote these before merging."""
        edited = DESCRIPTION.replace(
            'A routine maintenance release: three fixes and a documentation pass.',
            'Mostly fixes. If you hit the duplicate-notice bug, this is the release you want.\n\n'
            'Thanks to everyone who reported it.',
        )
        notes = build.release_notes(edited)
        assert notes.startswith('Mostly fixes.')
        assert 'Thanks to everyone who reported it.' in notes

    def test_takes_the_placeholder(self):
        """A merged placeholder is somebody's decision, not a failure."""
        notes = build.release_notes(PLACEHOLDER_DESCRIPTION)
        assert build.is_placeholder(notes)
        assert 'Write them here before merging.' in notes

    def test_ordinary_notes_are_not_the_placeholder(self):
        """The placeholder check does not fire on notes that merely mention it."""
        assert not build.is_placeholder(build.release_notes(DESCRIPTION))

    def test_rejects_a_missing_start_marker(self):
        """Without both markers there is no telling where the notes begin."""
        with pytest.raises(ValueError, match='0 `<!-- release-notes:start -->` markers'):
            build.release_notes(DESCRIPTION.replace('<!-- release-notes:start -->\n\n', ''))

    def test_rejects_a_missing_end_marker(self):
        """The end marker is the one an edit is most likely to take with it."""
        with pytest.raises(ValueError, match='0 `<!-- release-notes:end -->` markers'):
            build.release_notes(DESCRIPTION.replace('\n<!-- release-notes:end -->\n', ''))

    def test_rejects_a_duplicated_marker(self):
        """Two starts, from a copied-in draft, would silently drop half the notes."""
        with pytest.raises(ValueError, match='2 `<!-- release-notes:start -->` markers'):
            build.release_notes(
                DESCRIPTION.replace(
                    'A routine maintenance release',
                    '<!-- release-notes:start -->\n\nA routine maintenance release',
                )
            )

    def test_rejects_markers_in_the_wrong_order(self):
        """An end above a start is not an empty set of notes, it is a mistake."""
        swapped = DESCRIPTION.replace('start -->', 'TEMP -->')
        swapped = swapped.replace('end -->', 'start -->').replace('TEMP -->', 'end -->')
        with pytest.raises(ValueError, match='before it starts'):
            build.release_notes(swapped)

    def test_rejects_empty_notes(self):
        """Somebody deleted the notes rather than editing them."""
        with pytest.raises(ValueError, match='nothing between'):
            build.release_notes(
                'Prepares it.\n\n<!-- release-notes:start -->\n\n<!-- release-notes:end -->\n'
            )

    def test_allows_an_indented_marker(self):
        """A stray space before a marker is not worth failing a release over."""
        assert build.release_notes(DESCRIPTION.replace('<!-- release', '  <!-- release'))


class TestChangelogSection:
    """Slicing this release's entry out of CHANGES.md."""

    def test_takes_the_first_section(self):
        """From its own heading to the previous release's, and no further."""
        section = build.changelog_section(CHANGES, '3.8.3')
        assert section.startswith('# 3.8.3 - 22 September 2026')
        assert '## Documentation' in section
        assert '3.8.2' not in section

    def test_takes_a_changelog_with_one_section(self):
        """A first release has no next heading to stop at."""
        only = '# 1.0.0 - 1 January 2027\n\n## Features\n\n* Everything (#1)\n'
        assert build.changelog_section(only, '1.0.0').endswith('* Everything (#1)')

    def test_ignores_blank_lines_above_the_heading(self):
        """The slice does not depend on the file starting at byte zero."""
        assert build.changelog_section('\n\n' + CHANGES, '3.8.3').startswith('# 3.8.3')

    def test_rejects_a_section_for_another_version(self):
        """The wrong changelog under the right notes is worse than no release."""
        with pytest.raises(ValueError, match=re.escape('first section is for 3.8.3')):
            build.changelog_section(CHANGES, '3.8.4')

    def test_rejects_a_changelog_that_does_not_start_with_a_heading(self):
        """If the file is not the shape we think, the slice would be guesswork."""
        with pytest.raises(ValueError, match='does not start with'):
            build.changelog_section('Changes are listed below.\n\n' + CHANGES, '3.8.3')


class TestReleaseBody:
    """The two halves, put together."""

    def test_notes_first_then_the_changelog(self):
        """What the release is about, and then the complete list."""
        body = build.release_body(
            build.release_notes(DESCRIPTION), build.changelog_section(CHANGES, '3.8.3')
        )
        assert body.startswith('A routine maintenance release')
        assert body.index('## Changelog') > body.index('A routine maintenance release')

    def test_the_changelog_keeps_its_entries_exactly(self):
        """Copied, not regenerated: every line of it survives unchanged."""
        section = build.changelog_section(CHANGES, '3.8.3')
        body = build.release_body('The notes.', section)
        entries = [line for line in section.splitlines() if line.startswith('* ')]
        assert len(entries) == 2
        for entry in entries:
            assert entry in body

    def test_the_headings_are_demoted(self):
        """The release has the version as its title and the notes use `##`."""
        body = build.release_body('The notes.', build.changelog_section(CHANGES, '3.8.3'))
        assert '\n### Fixes\n' in body
        assert '\n## Fixes\n' not in body
        assert '# 3.8.3 - 22 September 2026' not in body

    def test_the_placeholder_goes_in_as_it_stands(self):
        """A release drafted without a model still gets its changelog half."""
        body = build.release_body(
            build.release_notes(PLACEHOLDER_DESCRIPTION),
            build.changelog_section(CHANGES, '3.8.3'),
        )
        assert body.startswith('_No release notes were drafted for 3.8.3')
        assert '### Fixes' in body


class TestBuildMain:
    """The command line, end to end over files."""

    def test_writes_the_body(self, tmp_path: pathlib.Path):
        """What the workflow hands to `gh release create --notes-file`."""
        description = tmp_path / 'pr-description.md'
        description.write_text(DESCRIPTION)
        changes = tmp_path / 'CHANGES.md'
        changes.write_text(CHANGES)
        output = tmp_path / 'release-body.md'

        assert (
            build.main([
                '--version',
                '3.8.3',
                '--description',
                str(description),
                '--changelog',
                str(changes),
                '--output',
                str(output),
            ])
            == 0
        )
        body = output.read_text()
        assert body.startswith('A routine maintenance release')
        assert '### Documentation' in body

    def test_reports_the_placeholder_without_failing(self, tmp_path: pathlib.Path, capsys):
        """A notice in the log, an exit code of 0, and a body that was written."""
        description = tmp_path / 'pr-description.md'
        description.write_text(PLACEHOLDER_DESCRIPTION)
        changes = tmp_path / 'CHANGES.md'
        changes.write_text(CHANGES)
        output = tmp_path / 'release-body.md'

        assert (
            build.main([
                '--version',
                '3.8.3',
                '--description',
                str(description),
                '--changelog',
                str(changes),
                '--output',
                str(output),
            ])
            == 0
        )
        assert '::notice::' in capsys.readouterr().err
        assert output.read_text().startswith('_No release notes were drafted')

    def test_fails_on_a_description_without_markers(self, tmp_path: pathlib.Path, capsys):
        """The one case that stops a release: no notes to publish."""
        description = tmp_path / 'pr-description.md'
        description.write_text('Prepares the 3.8.3 release.\n')
        changes = tmp_path / 'CHANGES.md'
        changes.write_text(CHANGES)

        assert (
            build.main([
                '--version',
                '3.8.3',
                '--description',
                str(description),
                '--changelog',
                str(changes),
                '--output',
                str(tmp_path / 'release-body.md'),
            ])
            == 1
        )
        assert 'markers' in capsys.readouterr().err
