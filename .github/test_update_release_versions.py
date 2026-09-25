# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Tests for update-release-versions.py, which rewrites the version strings.

`tox -e unit` runs this, but only because the unit environment names the file:
pytest's default `norecursedirs` skips dotted directories, so it never finds
anything under `.github/` on its own. A new test file here needs adding to that
list in `tox.ini`. To run this one on its own:

    uv run --group unit pytest .github/test_update_release_versions.py

The script has a hyphen in its name, following the other scripts here, which
means it cannot be imported by name; `load` below does it by path.
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


update = load('update-release-versions')


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
