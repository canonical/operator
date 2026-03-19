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

Usage: patch-charm-deps.py <ops-wheel> <ops-scenario-wheel>
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


# Handle tox-uv


def _detect_tox_uv_ini(config: configparser.ConfigParser) -> bool:
    """Detect if tox-uv is being used in a tox.ini config.

    Args:
        config: Parsed configparser object

    Returns:
        True if tox-uv is detected, False otherwise
    """
    for section in config.sections():
        if config.has_option(section, 'runner') and 'uv-venv' in config.get(section, 'runner'):
            return True
        if config.has_option(section, 'package') and 'uv' in config.get(section, 'package'):
            return True
    return False


def _detect_tox_uv_toml(data: dict) -> bool:
    """Detect if tox-uv is being used in a tox.toml config.

    Args:
        data: Parsed TOML data

    Returns:
        True if tox-uv is detected, False otherwise
    """
    if 'env_run_base' in data:
        env_base = data['env_run_base']
        if 'runner' in env_base and 'uv-venv' in str(env_base['runner']):
            return True
        if 'package' in env_base and 'uv' in str(env_base['package']):
            return True

    if 'env' not in data:
        return False

    for env_data in data['env'].values():
        if 'runner' in env_data and 'uv-venv' in str(env_data['runner']):
            return True
        if 'package' in env_data and 'uv' in str(env_data['package']):
            return True

    return False


# Adjust tox to install the version of ops[...] that we want.


def add_tox_pip_commands_ini(
    tox_ini_path: Path, section: str, ops_wheel: str, ops_scenario_wheel: str, use_uv_pip: bool
) -> None:
    """Add pip to allowlist_externals and commands_pre to force-reinstall ops wheels (INI format).

    Args:
        tox_ini_path: Path to tox.ini
        section: Section name (e.g., "testenv:unit" or "testenv")
        ops_wheel: Path to ops wheel file
        ops_scenario_wheel: Path to ops-scenario wheel file
        use_uv_pip: Whether to use 'uv pip install' instead of 'pip install'
    """
    config = configparser.ConfigParser()
    config.read(tox_ini_path)

    if not config.has_section(section):
        print(f'  Section [{section}] not found in tox.ini, skipping')
        return

    print(f'  Adding pip to allowlist_externals and commands_pre in [{section}]')

    pip_cmd = 'uv pip install' if use_uv_pip else 'pip install'

    # Add pip to allowlist_externals.
    if config.has_option(section, 'allowlist_externals'):
        allowlist = config.get(section, 'allowlist_externals')
        if 'pip' not in allowlist.split():
            print('    Found existing allowlist_externals, appending pip')
            config.set(section, 'allowlist_externals', allowlist + '\n    pip')
    else:
        print('    Creating new allowlist_externals with pip')
        config.set(section, 'allowlist_externals', 'pip')

    # Append to commands_pre (preserve existing commands like 'poetry install').
    print(f"    Adding commands_pre to force-reinstall ops 3.x (using '{pip_cmd}')")
    new_commands = (
        f'\n    {pip_cmd} --force-reinstall --no-deps {ops_wheel}'
        f'\n    {pip_cmd} --no-deps {ops_scenario_wheel}'
    )
    existing = config.get(section, 'commands_pre', fallback='')
    config.set(section, 'commands_pre', existing + new_commands)

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

    use_uv_pip = _detect_tox_uv_toml(data)
    if use_uv_pip:
        print("  Detected tox-uv, will use 'uv pip install'")

    # Patch env_run_base (equivalent to [testenv]).
    if 'env_run_base' in data:
        add_tox_pip_commands_toml(tox_config, 'testenv', ops_wheel, ops_scenario_wheel, use_uv_pip)

    # Patch specific envs.
    if 'env' in data:
        for env_name in data['env']:
            add_tox_pip_commands_toml(
                tox_config, f'testenv:{env_name}', ops_wheel, ops_scenario_wheel, use_uv_pip
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

    use_uv_pip = _detect_tox_uv_ini(config)
    if use_uv_pip:
        print("  Detected tox-uv, will use 'uv pip install'")

    # Find all testenv sections.
    testenv_sections = [s for s in config.sections() if s.startswith('testenv')]
    if not testenv_sections:
        return False

    for section in testenv_sections:
        add_tox_pip_commands_ini(tox_config, section, ops_wheel, ops_scenario_wheel, use_uv_pip)

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
    tox_toml_path: Path, section: str, ops_wheel: str, ops_scenario_wheel: str, use_uv_pip: bool
) -> None:
    """Add pip to allowlist_externals and commands_pre to force-reinstall ops wheels.

    This function handles TOML format tox configuration files.

    Args:
        tox_toml_path: Path to tox.toml
        section: Section name (e.g., "testenv:unit" or "testenv")
        ops_wheel: Path to ops wheel file
        ops_scenario_wheel: Path to ops-scenario wheel file
        use_uv_pip: Whether to use 'uv pip install' instead of 'pip install'
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
    print(f'  Adding pip to allowlist_externals and commands_pre in [{toml_section}]')

    pip_cmd = 'uv pip install' if use_uv_pip else 'pip install'
    modified = False

    # Update allowlist_externals.
    if 'allowlist_externals' not in current:
        print('    Creating new allowlist_externals with pip')
        current['allowlist_externals'] = ['pip']
        modified = True
    elif 'pip' not in current['allowlist_externals']:
        print('    Found existing allowlist_externals, appending pip')
        current['allowlist_externals'].append('pip')
        modified = True
    else:
        print('      pip already in allowlist_externals, skipping')

    # Update commands_pre (tox 4 TOML format requires list-of-lists).
    pip_args = ['uv', 'pip', 'install'] if use_uv_pip else ['pip', 'install']
    new_commands = [
        [*pip_args, '--force-reinstall', '--no-deps', ops_wheel],
        [*pip_args, '--no-deps', ops_scenario_wheel],
    ]
    if 'commands_pre' not in current:
        print(f"    Adding commands_pre to force-reinstall ops 3.x (using '{pip_cmd}')")
        current['commands_pre'] = new_commands
        modified = True
    else:
        print(f"    Appending to existing commands_pre (using '{pip_cmd}')")
        existing = current['commands_pre']
        if isinstance(existing, list):
            current['commands_pre'] = existing + new_commands
        else:
            current['commands_pre'] = new_commands
        modified = True

    if modified:
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


def _patch_uv_deps_directly(charm_root: Path, ops_wheel: str, ops_scenario_wheel: str) -> bool:
    """Patch uv dependencies directly via uv CLI when no tox config exists.

    Args:
        charm_root: Root directory of the charm
        ops_wheel: Path to ops wheel file
        ops_scenario_wheel: Path to ops-scenario wheel file

    Returns:
        True if patched successfully, False otherwise
    """
    print('  No tox config found, patching dependencies directly via uv CLI')

    # Read pyproject.toml to find which groups contain ops-scenario.
    pyproject = charm_root / 'pyproject.toml'
    scenario_groups: list[str] = []
    if pyproject.exists():
        data = tomllib.loads(pyproject.read_text())
        # Check dependency-groups for ops-scenario.
        scenario_groups = [
            group_name
            for group_name, group_deps in data.get('dependency-groups', {}).items()
            for dep in group_deps
            if isinstance(dep, str) and re.match(r'^ops-scenario\b', dep)
        ]

    # Remove existing ops deps (ignore errors - they may not exist).
    for dep_name in ('ops[testing]', 'ops'):
        subprocess.run(
            ['uv', 'remove', dep_name, '--frozen'],
            cwd=charm_root,
            capture_output=True,
            text=True,
        )

    # Remove ops-scenario from all groups where it was found.
    for group in scenario_groups:
        subprocess.run(
            ['uv', 'remove', 'ops-scenario', '--group', group, '--frozen'],
            cwd=charm_root,
            capture_output=True,
            text=True,
        )

    # Add the ops wheel.
    result = subprocess.run(
        ['uv', 'add', ops_wheel, '--raw-sources', '--prerelease=if-necessary-or-explicit'],
        cwd=charm_root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f'    ✗ Failed to add ops wheel: {result.stderr.strip()}')
        return False
    print('    ✓ Added ops wheel')

    # Add the ops-scenario wheel to each group it was originally in.
    scenario_add_targets = scenario_groups or [None]
    for group in scenario_add_targets:
        scenario_cmd = [
            'uv',
            'add',
            ops_scenario_wheel,
            '--raw-sources',
            '--prerelease=if-necessary-or-explicit',
        ]
        if group:
            scenario_cmd.extend(['--group', group])
        result = subprocess.run(scenario_cmd, cwd=charm_root, capture_output=True, text=True)
        if result.returncode != 0:
            print(f'    ✗ Failed to add ops-scenario wheel: {result.stderr.strip()}')
            # Still return True since ops was updated successfully.
        else:
            group_label = f' (group: {group})' if group else ''
            print(f'    ✓ Added ops-scenario wheel{group_label}')

    return True


def patch_uv(charm_root: Path, ops_wheel: str, ops_scenario_wheel: str) -> bool:
    """Patch uv-based charm dependencies.

    Returns:
        True if patched successfully, False otherwise
    """
    print('✓ Found uv-based charm')

    # Try tox config first.
    if patch_tox_testenv_sections(charm_root, ops_wheel, ops_scenario_wheel):
        print('  Strategy: Force-reinstall wheels via tox after uv install')
        print('    ✓ Updated tox config to force-reinstall ops 3.x wheels')
        return True

    # No tox config - patch deps directly via uv CLI.
    return _patch_uv_deps_directly(charm_root, ops_wheel, ops_scenario_wheel)


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Patch charm dependencies to use newer ops for compatibility testing'
    )
    parser.add_argument('ops_wheel', help='Path to ops wheel file')
    parser.add_argument('ops_scenario_wheel', help='Path to ops-scenario wheel file')
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
        updated = patch_uv(args.charm_root, args.ops_wheel, args.ops_scenario_wheel)

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
