# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

from __future__ import annotations

import pathlib
import shutil
import subprocess
import textwrap

import pytest
from scenario import _charm_requirements
from scenario._charm_requirements import _RequirementsError

needs_uv = pytest.mark.skipif(shutil.which('uv') is None, reason='needs uv on PATH')


def _charmcraft(root: pathlib.Path, text: str) -> pathlib.Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / 'charmcraft.yaml').write_text(textwrap.dedent(text))
    return root


# Detecting the build plugin


@pytest.mark.parametrize('plugin', ['python', 'uv'])
def test_detects_the_plugin_from_charmcraft_yaml(tmp_path: pathlib.Path, plugin: str):
    root = _charmcraft(
        tmp_path,
        f"""
        type: charm
        parts:
          deps:
            plugin: nil
          charm:
            plugin: {plugin}
            source: .
            {plugin}-extra: x
        """,
    )
    detected, part = _charm_requirements.detect_plugin(root)
    assert detected == plugin
    assert part[f'{plugin}-extra'] == 'x'


CHARM_PLUGIN_ERROR = (
    r'charm plugin, which is deprecated and isn\'t supported\. '
    r'Move the charm to the uv or python plugin\.'
)


def test_the_charm_plugin_is_an_error(tmp_path: pathlib.Path):
    root = _charmcraft(tmp_path, 'parts:\n  deps:\n    plugin: nil\n  build:\n    plugin: charm\n')
    with pytest.raises(_RequirementsError, match=rf"Part 'build'.*{CHARM_PLUGIN_ERROR}"):
        _charm_requirements.detect_plugin(root)


def test_a_part_named_charm_with_no_plugin_is_the_charm_plugin(tmp_path: pathlib.Path):
    root = _charmcraft(tmp_path, 'parts:\n  charm:\n    charm-requirements: [reqs.txt]\n')
    with pytest.raises(_RequirementsError, match=rf"Part 'charm'.*{CHARM_PLUGIN_ERROR}"):
        _charm_requirements.detect_plugin(root)


def test_charmcraft_yaml_with_no_parts_is_the_charm_plugin(tmp_path: pathlib.Path):
    root = _charmcraft(tmp_path, 'type: charm\nname: x\n')
    (root / 'uv.lock').write_text('')
    with pytest.raises(_RequirementsError, match=rf'has no parts.*{CHARM_PLUGIN_ERROR}'):
        _charm_requirements.detect_plugin(root)


def test_with_no_charmcraft_yaml_a_uv_lock_means_uv(tmp_path: pathlib.Path):
    with pytest.raises(
        _RequirementsError, match=rf'no charmcraft.yaml or uv.lock.*{CHARM_PLUGIN_ERROR}'
    ):
        _charm_requirements.detect_plugin(tmp_path)
    (tmp_path / 'uv.lock').write_text('')
    assert _charm_requirements.detect_plugin(tmp_path) == ('uv', {})


@pytest.mark.parametrize('plugin', ['poetry', 'reactive'])
def test_unsupported_plugins_are_an_error(tmp_path: pathlib.Path, plugin: str):
    root = _charmcraft(tmp_path, f'parts:\n  charm:\n    plugin: {plugin}\n')
    with pytest.raises(_RequirementsError, match=rf"the {plugin} plugin isn't supported"):
        _charm_requirements.detect_plugin(root)


def test_a_poetry_lock_without_charmcraft_yaml_is_an_error(tmp_path: pathlib.Path):
    (tmp_path / 'poetry.lock').write_text('')
    with pytest.raises(_RequirementsError, match=r"poetry.lock.*poetry plugin isn't supported"):
        _charm_requirements.detect_plugin(tmp_path)


def test_no_python_part_names_the_parts(tmp_path: pathlib.Path):
    root = _charmcraft(
        tmp_path, 'parts:\n  web:\n    plugin: flask-framework\n  files:\n    plugin: dump\n'
    )
    with pytest.raises(_RequirementsError, match=r'use: web \(flask-framework\)\.$'):
        _charm_requirements.detect_plugin(root)


@pytest.mark.parametrize(
    ('text', 'error'),
    [
        ('parts: [\n', 'Could not read'),
        ('parts: [a, b]\n', 'parts in .* is not a mapping'),
        ('parts:\n  charm: x\n', "Part 'charm' in .* is not a mapping"),
    ],
)
def test_a_malformed_charmcraft_yaml_is_an_error(tmp_path: pathlib.Path, text: str, error: str):
    root = _charmcraft(tmp_path, text)
    with pytest.raises(_RequirementsError, match=error):
        _charm_requirements.detect_plugin(root)


# Reading requirements files


def test_read_requirements_flattens_a_requirements_file(tmp_path: pathlib.Path):
    (tmp_path / 'sub').mkdir()
    (tmp_path / 'sub' / 'more.txt').write_text('included==1  # A comment.\n-r ../base.txt\n')
    (tmp_path / 'base.txt').write_text('base>=2\n-r sub/more.txt\n')
    (tmp_path / 'constraints.txt').write_text('')
    (tmp_path / 'requirements.txt').write_text(
        textwrap.dedent("""\
            # Exported.
            pinned==1.0 \\
                --hash=sha256:abc \\
                --hash=sha256:def
            marked==2.0 ; python_version >= "3.8"
            -r sub/more.txt
            -c constraints.txt
            --find-links=wheels
            ./local/package
            named @ ./local/named
            named-url @ https://example.com/x.whl
            --extra-index-url https://example.com/simple

            """)
    )
    assert _charm_requirements.read_requirements(tmp_path / 'requirements.txt') == [
        'pinned==1.0',
        'marked==2.0 ; python_version >= "3.8"',
        'included==1',
        'base>=2',
        f'-c {tmp_path / "constraints.txt"}',
        f'--find-links {tmp_path / "wheels"}',
        str(tmp_path / 'local' / 'package'),
        f'named @ {(tmp_path / "local" / "named").as_uri()}',
        'named-url @ https://example.com/x.whl',
        '--extra-index-url https://example.com/simple',
    ]


# The python plugin


def test_python_plugin_requirements(tmp_path: pathlib.Path):
    root = _charmcraft(
        tmp_path,
        """
        parts:
          charm:
            plugin: python
            source: .
            python-requirements: [requirements.txt]
            python-packages: [extra==1, requests==2.32]
            python-constraints: [constraints.txt]
        """,
    )
    (root / 'requirements.txt').write_text('requests==2.32\nops==2.17.0\nops_scenario>=7\n')
    (root / 'constraints.txt').write_text('urllib3<3\n')
    # charmcraft's python plugin doesn't install charm libraries' PYDEPS.
    (root / 'lib' / 'charms' / 'thing' / 'v0').mkdir(parents=True)
    (root / 'lib' / 'charms' / 'thing' / 'v0' / 'thing.py').write_text(
        'PYDEPS = ["pydantic>=2"]\n'
    )
    # ops and ops-scenario are left out, and so are repeats.
    assert _charm_requirements.charm_requirements(root) == [
        'requests==2.32',
        'extra==1',
        f'-c {root / "constraints.txt"}',
    ]


@pytest.mark.parametrize('kind', ['requirements', 'constraints'])
def test_a_missing_listed_file_is_an_error(tmp_path: pathlib.Path, kind: str):
    root = _charmcraft(
        tmp_path, f'parts:\n  charm:\n    plugin: python\n    python-{kind}: [x.txt]\n'
    )
    with pytest.raises(_RequirementsError, match=rf'lists x.txt as a {kind} file'):
        _charm_requirements.charm_requirements(root)


# The uv plugin


def _uv_charm(root: pathlib.Path, part: str = '', pyproject: str = '') -> pathlib.Path:
    """A uv charm with path dependencies, so that locking it needs no index."""
    for name in ('base', 'extra', 'grouped', 'dev'):
        (root / 'deps' / name).mkdir(parents=True)
        (root / 'deps' / name / 'pyproject.toml').write_text(
            f'[project]\nname = "{name}"\nversion = "1.0"\n'
        )
    _charmcraft(root, f'parts:\n  charm:\n    plugin: uv\n    source: .\n{part}')
    (root / 'pyproject.toml').write_text(
        textwrap.dedent("""
            [project]
            name = "charm"
            version = "0"
            requires-python = ">=3.10"
            dependencies = ["base"]

            [project.optional-dependencies]
            x = ["extra"]

            [dependency-groups]
            dev = ["dev"]
            g = ["grouped"]

            [tool.uv.sources]
            base = { path = "deps/base" }
            extra = { path = "deps/extra" }
            grouped = { path = "deps/grouped" }
            dev = { path = "deps/dev" }
        """)
        + pyproject
    )
    subprocess.run(
        [shutil.which('uv') or 'uv', 'lock', '--quiet', '--offline'], cwd=root, check=True
    )
    return root


@needs_uv
def test_uv_plugin_leaves_out_the_dev_group(tmp_path: pathlib.Path):
    root = _uv_charm(tmp_path)
    # Path dependencies are made absolute.
    assert _charm_requirements.charm_requirements(root) == [str(root / 'deps' / 'base')]


@needs_uv
def test_uv_plugin_keeps_other_default_groups(tmp_path: pathlib.Path):
    root = _uv_charm(tmp_path, pyproject='\n[tool.uv]\ndefault-groups = ["dev", "g"]\n')
    assert sorted(_charm_requirements.charm_requirements(root)) == [
        str(root / 'deps' / name) for name in ('base', 'grouped')
    ]


@needs_uv
def test_uv_plugin_forwards_extras_and_groups(tmp_path: pathlib.Path):
    root = _uv_charm(tmp_path, '    uv-extras: [x]\n    uv-groups: [g]\n')
    assert sorted(_charm_requirements.charm_requirements(root)) == [
        str(root / 'deps' / name) for name in ('base', 'extra', 'grouped')
    ]


@needs_uv
def test_uv_plugin_with_a_stale_lockfile(tmp_path: pathlib.Path):
    root = _uv_charm(tmp_path)
    pyproject = root / 'pyproject.toml'
    pyproject.write_text(pyproject.read_text().replace('["base"]', '["base", "extra"]'))
    with pytest.raises(_RequirementsError, match=r'uv.lock .* is out of date.*`uv lock`'):
        _charm_requirements.charm_requirements(root)


def test_uv_plugin_without_a_lockfile(tmp_path: pathlib.Path):
    root = _charmcraft(tmp_path, 'parts:\n  charm:\n    plugin: uv\n')
    with pytest.raises(_RequirementsError, match=r'has no uv.lock\. Run `uv lock`'):
        _charm_requirements.charm_requirements(root)


def test_uv_plugin_without_uv(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    root = _charmcraft(tmp_path, 'parts:\n  charm:\n    plugin: uv\n')
    (root / 'uv.lock').write_text('')
    monkeypatch.setenv('PATH', str(tmp_path / 'empty'))
    with pytest.raises(_RequirementsError, match='uv is not on PATH'):
        _charm_requirements.charm_requirements(root)
