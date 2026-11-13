# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys
import textwrap
import zipfile

import pytest
from scenario import _charm_requirements
from scenario._charm_requirements import _RequirementsError


def _charmcraft(root: pathlib.Path, text: str) -> pathlib.Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / 'charmcraft.yaml').write_text(textwrap.dedent(text))
    return root


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


def test_no_charmcraft_yaml_is_an_error(tmp_path: pathlib.Path):
    # A lockfile isn't enough: charmcraft can't build a charm without charmcraft.yaml.
    (tmp_path / 'uv.lock').write_text('')
    with pytest.raises(_RequirementsError, match=r'has no charmcraft.yaml'):
        _charm_requirements.detect_plugin(tmp_path)


@pytest.mark.parametrize('parts', ['', 'parts:\n  charm:\n    build-snaps: [rustup]\n'])
def test_an_extension_is_an_error(tmp_path: pathlib.Path, parts: str):
    # The extension's part sets the plugin, which depends on the base.
    root = _charmcraft(tmp_path, f'base: ubuntu@26.04\nextensions: [flask-framework]\n{parts}')
    with pytest.raises(_RequirementsError, match=r'uses the flask-framework extension'):
        _charm_requirements.detect_plugin(root)


@pytest.mark.parametrize('name', ['charm', 'deps'])
def test_an_extension_with_a_uv_part_is_an_error(tmp_path: pathlib.Path, name: str):
    # charmcraft rejects a customised charm part, and adds its own charm part
    # alongside a part with another name.
    root = _charmcraft(
        tmp_path, f'extensions: [flask-framework]\nparts:\n  {name}:\n    plugin: uv\n'
    )
    with pytest.raises(_RequirementsError, match=r'uses the flask-framework extension'):
        _charm_requirements.detect_plugin(root)


@pytest.mark.parametrize('order', [('python', 'charm'), ('charm', 'python')])
def test_every_part_is_checked(tmp_path: pathlib.Path, order: tuple[str, str]):
    parts = ''.join(f'  {plugin}-part:\n    plugin: {plugin}\n' for plugin in order)
    root = _charmcraft(tmp_path, f'parts:\n{parts}')
    with pytest.raises(_RequirementsError, match=CHARM_PLUGIN_ERROR):
        _charm_requirements.detect_plugin(root)


def test_more_than_one_python_part_is_an_error(tmp_path: pathlib.Path):
    root = _charmcraft(
        tmp_path, 'parts:\n  charm:\n    plugin: uv\n  extra:\n    plugin: python\n'
    )
    with pytest.raises(_RequirementsError, match=r'More than one part .*charm \(uv\), extra'):
        _charm_requirements.detect_plugin(root)


@pytest.mark.parametrize('plugin', ['poetry', 'reactive'])
def test_unsupported_plugins_are_an_error(tmp_path: pathlib.Path, plugin: str):
    root = _charmcraft(tmp_path, f'parts:\n  charm:\n    plugin: {plugin}\n')
    with pytest.raises(_RequirementsError, match=rf"the {plugin} plugin isn't supported"):
        _charm_requirements.detect_plugin(root)


@pytest.mark.parametrize('python_plugin', ['', '  deps:\n    plugin: uv\n'])
def test_unknown_plugin_is_refused(tmp_path: pathlib.Path, python_plugin: str):
    # Even next to a Python part: the unknown one might install dependencies too.
    root = _charmcraft(
        tmp_path,
        f'parts:\n{python_plugin}  web:\n    plugin: flask-framework\n'
        '  files:\n    plugin: dump\n',
    )
    with pytest.raises(_RequirementsError, match=r'too: web \(flask-framework\)\.$'):
        _charm_requirements.detect_plugin(root)


def test_other_craft_parts_plugins_are_skipped(tmp_path: pathlib.Path):
    root = _charmcraft(tmp_path, 'parts:\n  deps:\n    plugin: uv\n  java:\n    plugin: maven\n')
    plugin, _ = _charm_requirements.detect_plugin(root)
    assert plugin == 'uv'


@pytest.mark.parametrize(
    ('text', 'error'),
    [
        ('parts: [\n', 'Could not read'),
        ('[parts]\n', 'charmcraft.yaml is not a mapping'),
        ('parts: [a, b]\n', 'parts in .* is not a mapping'),
        ('parts:\n  charm: x\n', "Part 'charm' in .* is not a mapping"),
    ],
)
def test_a_malformed_charmcraft_yaml_is_an_error(tmp_path: pathlib.Path, text: str, error: str):
    root = _charmcraft(tmp_path, text)
    with pytest.raises(_RequirementsError, match=error):
        _charm_requirements.detect_plugin(root)


def test_python_plugin_requirements(tmp_path: pathlib.Path):
    root = _charmcraft(
        tmp_path,
        """
        parts:
          charm:
            plugin: python
            source: .
            source-subdir: src dir
            python-requirements: [requirements.txt]
            python-packages: [extra==1, ./vendor/lib]
            python-constraints: [constraints.txt]
        """,
    )
    (root / 'src dir').mkdir()
    (root / 'src dir' / 'requirements.txt').write_text('requests==2.32\n')
    (root / 'src dir' / 'constraints.txt').write_text('urllib3<3\n')
    # charmcraft's python plugin doesn't install charm libraries' PYDEPS.
    (root / 'lib' / 'charms' / 'thing' / 'v0').mkdir(parents=True)
    (root / 'lib' / 'charms' / 'thing' / 'v0' / 'thing.py').write_text(
        'PYDEPS = ["pydantic>=2"]\n'
    )
    # The files and packages are given to pip as charmcraft gives them, to run
    # in the part's build directory.
    assert _charm_requirements.charm_requirements(root) == _charm_requirements._Requirements(
        root / 'src dir',
        (
            '--constraint=constraints.txt',
            '--requirement=requirements.txt',
            'extra==1',
            './vendor/lib',
        ),
        check=True,
    )


def test_a_part_source_that_is_not_local_is_an_error(tmp_path: pathlib.Path):
    root = _charmcraft(
        tmp_path, 'parts:\n  charm:\n    plugin: python\n    source: https://x.com/c.git\n'
    )
    with pytest.raises(_RequirementsError, match=r"isn't a local directory"):
        _charm_requirements.charm_requirements(root)


@pytest.mark.parametrize('kind', ['requirements', 'constraints'])
def test_a_missing_listed_file_is_an_error(tmp_path: pathlib.Path, kind: str):
    root = _charmcraft(
        tmp_path, f'parts:\n  charm:\n    plugin: python\n    python-{kind}: [x.txt]\n'
    )
    with pytest.raises(_RequirementsError, match=rf'lists x.txt as a {kind} file'):
        _charm_requirements.charm_requirements(root)


@pytest.mark.parametrize(
    'key',
    ['python-requirements', 'python-packages', 'python-constraints', 'uv-extras', 'uv-groups'],
)
def test_a_list_option_that_is_not_a_list_is_an_error(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, key: str
):
    monkeypatch.setenv('PATH', str(tmp_path / 'empty'))
    plugin = key.partition('-')[0]
    root = _charmcraft(tmp_path, f'parts:\n  charm:\n    plugin: {plugin}\n    {key}: x.txt\n')
    (root / 'uv.lock').write_text('')
    with pytest.raises(_RequirementsError, match=rf'{key} in .* is not a list'):
        _charm_requirements.charm_requirements(root)


def _uv_charm(root: pathlib.Path, part: str = '', pyproject: str = '') -> pathlib.Path:
    """A uv charm with path dependencies, so that locking it needs no index."""
    for name in ('base', 'extra', 'grouped', 'dev', 'editable', 'ops', 'ops-tracing'):
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
            dependencies = ["base", "editable", "ops", "ops-tracing"]

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
            editable = { path = "deps/editable", editable = true }
            ops = { path = "deps/ops" }
            ops-tracing = { path = "deps/ops-tracing" }

            # A charm that's a package, so that leaving the project out is tested.
            [build-system]
            requires = ["uv_build"]
            build-backend = "uv_build"
        """)
        + pyproject
    )
    subprocess.run(
        [shutil.which('uv') or 'uv', 'lock', '--quiet', '--offline'], cwd=root, check=True
    )
    return root


def _uv_args(root: pathlib.Path) -> list[str]:
    requirements = _charm_requirements.charm_requirements(root)
    assert requirements.directory == root
    return sorted(requirements.args)


def test_uv_plugin_leaves_out_the_dev_group(tmp_path: pathlib.Path):
    root = _uv_charm(tmp_path)
    # Editable dependencies aren't editable, and the charm itself, ops and
    # ops-tracing aren't included.
    assert _uv_args(root) == ['./deps/base', './deps/editable']


def test_uv_plugin_keeps_other_default_groups(tmp_path: pathlib.Path):
    root = _uv_charm(tmp_path, pyproject='\n[tool.uv]\ndefault-groups = ["dev", "g"]\n')
    assert _uv_args(root) == ['./deps/base', './deps/editable', './deps/grouped']


def test_uv_plugin_forwards_extras_and_groups(tmp_path: pathlib.Path):
    root = _uv_charm(tmp_path, '    uv-extras: [x]\n    uv-groups: [g]\n')
    assert _uv_args(root) == [
        './deps/base',
        './deps/editable',
        './deps/extra',
        './deps/grouped',
    ]


def test_uv_plugin_uses_the_source_subdir(tmp_path: pathlib.Path):
    _uv_charm(tmp_path / 'charm')
    root = _charmcraft(
        tmp_path, 'parts:\n  charm:\n    plugin: uv\n    source: .\n    source-subdir: charm\n'
    )
    requirements = _charm_requirements.charm_requirements(root)
    assert requirements.directory == root / 'charm'
    assert sorted(requirements.args) == ['./deps/base', './deps/editable']


def test_uv_plugin_in_a_monorepo(tmp_path: pathlib.Path):
    # The layout charmcraft's experimental monorepo mode documents: the part's
    # source is the repository root, and the charm uses shared code from it.
    repo = tmp_path / 'repo'
    (repo / '.git').mkdir(parents=True)
    (repo / 'shared' / 'common').mkdir(parents=True)
    (repo / 'shared' / 'common' / 'pyproject.toml').write_text(
        '[project]\nname = "common"\nversion = "1.0"\n'
    )
    root = repo / 'charms' / 'my-charm'
    _charmcraft(
        root,
        'parts:\n  my-charm:\n    plugin: uv\n    source: ../..\n'
        '    source-subdir: charms/my-charm\n',
    )
    (root / 'pyproject.toml').write_text(
        textwrap.dedent("""
            [project]
            name = "my-charm"
            version = "0"
            requires-python = ">=3.10"
            dependencies = ["common"]

            [tool.uv.sources]
            common = { path = "../../shared/common" }
        """)
    )
    subprocess.run(
        [shutil.which('uv') or 'uv', 'lock', '--quiet', '--offline'], cwd=root, check=True
    )
    requirements = _charm_requirements.charm_requirements(root)
    assert requirements.directory == root.resolve()
    assert requirements.args == ('../../shared/common',)


def test_a_part_source_outside_the_repository_is_an_error(tmp_path: pathlib.Path):
    (tmp_path / 'repo' / '.git').mkdir(parents=True)
    (tmp_path / 'elsewhere').mkdir()
    root = _charmcraft(
        tmp_path / 'repo' / 'charm',
        'parts:\n  charm:\n    plugin: python\n    source: ../../elsewhere\n',
    )
    with pytest.raises(_RequirementsError, match="outside the charm's git repository"):
        _charm_requirements.charm_requirements(root)


def test_uv_plugin_with_a_stale_lockfile(tmp_path: pathlib.Path):
    root = _uv_charm(tmp_path)
    pyproject = root / 'pyproject.toml'
    pyproject.write_text(
        pyproject.read_text().replace('"ops-tracing"]', '"ops-tracing", "extra"]')
    )
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


def _wheel(directory: pathlib.Path, name: str, requires: str = '') -> str:
    """Build a wheel with no code, so that installing it needs no index or build."""
    directory.mkdir(parents=True, exist_ok=True)
    stem = f'{name.replace("-", "_")}-1.0'
    metadata = f'Metadata-Version: 2.1\nName: {name}\nVersion: 1.0\n'
    if requires:
        metadata += f'Requires-Dist: {requires}\n'
    with zipfile.ZipFile(directory / f'{stem}-py3-none-any.whl', 'w') as wheel:
        wheel.writestr(f'{stem}.dist-info/METADATA', metadata)
        wheel.writestr(
            f'{stem}.dist-info/WHEEL',
            'Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n',
        )
        wheel.writestr(f'{stem}.dist-info/RECORD', '')
    return f'{stem}-py3-none-any.whl'


def _installed(python: pathlib.Path) -> list[str]:
    script = 'import importlib.metadata as m; print(*sorted(d.name for d in m.distributions()))'
    result = subprocess.run(
        [python, '-I', '-c', script], capture_output=True, text=True, check=True
    )
    return result.stdout.split()


@pytest.fixture
def venv(tmp_path: pathlib.Path) -> pathlib.Path:
    subprocess.run([sys.executable, '-m', 'venv', '--without-pip', tmp_path / 'venv'], check=True)
    return tmp_path / 'venv' / 'bin' / 'python'


def test_install_python_plugin(tmp_path: pathlib.Path, venv: pathlib.Path):
    # A space in the path, and relative paths in the part and in the files,
    # work because pip runs in the part's build directory.
    root = tmp_path / 'my charm'
    wheels = root / 'src' / 'wheels'
    names = {name: _wheel(wheels, name) for name in ('listed', 'packaged', 'ops', 'ops-scenario')}
    _charmcraft(
        root,
        f"""
        parts:
          charm:
            plugin: python
            source: src
            python-requirements: [requirements.txt]
            python-packages: [./wheels/{names['packaged']}, ./wheels/{names['ops-scenario']}]
        """,
    )
    (root / 'src' / 'requirements.txt').write_text(f'./wheels/{names["listed"]}\n-r more.txt\n')
    (root / 'src' / 'more.txt').write_text(f'./wheels/{names["ops"]}\n')
    _charm_requirements.install_charm_requirements(root, venv)
    assert _installed(venv) == ['listed', 'packaged']


def test_install_uv_plugin(tmp_path: pathlib.Path, venv: pathlib.Path):
    root = _charmcraft(tmp_path / 'charm', 'parts:\n  charm:\n    plugin: uv\n    source: .\n')
    names = {name: _wheel(root / 'wheels', name) for name in ('dep', 'ops')}
    (root / 'pyproject.toml').write_text(
        textwrap.dedent(f"""
            [project]
            name = "charm"
            version = "0"
            requires-python = ">=3.10"
            dependencies = ["dep", "ops"]

            [tool.uv.sources]
            dep = {{ path = "wheels/{names['dep']}" }}
            ops = {{ path = "wheels/{names['ops']}" }}
        """)
    )
    subprocess.run(
        [shutil.which('uv') or 'uv', 'lock', '--quiet', '--offline'], cwd=root, check=True
    )
    _charm_requirements.install_charm_requirements(root, venv)
    assert _installed(venv) == ['dep']


def test_a_failed_install_is_an_error(tmp_path: pathlib.Path, venv: pathlib.Path):
    root = _charmcraft(
        tmp_path, 'parts:\n  charm:\n    plugin: python\n    python-packages: [./missing]\n'
    )
    with pytest.raises(_RequirementsError, match=r'--no-deps ./missing` failed'):
        _charm_requirements.install_charm_requirements(root, venv)


def _no_uv(name: str) -> str | None:
    return None


def test_a_failed_command_shows_its_stdout_too():
    script = 'import sys; print("on stdout"); print("on stderr", file=sys.stderr); sys.exit(1)'
    with pytest.raises(_RequirementsError) as excinfo:
        _charm_requirements._run([sys.executable, '-c', script])
    assert str(excinfo.value).endswith('failed:\non stderr\non stdout\n')


def test_pip_fallback_command(monkeypatch: pytest.MonkeyPatch):
    # Without uv, the test's own pip is used, and it only accepts --python
    # before the command.
    monkeypatch.setattr(shutil, 'which', _no_uv)
    python = pathlib.Path('/env/bin/python')
    pip = [sys.executable, '-m', 'pip', '--python', str(python)]
    assert _charm_requirements._pip(python, 'install', '--no-deps', 'a') == [
        *pip,
        'install',
        '--quiet',
        '--no-deps',
        'a',
    ]
    assert _charm_requirements._pip(python, 'uninstall', 'ops') == [
        *pip,
        'uninstall',
        '--quiet',
        '--yes',
        'ops',
    ]


def test_install_python_plugin_checks_the_requirements_are_complete(
    tmp_path: pathlib.Path, venv: pathlib.Path
):
    # charmcraft runs pip check after installing with --no-deps, so a
    # requirements file that's missing a dependency fails the pack.
    wheel = _wheel(tmp_path / 'wheels', 'needy', requires='missing')
    root = _charmcraft(
        tmp_path,
        'parts:\n  charm:\n    plugin: python\n    source: .\n'
        f'    python-packages: [wheels/{wheel}]\n',
    )
    with pytest.raises(_RequirementsError, match='missing'):
        _charm_requirements.install_charm_requirements(root, venv)


def test_install_refuses_the_tests_own_environment(tmp_path: pathlib.Path):
    root = _charmcraft(tmp_path, 'parts:\n  charm:\n    plugin: python\n')
    with pytest.raises(_RequirementsError, match="test's own environment"):
        _charm_requirements.install_charm_requirements(root, pathlib.Path(sys.executable))


def test_install_with_no_dependencies(tmp_path: pathlib.Path, venv: pathlib.Path):
    root = _charmcraft(tmp_path, 'parts:\n  charm:\n    plugin: python\n')
    _charm_requirements.install_charm_requirements(root, venv)
    assert _installed(venv) == []
