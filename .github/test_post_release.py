# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Tests for the scripts the post-release workflow runs.

pytest does not collect this with the rest of the suite: its default
`norecursedirs` skips dotted directories, so nothing under `.github/` is
found by `tox -e unit`. Run it by naming it:

    uv run --group unit pytest .github/test_post_release.py

The scripts have hyphens in their names, following the other scripts here,
which means they cannot be imported by name; `load` below does it by path.
"""

from __future__ import annotations

import importlib.util
import pathlib
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


post_release = load('post-release-version')
update = load('update-release-versions')


class TestNextDevVersion:
    """The arithmetic, which is release.py's get_new_version_post_release."""

    @pytest.mark.parametrize(
        ('released', 'expected'),
        [
            # Every one of these really happened, and the version on the
            # right is the one the post-release bump really wrote. Taken from
            # canonical/operator's own history of ops/version.py.
            ('3.8.2', '3.9.0.dev0'),  # 0d7fbd21 released, 7c24231c bumped
            ('3.8.1', '3.9.0.dev0'),  # 1fdae240 released, 04c05249 bumped
            ('3.8.0', '3.9.0.dev0'),  # c9ece861 released, 594d6d93 bumped
            ('3.4.0', '3.5.0.dev0'),  # 63136b67 released, a9508406 bumped
        ],
    )
    def test_real_releases_from_main(self, released: str, expected: str):
        """Four real releases from `main`, against the bump each one really got."""
        assert post_release.next_dev_version(released, 'main') == expected

    @pytest.mark.parametrize(
        ('released', 'expected'),
        [
            # The same, on the LTS branch, where the bump is a patch.
            ('2.23.5', '2.23.6.dev0'),  # 938e064b released, 798cadc5 bumped
            ('2.23.4', '2.23.5.dev0'),  # 36d9b0da released, c4fcdf7c bumped
            ('2.23.2', '2.23.3.dev0'),  # ad4a455c released, 46d87a41 bumped
        ],
    )
    def test_real_releases_from_the_lts_branch(self, released: str, expected: str):
        """Three real releases from 2.23-maintenance, where the patch moves."""
        assert post_release.next_dev_version(released, '2.23-maintenance') == expected

    @pytest.mark.parametrize(
        ('released', 'expected'),
        [
            # 17cc70ad cut 3.4.0b3 and 1224f105 bumped to 3.4.0.dev0;
            # 2a6c59bf cut 3.4.0b1 and 0d7abe9b bumped to the same thing.
            ('3.4.0b3', '3.4.0.dev0'),
            ('3.4.0b1', '3.4.0.dev0'),
            # The other two shapes this repository accepts, by construction:
            # there is no alpha or release candidate in the history.
            ('3.4.0a1', '3.4.0.dev0'),
            ('3.9.0rc2', '3.9.0.dev0'),
        ],
    )
    def test_pre_releases_drop_their_suffix(self, released: str, expected: str):
        """A pre-release goes back to its own base version, bumping nothing."""
        assert post_release.next_dev_version(released, 'main') == expected

    def test_a_pre_release_on_a_maintenance_branch_still_drops_its_suffix(self):
        """release.py tests `.pre` before the branch name, so the patch stays put."""
        assert post_release.next_dev_version('2.23.6rc1', '2.23-maintenance') == '2.23.6.dev0'

    @pytest.mark.parametrize(
        ('released', 'branch', 'expected'),
        [
            ('9.9.9', 'main', '9.10.0.dev0'),
            ('9.9.9', '1.5-maintenance', '9.9.10.dev0'),
            ('3.0.0', 'main', '3.1.0.dev0'),
            ('2.23.9', '2.23-maintenance', '2.23.10.dev0'),
        ],
    )
    def test_the_bump_is_arithmetic_and_not_string_work(
        self, released: str, branch: str, expected: str
    ):
        """9 goes to 10 rather than to 0, on either half of the version."""
        assert post_release.next_dev_version(released, branch) == expected

    def test_a_development_version_falls_through_to_the_bumps(self):
        """Unreachable here, but it is what release.py does: it only reads `.pre`."""
        assert post_release.next_dev_version('3.9.0.dev0', 'main') == '3.10.0.dev0'

    @pytest.mark.parametrize('released', ['v3.8.2', '3.8', '3.8.2.post1', '3.8.2-rc1', ''])
    def test_a_version_of_another_shape_is_refused(self, released: str):
        """A tag this repository does not release is an error, not a guess."""
        with pytest.raises(ValueError):
            post_release.next_dev_version(released, 'main')


# Every branch canonical/operator releases from, as `git for-each-ref` lists
# them: `main` and the six maintenance branches, in its order rather than in
# version order.
CANDIDATES = [
    '1.5-maintenance',
    '2.16-maintenance',
    '2.19-maintenance',
    '2.23-maintenance',
    '2.5-maintenance',
    '3.3-maintenance',
    'main',
]


class TestResolveBranch:
    """Getting from the event to the branch the release was cut from.

    The containment lists below were measured against canonical/operator: for
    every tag, which of the seven branches above has the tag in its history.
    """

    def test_a_draft_from_the_workflow_carries_a_sha_and_the_tag_places_it(self):
        """--target is the merge commit, so the name is no help and the tag answers it."""
        branch, why = post_release.resolve_branch(
            '0d7fbd21ad9d4a9e2e0f53b96e0b1a1f7ac8c7dd', CANDIDATES, ['main']
        )
        assert branch == 'main'
        assert 'only branch' in why

    def test_a_maintenance_release_is_on_its_own_branch_alone(self):
        """Measured for 2.23.5: `main` does not have it, which is what the branch is for."""
        branch, _ = post_release.resolve_branch(
            '938e064b2a0e94f2a1b3f0b5f1a0a0f1e2d3c4b5', CANDIDATES, ['2.23-maintenance']
        )
        assert branch == '2.23-maintenance'

    @pytest.mark.parametrize(
        'containing',
        [
            # Measured: 2.23.0 and 3.3.0 were both released from `main`, and
            # a maintenance branch was cut off `main` afterwards, so both
            # branches have the tag in their history.
            ['main', '2.23-maintenance', '3.3-maintenance'],
            ['main', '3.3-maintenance'],
        ],
    )
    def test_main_wins_when_several_branches_have_the_tag(self, containing: list[str]):
        """A release cut from `main` before a branch was taken off it is still `main`'s."""
        branch, why = post_release.resolve_branch('deadbeef', CANDIDATES, containing)
        assert branch == 'main'
        assert 'main wins' in why

    def test_a_named_branch_is_taken_at_its_word(self):
        """A release made by hand carries a branch name rather than a SHA."""
        branch, why = post_release.resolve_branch(
            '2.23-maintenance', CANDIDATES, ['main', '2.23-maintenance']
        )
        assert branch == '2.23-maintenance'
        assert 'names 2.23-maintenance' in why

    def test_a_named_branch_without_the_tag_does_not_win(self):
        """The name is a hint: if that branch has not got the tag, containment decides."""
        branch, _ = post_release.resolve_branch('main', CANDIDATES, ['2.23-maintenance'])
        assert branch == '2.23-maintenance'

    def test_a_named_branch_is_enough_when_the_tag_is_not_in_the_checkout(self):
        """With nothing to place the tag against, the name is all there is."""
        branch, why = post_release.resolve_branch('main', CANDIDATES, [])
        assert branch == 'main'
        assert 'not in the checkout' in why

    def test_nothing_to_go_on_is_an_error(self):
        """No containment and a target that names no release branch: stop."""
        with pytest.raises(ValueError, match='No release branch'):
            post_release.resolve_branch('deadbeef', CANDIDATES, [])

    def test_several_maintenance_branches_and_no_main_is_an_error(self):
        """Cannot happen today; it is a guess rather than a wrong answer, so it is loud."""
        with pytest.raises(ValueError, match='is a guess'):
            post_release.resolve_branch(
                'deadbeef', CANDIDATES, ['2.19-maintenance', '2.23-maintenance']
            )

    def test_the_branch_it_picks_is_what_the_arithmetic_reads(self):
        """The two halves joined up: the branch is the pull request's base and the bump."""
        branch, _ = post_release.resolve_branch('deadbeef', CANDIDATES, ['2.23-maintenance'])
        assert post_release.next_dev_version('2.23.5', branch) == '2.23.6.dev0'


class TestSplit:
    """The comma-separated lists the workflow builds, leading commas and all."""

    def test_leading_and_repeated_commas_are_dropped(self):
        """The workflow appends `,$branch` in a loop, so the first item is empty."""
        assert post_release.split(',main,,2.23-maintenance,') == ['main', '2.23-maintenance']

    def test_an_empty_list_is_empty(self):
        """No branches contain the tag: an empty string, not a list with one empty name."""
        assert post_release.split('') == []
        assert post_release.split(',,') == []


class TestCommandLine:
    """The script as the workflow runs it."""

    def test_it_prints_the_branch_and_the_version(self, capsys: pytest.CaptureFixture[str]):
        """Two lines on stdout for $GITHUB_OUTPUT, and the reasoning on stderr."""
        code = post_release.main([
            '--tag',
            '2.23.5',
            '--target',
            '938e064b',
            '--candidates',
            ',main,2.23-maintenance',
            '--containing',
            ',2.23-maintenance',
        ])
        assert code == 0
        captured = capsys.readouterr()
        assert captured.out == 'branch=2.23-maintenance\nversion=2.23.6.dev0\n'
        assert '2.23.5 was released from 2.23-maintenance' in captured.err

    def test_a_branch_it_cannot_work_out_exits_1_and_prints_nothing(
        self, capsys: pytest.CaptureFixture[str]
    ):
        """Nothing on stdout, so a failed step cannot half-write $GITHUB_OUTPUT."""
        code = post_release.main([
            '--tag',
            '3.8.3',
            '--target',
            'deadbeef',
            '--candidates',
            'main',
            '--containing',
            '',
        ])
        assert code == 1
        captured = capsys.readouterr()
        assert captured.out == ''
        assert 'No release branch' in captured.err

    def test_a_tag_it_cannot_take_apart_exits_1(self, capsys: pytest.CaptureFixture[str]):
        """The branch resolves, but `v3.8.3` is not a version this repository releases."""
        code = post_release.main([
            '--tag',
            'v3.8.3',
            '--target',
            'main',
            '--candidates',
            'main',
            '--containing',
            'main',
        ])
        assert code == 1
        assert capsys.readouterr().out == ''


# A tree small enough to assert on and shaped like the real one, so that the
# post-release fan-out can be checked file by file. The version strings are
# the ones the 3.8.2 release left behind.
TREE = {
    'ops/version.py': (
        '"""Package version."""\n\nfrom __future__ import annotations\n\n'
        "version: str = '3.8.2'\n"
    ),
    'pyproject.toml': (
        '[project]\nname = "ops"\ndependencies = [\n'
        '    "ops-scenario==8.8.2",\n    "ops-tracing==3.8.2",\n]\n'
    ),
    'testing/pyproject.toml': (
        '[project]\nname = "ops-scenario"\nversion = "8.8.2"\ndependencies = [\n'
        '    "ops==3.8.2",\n]\n'
    ),
    'tracing/pyproject.toml': (
        '[project]\nname = "ops-tracing"\nversion = "3.8.2"\ndependencies = [\n'
        '    "ops==3.8.2",\n]\n'
    ),
    'docs/explanation/versions.md': (
        '| Version | Status | Released | EOL |\n'
        '| Ops 2.23 (LTS) | Active | 2023-01-25 | 2038-01-25 |\n'
        '| Ops 3.8 | Active | 2026-08-31 | 2027-08-31 |\n'
    ),
}


@pytest.fixture
def tree(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    """Write the small tree out and chdir into it, as the workflow does."""
    for name, content in TREE.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    monkeypatch.chdir(tmp_path)
    return tmp_path


class TestPostReleaseFanOut:
    """update-release-versions.py in its post-release shape."""

    def test_it_writes_every_version_file_and_leaves_the_doc(self, tree: pathlib.Path):
        """The four files it rewrites, and the one it does not."""
        assert update.main(['--version', '3.9.0.dev0', '--post-release']) == 0

        assert "version: str = '3.9.0.dev0'" in (tree / 'ops/version.py').read_text()

        root = (tree / 'pyproject.toml').read_text()
        assert 'ops-scenario==8.9.0.dev0' in root
        assert 'ops-tracing==3.9.0.dev0' in root

        testing = (tree / 'testing/pyproject.toml').read_text()
        assert 'version = "8.9.0.dev0"' in testing
        assert 'ops==3.9.0.dev0' in testing

        tracing = (tree / 'tracing/pyproject.toml').read_text()
        assert 'version = "3.9.0.dev0"' in tracing
        assert 'ops==3.9.0.dev0' in tracing

        # The one difference from a release: the tool-versions table records
        # releases, and a bump back to a development version is not one.
        assert (tree / 'docs/explanation/versions.md').read_text() == (
            TREE['docs/explanation/versions.md']
        )

    def test_a_release_run_on_the_same_tree_does_write_the_doc(self, tree: pathlib.Path):
        """The other half of the pair: the skipping is the flag's doing."""
        assert update.main(['--version', '3.9.0', '--date', '2026-09-30']) == 0
        doc = (tree / 'docs/explanation/versions.md').read_text()
        assert '| Ops 3.9 | Active | 2026-09-30 | 2027-09-30 |' in doc

    def test_the_maintenance_shape(self, tree: pathlib.Path):
        """The LTS branch's patch bump, over the same four files."""
        for name in TREE:
            if name.endswith('.md'):
                continue
            path = tree / name
            path.write_text(path.read_text().replace('3.8.2', '2.23.5').replace('8.8.2', '7.23.5'))

        assert update.main(['--version', '2.23.6.dev0', '--post-release']) == 0
        assert "version: str = '2.23.6.dev0'" in (tree / 'ops/version.py').read_text()
        assert 'version = "7.23.6.dev0"' in (tree / 'testing/pyproject.toml').read_text()
        assert (tree / 'docs/explanation/versions.md').read_text() == (
            TREE['docs/explanation/versions.md']
        )

    def test_the_scenario_version_carries_the_dev_suffix(self):
        """ops-scenario is five majors ahead, suffix and all."""
        assert update.scenario_version('3.9.0.dev0') == '8.9.0.dev0'
        assert update.scenario_version('3.4.0.dev0') == '8.4.0.dev0'

    def test_a_tree_already_at_the_version_is_an_error(self, tree: pathlib.Path):
        """The workflow checks the branch first, so this is the backstop."""
        assert update.main(['--version', '3.9.0.dev0', '--post-release']) == 0
        assert update.main(['--version', '3.9.0.dev0', '--post-release']) == 1

    def test_the_files_the_workflow_commits_are_the_files_it_writes(self, tree: pathlib.Path):
        """Nothing else in the tree moves, so the commit can name its files."""
        before = {path: path.read_text() for path in sorted(tree.rglob('*')) if path.is_file()}
        assert update.main(['--version', '3.9.0.dev0', '--post-release']) == 0
        changed = {
            str(path.relative_to(tree))
            for path, content in before.items()
            if path.read_text() != content
        }
        # uv.lock is the fifth, and the workflow writes it in its own step.
        assert changed == {
            'ops/version.py',
            'pyproject.toml',
            'testing/pyproject.toml',
            'tracing/pyproject.toml',
        }
