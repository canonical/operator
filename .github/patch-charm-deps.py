#!/usr/bin/env -S uv run --script --no-project
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "tomli-w~=1.2.0",
# ]
# ///
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.
"""Patch charm dependencies to use ops 3.x for compatibility testing.

This script handles multiple dependency management systems (pip, Poetry, uv)
and updates them to use the specified version of ops and ops-scenario.

Usage: patch-charm-deps.py <ops-wheel> <ops-scenario-wheel> [<ops-tracing-wheel>]
"""

from __future__ import annotations

import argparse
import configparser
import copy
import re
import subprocess
import sys
from pathlib import Path

import tomli_w
import tomllib

# Manage the Python version in tox


def get_tox_config_path(charm_root: Path) -> Path | None:
    """Find tox configuration file (tox.toml or tox.ini).

    Returns:
        Path to tox config file, or None if not found
    """
    tox_toml = charm_root / 'tox.toml'
    if tox_toml.exists():
        return tox_toml

    tox_ini = charm_root / 'tox.ini'
    if tox_ini.exists():
        return tox_ini

    return None


def _update_tox_python_version_ini(tox_config: Path, charm_root: Path) -> None:
    """Update Python version in tox.ini configuration.

    Args:
        tox_config: Path to tox.ini file
        charm_root: Root directory of charm (for relative path display)
    """
    config = configparser.ConfigParser()
    config.read(tox_config)
    modified = False

    for section in config.sections():
        # Update basepython to use python3.10 if it's set to 3.8 or 3.9
        if config.get(section, 'basepython', fallback=None) in ('python3.8', 'python3.9'):
            config.set(section, 'basepython', 'python3.10')
            modified = True

        # Update envlist to replace py38/py39 with py310
        # Only replace if py310 doesn't already exist to avoid duplicates.
        if config.has_option(section, 'envlist'):
            envlist = config.get(section, 'envlist')
            new_envlist = envlist
            if 'py310' not in envlist:
                new_envlist = new_envlist.replace('py38', 'py310').replace('py39', 'py310')
            else:
                # py310 already exists, just remove py38/py39 references.
                new_envlist = re.sub(r'\bpy38\b,?\s*', '', new_envlist)
                new_envlist = re.sub(r'\bpy39\b,?\s*', '', new_envlist)
                new_envlist = re.sub(r'\{py38\},?\s*', '', new_envlist)
                new_envlist = re.sub(r'\{py39\},?\s*', '', new_envlist)
                # Clean up any trailing commas or whitespace.
                new_envlist = re.sub(r',\s*$', '', new_envlist)
                new_envlist = re.sub(r',\s*\n', '\n', new_envlist)
            if new_envlist != envlist:
                config.set(section, 'envlist', new_envlist)
                modified = True

    if modified:
        with open(tox_config, 'w') as f:
            config.write(f)
        print(f'  ✓ Updated {tox_config.relative_to(charm_root)}')


def _update_tox_python_version_toml(tox_config: Path, charm_root: Path) -> None:
    """Update Python version in tox.toml configuration.

    Args:
        tox_config: Path to tox.toml file
        charm_root: Root directory of charm (for relative path display)
    """
    with open(tox_config, 'rb') as f:
        original = tomllib.load(f)
    data = copy.deepcopy(original)

    def _update_section(section_data: dict) -> None:
        """Update basepython and envlist in a single tox section."""
        if section_data.get('basepython') in ('python3.8', 'python3.9'):
            section_data['basepython'] = 'python3.10'

        if 'envlist' not in section_data:
            return
        envlist = section_data['envlist']
        if isinstance(envlist, list):
            has_py310 = any('py310' in str(e) for e in envlist)
            if not has_py310:
                envlist = [
                    str(e).replace('py38', 'py310').replace('py39', 'py310') for e in envlist
                ]
            else:
                envlist = [e for e in envlist if not re.search(r'py3[89]', str(e))]
            section_data['envlist'] = envlist
        elif isinstance(envlist, str):
            if 'py310' not in envlist:
                section_data['envlist'] = envlist.replace('py38', 'py310').replace('py39', 'py310')
            else:
                envs = [e for e in envlist.split(',') if not re.search(r'py3[89]', e)]
                section_data['envlist'] = ','.join(envs)

    # Update top-level, env_run_base, and individual envs.
    _update_section(data)
    if 'env_run_base' in data:
        _update_section(data['env_run_base'])
    if 'env' in data:
        for env_data in data['env'].values():
            _update_section(env_data)

    if data != original:
        with open(tox_config, 'wb') as f:
            tomli_w.dump(data, f)
        print(f'  ✓ Updated {tox_config.relative_to(charm_root)}')


def update_tox_python_version(tox_config: Path, charm_root: Path) -> None:
    """Update Python version in tox configuration (tox.ini or tox.toml).

    Args:
        tox_config: Path to tox configuration file
        charm_root: Root directory of charm (for relative path display)
    """
    if tox_config.suffix == '.ini':
        _update_tox_python_version_ini(tox_config, charm_root)
    elif tox_config.suffix == '.toml':
        _update_tox_python_version_toml(tox_config, charm_root)


# Manage requires-python and .python-version


def update_pyproject_python_version(pyproject: Path, charm_root: Path) -> None:
    """Update requires-python in pyproject.toml.

    Args:
        pyproject: Path to pyproject.toml
        charm_root: Root directory of charm (for relative path display)
    """
    data = tomllib.loads(pyproject.read_text())

    requires_python = data.get('project', {}).get('requires-python')
    if requires_python is None:
        return

    if re.match(r'>=3\.[89]', requires_python):
        new_requires = '>=3.10'
    else:
        return

    data['project']['requires-python'] = new_requires
    pyproject.write_text(tomli_w.dumps(data))
    print(f'  ✓ Updated {pyproject.relative_to(charm_root)}')

    # If a uv.lock exists, update it to reflect the new requires-python
    uv_lock = charm_root / 'uv.lock'
    if uv_lock.exists():
        print('  Updating uv.lock after requires-python change...')
        result = subprocess.run(
            ['uv', 'lock', '--python-preference', 'system'],
            cwd=charm_root,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f'  ✗ Failed to update uv.lock: {result.stderr.strip()}')
            sys.exit(1)
        print('  ✓ Updated uv.lock')


def update_python_version_file(python_version_file: Path, charm_root: Path) -> None:
    """Update .python-version file.

    Args:
        python_version_file: Path to .python-version
        charm_root: Root directory of charm (for relative path display)
    """
    content = python_version_file.read_text().strip()
    # Use fullmatch with explicit minor versions to avoid matching 3.80, 3.81, etc.
    if re.fullmatch(r'3\.(8|9)(\.\d+)?', content):
        new_version = '3.10'
        python_version_file.write_text(new_version + '\n')
        print(f'  ✓ Updated {python_version_file.relative_to(charm_root)} to {new_version}')


# Pull it all together to update the Python version.


def update_python_version_requirements(charm_root: Path) -> None:
    """Update Python version requirements to >=3.10.

    Args:
        charm_root: Root directory of the charm
    """
    print('\nUpdating Python version requirements...')

    # Update tox.ini or tox.toml
    tox_config = get_tox_config_path(charm_root)
    if tox_config:
        update_tox_python_version(tox_config, charm_root)

    # Update pyproject.toml requires-python
    pyproject = charm_root / 'pyproject.toml'
    if pyproject.exists():
        update_pyproject_python_version(pyproject, charm_root)

    # Update .python-version
    python_version_file = charm_root / '.python-version'
    if python_version_file.exists():
        update_python_version_file(python_version_file, charm_root)


# Adjust tox to install the version of ops[...] that we want.

# Commands that install a charm's locked dependencies into the tox environment,
# and would put the locked ops back over the wheel if they ran after it.
_LOCKED_INSTALL_RE = re.compile(r'^\s*(poetry install|uv sync)\b')


def _wheel_install_commands(ops_wheel: str, ops_scenario_wheel: str) -> list[list[str]]:
    """Commands that force-install the ops wheels into the tox environment.

    These use uv rather than pip: an environment that tox-uv creates has no pip
    of its own, so a bare `pip` would be the system one, installing the wheels
    outside the environment. tox sets VIRTUAL_ENV for its commands, which is
    where `uv pip` installs. Dependencies are installed as well, since a charm
    locked to an older ops won't have everything the new one needs.
    """
    return [
        [
            'uv',
            'pip',
            'install',
            '--reinstall-package',
            'ops',
            '--reinstall-package',
            'ops-scenario',
            ops_wheel,
            ops_scenario_wheel,
        ]
    ]


def _insert_after_locked_installs_ini(commands: str, new_lines: list[str]) -> str:
    """Insert new_lines after the last locked install in an INI commands value."""
    lines = commands.split('\n')
    last = None
    i = 0
    while i < len(lines):
        first = i
        while lines[i].rstrip().endswith('\\') and i + 1 < len(lines):
            i += 1
        if _LOCKED_INSTALL_RE.match(lines[first]):
            last = i
        i += 1
    if last is None:
        return commands
    return '\n'.join(lines[: last + 1] + new_lines + lines[last + 1 :])


def _insert_after_locked_installs_toml(
    commands: list[list[str]], new_commands: list[list[str]]
) -> list[list[str]]:
    """Insert new_commands after the last locked install in a TOML commands list."""
    last = None
    for i, command in enumerate(commands):
        if isinstance(command, list) and _LOCKED_INSTALL_RE.match(' '.join(map(str, command))):
            last = i
    if last is None:
        return commands
    return commands[: last + 1] + new_commands + commands[last + 1 :]


def add_tox_pip_commands_ini(
    tox_ini_path: Path, section: str, ops_wheel: str, ops_scenario_wheel: str
) -> None:
    """Add commands to force-reinstall the ops wheels to a tox.ini section.

    The wheels are installed in commands_pre, and again after any command that
    installs the charm's locked dependencies, such as `poetry install`.

    Args:
        tox_ini_path: Path to tox.ini
        section: Section name (e.g., "testenv:unit" or "testenv")
        ops_wheel: Path to ops wheel file
        ops_scenario_wheel: Path to ops-scenario wheel file
    """
    config = configparser.ConfigParser()
    config.read(tox_ini_path)

    if not config.has_section(section):
        print(f'  Section [{section}] not found in tox.ini, skipping')
        return

    print(f'  Adding uv to allowlist_externals and commands_pre in [{section}]')

    if config.has_option(section, 'allowlist_externals'):
        allowlist = config.get(section, 'allowlist_externals')
        if 'uv' not in allowlist.split():
            print('    Found existing allowlist_externals, appending uv')
            config.set(section, 'allowlist_externals', allowlist + '\n    uv')
    else:
        print('    Creating new allowlist_externals with uv')
        config.set(section, 'allowlist_externals', 'uv')

    new_lines = [
        f'    {" ".join(command)}'
        for command in _wheel_install_commands(ops_wheel, ops_scenario_wheel)
    ]
    print("    Adding commands_pre to force-reinstall ops 3.x (using 'uv pip install')")
    existing = config.get(section, 'commands_pre', fallback='')
    config.set(section, 'commands_pre', existing + '\n' + '\n'.join(new_lines))

    if config.has_option(section, 'commands'):
        commands = config.get(section, 'commands')
        patched = _insert_after_locked_installs_ini(commands, new_lines)
        if patched != commands:
            print('    Reinstalling the wheels after the locked install in commands')
            config.set(section, 'commands', patched)

    with open(tox_ini_path, 'w') as f:
        config.write(f)


def _patch_tox_testenv_sections_toml(
    tox_config: Path, ops_wheel: str, ops_scenario_wheel: str
) -> bool:
    """Patch all testenv sections in tox.toml.

    Args:
        tox_config: Path to tox.toml
        ops_wheel: Path to ops wheel file
        ops_scenario_wheel: Path to ops-scenario wheel file

    Returns:
        True if any sections were patched, False otherwise
    """
    with open(tox_config, 'rb') as f:
        data = tomllib.load(f)

    # Patch env_run_base (equivalent to [testenv]).
    if 'env_run_base' in data:
        add_tox_pip_commands_toml(tox_config, 'testenv', ops_wheel, ops_scenario_wheel)

    # Patch specific envs.
    if 'env' in data:
        for env_name in data['env']:
            add_tox_pip_commands_toml(
                tox_config, f'testenv:{env_name}', ops_wheel, ops_scenario_wheel
            )

    return True


def _patch_tox_testenv_sections_ini(
    tox_config: Path, ops_wheel: str, ops_scenario_wheel: str
) -> bool:
    """Patch all testenv sections in tox.ini.

    Args:
        tox_config: Path to tox.ini
        ops_wheel: Path to ops wheel file
        ops_scenario_wheel: Path to ops-scenario wheel file

    Returns:
        True if any sections were patched, False otherwise
    """
    config = configparser.ConfigParser()
    config.read(tox_config)

    # Find all testenv sections.
    testenv_sections = [s for s in config.sections() if s.startswith('testenv')]
    if not testenv_sections:
        return False

    for section in testenv_sections:
        add_tox_pip_commands_ini(tox_config, section, ops_wheel, ops_scenario_wheel)

    return True


def patch_tox_testenv_sections(charm_root: Path, ops_wheel: str, ops_scenario_wheel: str) -> bool:
    """Patch all testenv sections in tox.ini or tox.toml.

    Returns:
        True if any sections were patched, False otherwise
    """
    tox_config = get_tox_config_path(charm_root)
    if not tox_config:
        return False

    if tox_config.suffix == '.toml':
        return _patch_tox_testenv_sections_toml(tox_config, ops_wheel, ops_scenario_wheel)

    return _patch_tox_testenv_sections_ini(tox_config, ops_wheel, ops_scenario_wheel)


def add_tox_pip_commands_toml(
    tox_toml_path: Path, section: str, ops_wheel: str, ops_scenario_wheel: str
) -> None:
    """Add commands to force-reinstall the ops wheels to a tox.toml section.

    The wheels are installed in commands_pre, and again after any command that
    installs the charm's locked dependencies, such as `poetry install`.

    Args:
        tox_toml_path: Path to tox.toml
        section: Section name (e.g., "testenv:unit" or "testenv")
        ops_wheel: Path to ops wheel file
        ops_scenario_wheel: Path to ops-scenario wheel file
    """
    with open(tox_toml_path, 'rb') as f:
        data = tomllib.load(f)

    # Convert section name format: testenv:unit -> env.unit, testenv -> env_run_base
    if section == 'testenv':
        section_keys = ['env_run_base']
    elif section.startswith('testenv:'):
        env_name = section.split(':', 1)[1]
        section_keys = ['env', env_name]
    else:
        print(f'  Unknown section format: {section}, skipping')
        return

    # Navigate to the target section.
    current = data
    for key in section_keys:
        if key not in current:
            toml_section = '.'.join(section_keys)
            print(f'  Section {toml_section} not found in tox.toml, skipping')
            return
        current = current[key]

    toml_section = '.'.join(section_keys)
    print(f'  Adding uv to allowlist_externals and commands_pre in [{toml_section}]')

    if 'allowlist_externals' not in current:
        print('    Creating new allowlist_externals with uv')
        current['allowlist_externals'] = ['uv']
    elif 'uv' not in current['allowlist_externals']:
        print('    Found existing allowlist_externals, appending uv')
        current['allowlist_externals'].append('uv')

    # tox 4 TOML format requires a list of lists for commands.
    new_commands = _wheel_install_commands(ops_wheel, ops_scenario_wheel)
    print("    Adding commands_pre to force-reinstall ops 3.x (using 'uv pip install')")
    existing = current.get('commands_pre')
    current['commands_pre'] = (existing if isinstance(existing, list) else []) + new_commands

    commands = current.get('commands')
    if isinstance(commands, list):
        patched = _insert_after_locked_installs_toml(commands, new_commands)
        if patched != commands:
            print('    Reinstalling the wheels after the locked install in commands')
            current['commands'] = patched

    with open(tox_toml_path, 'wb') as f:
        tomli_w.dump(data, f)


def _is_ops_dependency_line(line: str) -> bool:
    """Check if a line is an ops or ops-scenario dependency.

    Args:
        line: A line from a requirements file

    Returns:
        True if the line is an ops dependency that should be removed
    """
    if re.match(r'^ops[ ><=]', line):
        return True
    if 'canonical/operator' in line:
        return True
    if '#egg=ops' in line:
        return True
    if re.match(r'^ops-scenario[ ><=]', line):
        return True
    if re.match(r'^ops\[testing\][ ><=]', line):
        return True
    return False


def patch_requirements_txt(charm_root: Path, ops_wheel: str, ops_scenario_wheel: str) -> bool:
    """Patch requirements.txt-based charm dependencies.

    Returns:
        True if any files were patched, False otherwise
    """
    print('✓ Found requirements.txt-based charm')
    updated = False

    # Find all requirements files using glob.
    req_files = list(charm_root.glob('*requirements*.txt'))
    for req_file in req_files:
        print(f'  Patching {req_file.name}')
        content = req_file.read_text()

        # Remove existing ops and ops-scenario entries.
        lines = [line for line in content.split('\n') if not _is_ops_dependency_line(line)]

        # Add wheel paths.
        lines.extend(['', ops_wheel, '', ops_scenario_wheel])

        req_file.write_text('\n'.join(lines))
        print(f'    ✓ Updated {req_file.name} with ops 3.x')
        updated = True

    # Also patch inline deps in tox config if present.
    tox_config = get_tox_config_path(charm_root)
    if not tox_config or tox_config.suffix != '.ini':
        return updated

    config = configparser.ConfigParser()
    config.read(tox_config)

    modified = False
    for section in config.sections():
        if not config.has_option(section, 'deps'):
            continue

        deps = config.get(section, 'deps')
        # Remove ops and ops-scenario deps using the helper function.
        deps_lines = [stripped for line in deps.splitlines() if (stripped := line.strip())]
        new_deps_lines = [dep for dep in deps_lines if not _is_ops_dependency_line(dep)]
        if deps_lines == new_deps_lines:
            continue

        print('  Found inline ops deps in tox.ini, patching...')
        new_deps = ('\n    ' + '\n    '.join(new_deps_lines)) if new_deps_lines else ''
        config.set(section, 'deps', new_deps)
        modified = True

    if modified:
        with open(tox_config, 'w') as f:
            config.write(f)
        print('    ✓ Removed inline ops deps from tox.ini')
        patch_tox_testenv_sections(charm_root, ops_wheel, ops_scenario_wheel)

    return updated


def patch_poetry(charm_root: Path, ops_wheel: str, ops_scenario_wheel: str) -> bool:
    """Patch Poetry-based charm dependencies.

    Returns:
        True if patched successfully, False otherwise
    """
    print('✓ Found Poetry-based charm')
    print('  Strategy: Force-reinstall wheels via tox after Poetry install')

    # Poetry doesn't support adding local wheels directly to the lock file.
    # Instead, patch tox config to force-reinstall the wheels after Poetry install.
    if patch_tox_testenv_sections(charm_root, ops_wheel, ops_scenario_wheel):
        print('    ✓ Updated tox config to force-reinstall ops 3.x wheels')
        return True

    return False


def _declared_ops_extras(data: dict) -> set[str]:
    """Collect the extras on every ops requirement that pyproject.toml declares."""
    project = data.get('project', {})
    requirements = list(project.get('dependencies', []))
    for group in project.get('optional-dependencies', {}).values():
        requirements.extend(group)
    for group in data.get('dependency-groups', {}).values():
        requirements.extend(r for r in group if isinstance(r, str))
    extras: set[str] = set()
    for requirement in requirements:
        match = re.match(r'\s*ops\s*\[([^\]]*)\]', requirement)
        if match:
            extras.update(e.strip() for e in match.group(1).split(',') if e.strip())
    return extras


def _override_uv_lock(charm_root: Path, wheels: dict[str, str]) -> bool:
    """Override ops and its companions with the wheels in pyproject.toml, and relock.

    With uv.lock pointing at the wheels, `uv sync` and `uv run` install them too,
    and `uv run` uses the project's own environment rather than tox's, so
    reinstalling the wheels in the tox environment doesn't reach it. An override
    replaces every requirement on the package, including one from another
    dependency, without adding the package where nothing requires it. It also
    replaces the requirement's extras, so the ops override carries the extras
    the charm asks for.

    Args:
        charm_root: Root directory of the charm
        wheels: Path to the wheel for each package name

    Returns:
        True if uv.lock was updated, False otherwise
    """
    pyproject = charm_root / 'pyproject.toml'
    if not pyproject.exists():
        print('  ✗ No pyproject.toml next to uv.lock')
        return False
    data = tomllib.loads(pyproject.read_text())
    extras = _declared_ops_extras(data)
    uv_config = data.setdefault('tool', {}).setdefault('uv', {})
    overrides = [
        override
        for override in uv_config.get('override-dependencies', [])
        if re.split(r'[\s\[<>=~!@;]', override, maxsplit=1)[0] not in wheels
    ]
    for name, wheel in wheels.items():
        name_with_extras = (
            f'{name}[{",".join(sorted(extras))}]' if name == 'ops' and extras else name
        )
        overrides.append(f'{name_with_extras} @ {Path(wheel).resolve().as_uri()}')
    uv_config['override-dependencies'] = overrides
    pyproject.write_text(tomli_w.dumps(data))

    result = subprocess.run(
        ['uv', 'lock', '--python-preference', 'system'],
        cwd=charm_root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f'  ✗ Failed to lock with the ops wheels: {result.stderr.strip()}')
        return False
    print(f'  ✓ Locked {", ".join(wheels)} to the wheels in uv.lock')
    return True


def patch_uv(
    charm_root: Path, ops_wheel: str, ops_scenario_wheel: str, ops_tracing_wheel: str | None
) -> bool:
    """Patch uv-based charm dependencies.

    Returns:
        True if patched successfully, False otherwise
    """
    print('✓ Found uv-based charm')

    wheels = {'ops': ops_wheel, 'ops-scenario': ops_scenario_wheel}
    if ops_tracing_wheel:
        wheels['ops-tracing'] = ops_tracing_wheel
    if not _override_uv_lock(charm_root, wheels):
        return False

    # tox environments that install dependency groups or deps with `uv pip`
    # don't go through the lock, so reinstall the wheels there as well.
    if patch_tox_testenv_sections(charm_root, ops_wheel, ops_scenario_wheel):
        print('    ✓ Updated tox config to force-reinstall ops 3.x wheels')
    return True


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Patch charm dependencies to use newer ops for compatibility testing'
    )
    parser.add_argument('ops_wheel', help='Path to ops wheel file')
    parser.add_argument('ops_scenario_wheel', help='Path to ops-scenario wheel file')
    parser.add_argument(
        'ops_tracing_wheel', nargs='?', help='Path to ops-tracing wheel file (optional)'
    )
    parser.add_argument(
        '--charm-root',
        type=Path,
        default=Path.cwd(),
        help='Root directory of the charm (default: current directory)',
    )

    args = parser.parse_args()

    print('=========================================')
    print('Patching charm dependencies for newer ops compatibility testing')
    print(f'OPS WHEEL: {args.ops_wheel}')
    print(f'OPS-SCENARIO WHEEL: {args.ops_scenario_wheel}')
    if args.ops_tracing_wheel:
        print(f'OPS-TRACING WHEEL: {args.ops_tracing_wheel}')
    print('=========================================')

    # Update Python version requirements.
    update_python_version_requirements(args.charm_root)

    # Detect dependency management system and patch accordingly.
    print('\nDetecting dependency management system...')

    # 1. Handle requirements.txt-based charms.
    if list(args.charm_root.glob('*requirements*.txt')):
        updated = patch_requirements_txt(args.charm_root, args.ops_wheel, args.ops_scenario_wheel)

    # 2. Handle Poetry-based charms.
    elif (args.charm_root / 'poetry.lock').exists():
        updated = patch_poetry(args.charm_root, args.ops_wheel, args.ops_scenario_wheel)

    # 3. Handle uv-based charms.
    elif (args.charm_root / 'uv.lock').exists():
        updated = patch_uv(
            args.charm_root, args.ops_wheel, args.ops_scenario_wheel, args.ops_tracing_wheel
        )

    else:
        updated = False
        print(
            '✗ Error: No recognised dependency files found '
            '(requirements.txt, poetry.lock, or uv.lock)'
        )
        print('  Cannot update ops dependencies without a dependency file.')

    print()

    # Fail if we didn't successfully update any dependencies.
    if not updated:
        print('=========================================')
        print('✗ FAILURE: No dependency files were updated')
        print('=========================================')
        print(
            'ERROR: Unable to patch ops dependencies - '
            'no recognised dependency management system found.'
        )
        print('This charm either:')
        print('  1. Does not use Python dependencies')
        print('  2. Has a non-standard dependency setup')
        print('  3. Is missing dependency files that should be present')
        print()
        print('The test cannot proceed without updating ops.')
        return 1

    print('=========================================')
    print('✓ Dependency patching complete')
    print('=========================================')
    return 0


if __name__ == '__main__':
    sys.exit(main())
