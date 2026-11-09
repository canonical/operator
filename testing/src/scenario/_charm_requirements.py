# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Find a charm's Python dependencies from its build plugin.

This reads the dependencies the way ``charmcraft pack`` would, so that a charm
can be run in a virtual environment with its own dependencies rather than the
test's. Two plugins are supported:

* ``python``: the ``python-requirements`` files, ``python-packages`` and
  ``python-constraints``. As with charmcraft's python plugin, the ``PYDEPS``
  of the charm's libraries aren't included.
* ``uv``: what ``uv sync`` would install from the charm's ``uv.lock``, with
  the same options as charmcraft's uv plugin and the part's ``uv-extras``
  and ``uv-groups``. Unlike charmcraft, which uses the lockfile as it is, a
  ``uv.lock`` that's out of date with ``pyproject.toml`` is an error, so that
  the charm isn't tested with dependencies other than the ones it asks for.

Charms that use an extension, such as ``flask-framework``, aren't supported:
the extension adds parts that aren't in ``charmcraft.yaml``.

The result is one flat list of requirements, with relative paths made
absolute, so that it can be installed from anywhere.
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
from collections.abc import Iterable, Mapping
from typing import Any, cast

import yaml

#: The build plugins that dependencies can be found for.
_SUPPORTED_PLUGINS = ('python', 'uv')
#: Plugins that are charmcraft's, but that dependencies can't be found for.
_UNSUPPORTED_PLUGINS = ('poetry', 'reactive')
#: Plugins that don't install Python dependencies, so are skipped when looking
#: for the part that does.
_OTHER_PLUGINS = ('nil', 'dump', 'make', 'autotools', 'cmake', 'go', 'rust', 'npm')

#: The charm's environment never has these installed: the test's own are used.
#: ops-tracing pins an exact ops version, so it has to match the test's ops too.
_OPS_DISTRIBUTIONS = ('ops', 'ops-scenario', 'ops-tracing')

_REQUIREMENT_NAME = re.compile(r'^\s*([A-Za-z0-9][A-Za-z0-9._-]*)')
_EGG_NAME = re.compile(r'#(?:.*&)?egg=([A-Za-z0-9][A-Za-z0-9._-]*)')
# pip also accepts these options with the value attached, as in ``-rbase.txt``.
_ATTACHED_SHORT_OPTION = re.compile(r'^(-[rcef])(?=[^\s=])')
_HASH_OPTION = re.compile(r'\s--hash[=\s]\S+')


class _RequirementsError(RuntimeError):
    """The charm's dependencies can't be found."""


def charm_requirements(charm_root: pathlib.Path) -> list[str]:
    """The charm's dependencies, one requirement or option per entry.

    ``ops``, ``ops-scenario`` and ``ops-tracing`` are left out, as are
    repeats. The list is complete, as it is for charmcraft, so install it
    without resolving dependencies (``--no-deps``).

    Raises:
        _RequirementsError: if the build plugin can't be found or isn't
            supported, a file the plugin names is missing, or ``uv export``
            fails.
    """
    plugin, part = detect_plugin(charm_root)
    if plugin == 'uv':
        requirements = _uv_requirements(charm_root, part)
    else:
        requirements = _python_requirements(charm_root, part)
    return _deduplicated(requirements)


def detect_plugin(charm_root: pathlib.Path) -> tuple[str, Mapping[str, Any]]:
    """Find the charm's build plugin, and the ``charmcraft.yaml`` part that uses it.

    The first part whose plugin installs Python dependencies is the one
    used.

    Raises:
        _RequirementsError: if there's no ``charmcraft.yaml`` or it can't be
            read, or the plugin isn't supported. That includes the deprecated
            ``charm`` plugin, which charmcraft uses when ``charmcraft.yaml``
            has no ``parts``, and charms that use an extension, unless one of
            their own parts sets the python or uv plugin.
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
    parts: Any = charmcraft.get('parts')
    if parts and not isinstance(parts, dict):
        raise _RequirementsError(f'parts in {path} is not a mapping.')
    try:
        return _python_part(path, parts)
    except _RequirementsError:
        if extensions := charmcraft.get('extensions'):
            # The part that the extension adds, or changes, decides the plugin.
            raise _RequirementsError(
                f'{path} uses the {", ".join(map(str, extensions))} extension, which adds '
                "parts that aren't in charmcraft.yaml, so finding the charm's dependencies "
                "isn't supported."
            ) from None
        raise


def _python_part(path: pathlib.Path, parts: Any) -> tuple[str, Mapping[str, Any]]:
    if not parts:
        raise _charm_plugin(f'{path} has no parts')
    unknown: list[str] = []
    for name, part in cast('dict[str, Any]', parts).items():
        # A part with no keys at all is null in YAML.
        part = cast('dict[str, Any]', {} if part is None else part)
        if not isinstance(part, dict):
            raise _RequirementsError(f'Part {name!r} in {path} is not a mapping.')
        plugin = part.get('plugin', name)
        if plugin in _SUPPORTED_PLUGINS:
            return plugin, part
        if plugin == 'charm':
            raise _charm_plugin(f'Part {name!r} in {path} uses the charm plugin')
        if plugin in _UNSUPPORTED_PLUGINS:
            raise _RequirementsError(
                f'Part {name!r} in {path} uses the {plugin} plugin: {_unsupported(plugin)}'
            )
        if plugin not in _OTHER_PLUGINS:
            unknown.append(f'{name} ({plugin})')
    found = f' Its parts use: {", ".join(unknown)}.' if unknown else ''
    raise _RequirementsError(f'No part in {path} uses the python or uv plugin.{found}')


def _unsupported(plugin: str) -> str:
    return f"finding the dependencies of a charm built with the {plugin} plugin isn't supported."


def _charm_plugin(reason: str) -> _RequirementsError:
    return _RequirementsError(
        f"{reason}, so it's built with the charm plugin, which is deprecated and "
        "isn't supported. Move the charm to the uv or python plugin."
    )


def _python_requirements(charm_root: pathlib.Path, part: Mapping[str, Any]) -> list[str]:
    """The requirements the ``python`` plugin would install."""
    requirements: list[str] = []
    for name in _list(charm_root, part, 'python-requirements'):
        requirements.extend(read_requirements(_listed_file(charm_root, name, 'requirements')))
    requirements.extend(_list(charm_root, part, 'python-packages'))
    for name in _list(charm_root, part, 'python-constraints'):
        requirements.append(f'-c {_listed_file(charm_root, name, "constraints")}')
    return requirements


def _list(charm_root: pathlib.Path, part: Mapping[str, Any], key: str) -> list[str]:
    """A list option of the part, which is empty if it isn't set."""
    value = part.get(key, [])
    if not isinstance(value, list):
        raise _RequirementsError(f'{key} in {charm_root / "charmcraft.yaml"} is not a list.')
    return [str(item) for item in cast('list[Any]', value)]


def _listed_file(charm_root: pathlib.Path, name: str, kind: str) -> pathlib.Path:
    path = charm_root / name
    if not path.is_file():
        raise _RequirementsError(
            f'The python plugin lists {name} as a {kind} file, but there is no {path}.'
        )
    return path.resolve()


def _uv_requirements(charm_root: pathlib.Path, part: Mapping[str, Any]) -> list[str]:
    """The requirements ``uv export`` gives from the charm's lockfile."""
    if not (charm_root / 'uv.lock').exists():
        raise _RequirementsError(
            f'{charm_root} is built with the uv plugin but has no uv.lock. Run `uv lock` in it.'
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
        '--format',
        'requirements-txt',
        '--directory',
        str(charm_root),
        # The options charmcraft's uv plugin passes to `uv sync`.
        '--no-dev',
        '--no-editable',
        # charmcraft passes `--no-install-project`: the charm's code is copied, not installed.
        '--no-emit-project',
    ]
    for extra in _list(charm_root, part, 'uv-extras'):
        cmd += ['--extra', extra]
    for group in _list(charm_root, part, 'uv-groups'):
        cmd += ['--group', group]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        output = result.stderr.strip()
        if '--locked' in output or 'needs to be updated' in output:
            raise _RequirementsError(
                f'The uv.lock in {charm_root} is out of date with its pyproject.toml. '
                'Run `uv lock` in it.'
            )
        raise _RequirementsError(f'`uv export` failed in {charm_root}:\n{output}\n')
    # uv writes path dependencies relative to the project.
    return _parse_requirements(result.stdout, base=charm_root)


def read_requirements(
    path: pathlib.Path, *, seen: frozenset[pathlib.Path] = frozenset()
) -> list[str]:
    """Read a requirements file into a flat list, one requirement or option per entry.

    Included files (``-r``) are read in place. Hashes are dropped, because
    requirements from several files are installed together, and pip refuses
    a mix of requirements with and without hashes. Relative paths are made
    absolute against the file's directory, so that the list can be installed
    from anywhere.
    """
    path = path.resolve()
    return _parse_requirements(path.read_text(), base=path.parent, seen=seen | {path})


def _parse_requirements(
    text: str, *, base: pathlib.Path, seen: frozenset[pathlib.Path] = frozenset()
) -> list[str]:
    """Parse requirements file content, with relative paths resolved against ``base``."""
    lines = text.replace('\\\n', ' ').splitlines()
    requirements: list[str] = []
    for line in lines:
        line = re.sub(r'(^|\s)#.*$', '', line).strip()
        line = _HASH_OPTION.sub('', f' {line}').strip()
        if not line:
            continue
        line = _ATTACHED_SHORT_OPTION.sub(r'\1 ', line)
        option, _, value = line.partition(' ')
        if '=' in option and option.startswith('--'):
            option, _, value = option.partition('=')
        value = value.strip()
        if option in ('-r', '--requirement'):
            included = (base / value).resolve()
            if included not in seen:
                requirements.extend(read_requirements(included, seen=seen))
        elif option in ('-c', '--constraint', '-e', '--editable', '-f', '--find-links'):
            requirements.append(f'{option} {_absolute_location(value, base)}')
        elif line.startswith('-'):
            requirements.append(line)
        else:
            requirements.append(_absolute(line, base))
    return requirements


def _absolute_location(location: str, base: pathlib.Path) -> str:
    """Make an option's value absolute if it's a relative path rather than a URL."""
    if ':' in location or pathlib.PurePath(location).is_absolute():
        return location
    return str((base / location).resolve())


def _absolute(requirement: str, base: pathlib.Path) -> str:
    """Make a requirement that is a relative path, or names one, absolute."""
    if requirement.startswith(('./', '../', '.\\', '..\\')) or requirement == '.':
        return str((base / requirement).resolve())
    name, at, location = requirement.partition(' @ ')
    if at and location.startswith(('./', '../')):
        return f'{name} @ {(base / location).resolve().as_uri()}'
    return requirement


def _canonical_name(requirement: str) -> str | None:
    """The distribution a requirement names, if it names one.

    An editable requirement only names one in its ``#egg=`` fragment.
    """
    if requirement.startswith('-'):
        option, _, value = requirement.partition(' ')
        if option not in ('-e', '--editable'):
            return None
        match = _EGG_NAME.search(value)
    else:
        match = _REQUIREMENT_NAME.match(requirement)
    if match is None:
        return None
    return re.sub(r'[-_.]+', '-', match.group(1)).lower()


def _deduplicated(requirements: Iterable[str]) -> list[str]:
    """Drop repeats, and the charm's own ``ops``, ``ops-scenario`` and ``ops-tracing``."""
    seen: set[str] = set()
    result: list[str] = []
    for requirement in requirements:
        if requirement in seen:
            continue
        seen.add(requirement)
        if _canonical_name(requirement) in _OPS_DISTRIBUTIONS:
            continue
        result.append(requirement)
    return result
