# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Install a charm's Python dependencies the way its build plugin would.

This follows what ``charmcraft pack`` does, so that a charm can be run in a
virtual environment with its own dependencies rather than the test's. Rather
than reading requirements files itself, it gives pip and uv the same
arguments that charmcraft does, from the same directory: the part's
``source`` and ``source-subdir``. Two plugins are supported:

* ``python``: ``pip install --no-deps`` with the part's
  ``python-constraints``, ``python-requirements`` and ``python-packages``. As
  with charmcraft's python plugin, the ``PYDEPS`` of the charm's libraries
  aren't included.
* ``uv``: what ``uv sync`` would install from the charm's ``uv.lock``, with
  the same options as charmcraft's uv plugin and the part's ``uv-extras``
  and ``uv-groups``. Unlike charmcraft, which uses the lockfile as it is, a
  ``uv.lock`` that's out of date with ``pyproject.toml`` is an error, so that
  the charm isn't tested with dependencies other than the ones it asks for.

The charm's own ``ops``, ``ops-scenario`` and ``ops-tracing`` are never left
installed: the charm uses the test's.

Charms that use an extension, such as ``flask-framework``, aren't supported:
the extension adds parts that aren't in ``charmcraft.yaml``. Nor are charms
with more than one part that installs Python dependencies.
"""

from __future__ import annotations

import dataclasses
import pathlib
import shlex
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from typing import Any, cast

import yaml

#: The build plugins that dependencies can be found for.
_SUPPORTED_PLUGINS = ('python', 'uv')
#: Plugins that are charmcraft's, but that dependencies can't be found for.
_UNSUPPORTED_PLUGINS = ('poetry', 'reactive')
#: Plugins that don't install Python dependencies, so are skipped when looking
#: for the part that does: craft-parts' built-in plugins, apart from the Python
#: ones above. A part using any other plugin might install Python dependencies,
#: so the charm is refused rather than given an environment that could be
#: missing some.
_OTHER_PLUGINS = (
    'ant', 'autotools', 'bazel', 'cargo-use', 'cmake', 'dotnet', 'dump', 'go', 'go-use',
    'gradle', 'gradle-use', 'jlink', 'make', 'maven', 'maven-use', 'meson', 'nil', 'npm',
    'npm-use', 'qmake', 'ruby', 'rust', 'scons',
)  # fmt: skip

#: The charm's environment never has these installed: the test's own are used.
#: ops-tracing pins an exact ops version, so it has to match the test's ops too.
_OPS_DISTRIBUTIONS = ('ops', 'ops-scenario', 'ops-tracing')


class _RequirementsError(Exception):
    """The charm's dependencies can't be found or installed."""


@dataclasses.dataclass(frozen=True)
class _Requirements:
    """What to install for a charm, as arguments for ``pip install --no-deps``."""

    directory: pathlib.Path
    """The part's build directory. Relative paths in ``args`` are relative to it."""

    args: tuple[str, ...]
    """Requirements and options, as separate command-line arguments."""

    check: bool = False
    """Whether to run ``pip check`` after installing, as charmcraft's python plugin does.

    The uv plugin's export leaves out ``ops``, so a locked package that
    depends on it would fail the check.
    """


def install_charm_requirements(charm_root: pathlib.Path, python: pathlib.Path) -> None:
    """Install the charm's dependencies into the environment that ``python`` runs in.

    The list of dependencies is complete, as it is for charmcraft, so they
    are installed without resolving dependencies. The charm's own ``ops``,
    ``ops-scenario`` and ``ops-tracing`` are then removed. The uv plugin's
    export already leaves them out, but removing them whatever the plugin
    keeps that true without relying on it.

    Raises:
        _RequirementsError: if the charm's dependencies can't be found (see
            :func:`charm_requirements`), installing them fails, or ``python``
            is the interpreter running the tests, whose ``ops`` would be
            removed.
    """
    if _prefix(python) == pathlib.Path(sys.prefix).resolve():
        raise _RequirementsError(
            "Refusing to install a charm's dependencies into the test's own environment."
        )
    requirements = charm_requirements(charm_root)
    if requirements.args:
        install = _pip(python, 'install', '--no-deps', *requirements.args)
        _run(install, cwd=requirements.directory)
        # Before ops is removed, which deliberately leaves dependencies missing.
        if requirements.check:
            _run(_pip(python, 'check'))
    _run(_pip(python, 'uninstall', *_OPS_DISTRIBUTIONS))


def _prefix(python: pathlib.Path) -> pathlib.Path:
    """The environment that ``python`` runs in.

    A virtual environment's interpreter is usually a symlink to the base one,
    so the interpreter's own path doesn't say which environment it is.
    """
    cmd = [str(python), '-c', 'import sys; print(sys.prefix)']
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise _RequirementsError(f'`{shlex.join(cmd)}` failed:\n{result.stderr.strip()}\n')
    return pathlib.Path(result.stdout.strip()).resolve()


def _pip(python: pathlib.Path, command: str, *args: str) -> list[str]:
    """A pip command for the environment that ``python`` runs in.

    uv is used if it's on PATH, because an environment that uv made has no
    pip. Otherwise, the test's own pip is used, as charmcraft does.
    """
    if uv := shutil.which('uv'):
        return [uv, 'pip', command, '--quiet', '--python', str(python), *args]
    # pip only accepts --python before the command.
    pip = [sys.executable, '-m', 'pip', '--python', str(python), command, '--quiet']
    return [*pip, '--yes', *args] if command == 'uninstall' else [*pip, *args]


def _run(cmd: Sequence[str], cwd: pathlib.Path | None = None) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    if result.returncode != 0:
        raise _RequirementsError(f'`{shlex.join(cmd)}` failed:\n{result.stderr.strip()}\n')


def charm_requirements(charm_root: pathlib.Path) -> _Requirements:
    """What the charm's build plugin would install.

    Raises:
        _RequirementsError: if the build plugin can't be found or isn't
            supported, a file the plugin names is missing, or ``uv export``
            fails.
    """
    plugin, part = detect_plugin(charm_root)
    directory = _build_directory(charm_root, part)
    if plugin == 'uv':
        return _Requirements(directory, _uv_requirements(directory, part))
    return _Requirements(directory, _python_requirements(directory, part), check=True)


def detect_plugin(charm_root: pathlib.Path) -> tuple[str, Mapping[str, Any]]:
    """Find the charm's build plugin, and the ``charmcraft.yaml`` part that uses it.

    Raises:
        _RequirementsError: if there's no ``charmcraft.yaml`` or it can't be
            read, or the plugin isn't supported. That includes the deprecated
            ``charm`` plugin, which charmcraft uses when ``charmcraft.yaml``
            has no ``parts``, charms that use an extension, and charms with
            more than one part that installs Python dependencies.
    """
    path = charm_root / 'charmcraft.yaml'
    try:
        charmcraft: Any = yaml.safe_load(path.read_text()) or {}
    except FileNotFoundError:
        raise _RequirementsError(
            f'{charm_root} has no charmcraft.yaml, so its build plugin is unknown.'
        ) from None
    except (OSError, yaml.YAMLError) as e:
        raise _RequirementsError(f'Could not read {path}: {e}') from None
    if not isinstance(charmcraft, dict):
        raise _RequirementsError(f'{path} is not a mapping.')
    charmcraft = cast('dict[str, Any]', charmcraft)
    if extensions := charmcraft.get('extensions'):
        # The extension adds or changes the charm part, and its plugin
        # depends on the base.
        raise _RequirementsError(
            f'{path} uses the {", ".join(map(str, extensions))} extension, which adds '
            "parts that aren't in charmcraft.yaml, so finding the charm's dependencies "
            "isn't supported."
        )
    parts: Any = charmcraft.get('parts')
    if not parts:
        raise _charm_plugin(f'{path} has no parts')
    if not isinstance(parts, dict):
        raise _RequirementsError(f'parts in {path} is not a mapping.')
    return _python_part(path, cast('dict[str, Any]', parts))


def _python_part(path: pathlib.Path, parts: dict[str, Any]) -> tuple[str, Mapping[str, Any]]:
    """The one part that installs Python dependencies, and its plugin.

    Every part is checked, because charmcraft builds them all.
    """
    found: list[tuple[str, str, Mapping[str, Any]]] = []
    unknown: list[str] = []
    for name, part in parts.items():
        # A part with no keys at all is null in YAML.
        part = cast('dict[str, Any]', {} if part is None else part)
        if not isinstance(part, dict):
            raise _RequirementsError(f'Part {name!r} in {path} is not a mapping.')
        plugin = part.get('plugin', name)
        if plugin in _SUPPORTED_PLUGINS:
            found.append((name, plugin, part))
        elif plugin == 'charm':
            raise _charm_plugin(f'Part {name!r} in {path} uses the charm plugin')
        elif plugin in _UNSUPPORTED_PLUGINS:
            raise _RequirementsError(
                f'Part {name!r} in {path} uses the {plugin} plugin: {_unsupported(plugin)}'
            )
        elif plugin not in _OTHER_PLUGINS:
            unknown.append(f'{name} ({plugin})')
    if unknown:
        raise _RequirementsError(
            f"Can't find the dependencies of the charm in {path}, because these parts use "
            f'plugins that might install Python dependencies too: {", ".join(unknown)}.'
        )
    if len(found) > 1:
        names = ', '.join(f'{name} ({plugin})' for name, plugin, _ in found)
        raise _RequirementsError(
            f'More than one part in {path} installs Python dependencies: {names}. '
            "Finding the dependencies of a charm with more than one isn't supported."
        )
    if found:
        _, plugin, part = found[0]
        return plugin, part
    raise _RequirementsError(f'No part in {path} uses the python or uv plugin.')


def _unsupported(plugin: str) -> str:
    return f"finding the dependencies of a charm built with the {plugin} plugin isn't supported."


def _charm_plugin(reason: str) -> _RequirementsError:
    return _RequirementsError(
        f"{reason}, so it's built with the charm plugin, which is deprecated and "
        "isn't supported. Move the charm to the uv or python plugin."
    )


def _build_directory(charm_root: pathlib.Path, part: Mapping[str, Any]) -> pathlib.Path:
    """The directory charmcraft builds the part in: its ``source`` and ``source-subdir``.

    A ``source`` may lead out of the charm, up to the root of the git repository
    it's in: charmcraft's experimental monorepo mode mounts the whole repository,
    and its documentation has charms use ``source: ../..`` with a
    ``source-subdir`` back to the charm. Nothing outside the repository is ever
    available to charmcraft, so that's refused.
    """
    source = str(part.get('source', '.'))
    if '://' in source or source.startswith('git@'):
        raise _RequirementsError(
            f"The part's source, {source}, isn't a local directory, so finding the "
            "charm's dependencies isn't supported."
        )
    directory = (charm_root / source / str(part.get('source-subdir', ''))).resolve()
    if not directory.is_relative_to(_repository_root(charm_root.resolve())):
        raise _RequirementsError(
            f"The part's source is {directory}, which is outside the charm's git repository, "
            "so charmcraft can't build it."
        )
    if not directory.is_dir():
        raise _RequirementsError(
            f"The part's source is {directory}, which isn't a directory, so finding the "
            "charm's dependencies isn't supported."
        )
    return directory


def _repository_root(charm_root: pathlib.Path) -> pathlib.Path:
    """The root of the git repository the charm is in, or the charm itself if it isn't in one."""
    for directory in (charm_root, *charm_root.parents):
        if (directory / '.git').exists():
            return directory
    return charm_root


def _python_requirements(directory: pathlib.Path, part: Mapping[str, Any]) -> tuple[str, ...]:
    """The arguments charmcraft's ``python`` plugin passes to ``pip install --no-deps``."""
    constraints = _list(part, 'python-constraints')
    requirements = _list(part, 'python-requirements')
    packages = _list(part, 'python-packages')
    for name, kind in [(c, 'constraints') for c in constraints] + [
        (r, 'requirements') for r in requirements
    ]:
        if not (directory / name).is_file():
            raise _RequirementsError(
                f'The python plugin lists {name} as a {kind} file, but there is no '
                f'{directory / name}.'
            )
    return (
        *(f'--constraint={name}' for name in constraints),
        *(f'--requirement={name}' for name in requirements),
        *packages,
    )


def _list(part: Mapping[str, Any], key: str) -> list[str]:
    """A list option of the part, which is empty if it isn't set."""
    value = part.get(key, [])
    if not isinstance(value, list):
        raise _RequirementsError(f'{key} in charmcraft.yaml is not a list.')
    return [str(item) for item in cast('list[Any]', value)]


def _uv_requirements(directory: pathlib.Path, part: Mapping[str, Any]) -> tuple[str, ...]:
    """The requirements ``uv export`` gives from the charm's lockfile."""
    extras = _list(part, 'uv-extras')
    groups = _list(part, 'uv-groups')
    if not (directory / 'uv.lock').exists():
        raise _RequirementsError(
            f'{directory} is built with the uv plugin but has no uv.lock. Run `uv lock` in it.'
        )
    uv = shutil.which('uv')
    if uv is None:
        raise _RequirementsError(
            "uv is not on PATH, and it's needed to export the requirements from the "
            "charm's uv.lock. Install uv (https://docs.astral.sh/uv/)."
        )
    cmd = [
        uv,
        'export',
        # charmcraft uses the lockfile as it is (UV_FROZEN), but testing with a stale
        # lockfile would test the charm with dependencies it no longer asks for.
        '--locked',
        '--no-hashes',
        '--no-header',
        '--no-annotate',
        '--format',
        'requirements-txt',
        # The options charmcraft's uv plugin passes to `uv sync`.
        '--no-dev',
        '--no-editable',
        # charmcraft passes `--no-install-project`: the charm's code is copied, not installed.
        '--no-emit-project',
        *(arg for name in _OPS_DISTRIBUTIONS for arg in ('--no-emit-package', name)),
        *(arg for extra in extras for arg in ('--extra', extra)),
        *(arg for group in groups for arg in ('--group', group)),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=directory)
    if result.returncode != 0:
        output = result.stderr.strip()
        if '--locked' in output or 'needs to be updated' in output:
            raise _RequirementsError(
                f'The uv.lock in {directory} is out of date with its pyproject.toml. '
                'Run `uv lock` in it.'
            )
        raise _RequirementsError(f'`uv export` failed in {directory}:\n{output}\n')
    # Each line is one requirement, with any path relative to the directory.
    return tuple(
        arg
        for line in result.stdout.splitlines()
        if line.strip() and not line.lstrip().startswith('#')
        for arg in (shlex.split(line) if line.startswith('-') else [line.strip()])
    )
