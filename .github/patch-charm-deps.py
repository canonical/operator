#!/usr/bin/env python3
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
import re
import sys
from pathlib import Path

import tomllib


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


def update_tox_python_version(tox_config: Path, charm_root: Path) -> None:
    """Update Python version in tox configuration (tox.ini or tox.toml).

    Args:
        tox_config: Path to tox configuration file
        charm_root: Root directory of charm (for relative path display)
    """
    if tox_config.suffix == '.ini':
        config = configparser.ConfigParser()
        config.read(tox_config)
        modified = False

        for section in config.sections():
            # Update basepython to use python3.10 if it's set to 3.8 or 3.9
            if config.has_option(section, 'basepython'):
                basepython = config.get(section, 'basepython')
                if basepython in ('python3.8', 'python3.9'):
                    config.set(section, 'basepython', 'python3.10')
                    modified = True

            # Update envlist to replace py38/py39 with py310
            # Only replace if py310 doesn't already exist to avoid duplicates
            if config.has_option(section, 'envlist'):
                envlist = config.get(section, 'envlist')
                new_envlist = envlist
                if 'py310' not in envlist:
                    new_envlist = new_envlist.replace('py38', 'py310').replace('py39', 'py310')
                    new_envlist = new_envlist.replace('{py38}', '{py310}')
                    new_envlist = new_envlist.replace('{py39}', '{py310}')
                else:
                    # py310 already exists, just remove py38/py39 references
                    new_envlist = re.sub(r'\bpy38\b,?\s*', '', new_envlist)
                    new_envlist = re.sub(r'\bpy39\b,?\s*', '', new_envlist)
                    new_envlist = re.sub(r'\{py38\},?\s*', '', new_envlist)
                    new_envlist = re.sub(r'\{py39\},?\s*', '', new_envlist)
                    # Clean up any trailing commas or whitespace
                    new_envlist = re.sub(r',\s*$', '', new_envlist)
                    new_envlist = re.sub(r',\s*\n', '\n', new_envlist)
                if new_envlist != envlist:
                    config.set(section, 'envlist', new_envlist)
                    modified = True

        if modified:
            with open(tox_config, 'w') as f:
                config.write(f)
            print(f'  ✓ Updated {tox_config.relative_to(charm_root)}')

    elif tox_config.suffix == '.toml':
        # Handle tox.toml using regex (no standard library for writing TOML)
        content = tox_config.read_text()
        original = content

        # Update basepython
        content = re.sub(
            r'(basepython\s*=\s*["\'])python3\.[89](["\'])', r'\1python3.10\2', content
        )

        # Update envlist - only replace if py310 doesn't already exist to avoid duplicates
        if 'py310' not in content:
            content = content.replace('py38', 'py310').replace('py39', 'py310')
            content = content.replace('{py38}', '{py310}').replace('{py39}', '{py310}')
        else:
            # py310 already exists, just remove py38/py39 references
            content = re.sub(r'\bpy38\b,?\s*', '', content)
            content = re.sub(r'\bpy39\b,?\s*', '', content)
            content = re.sub(r'\{py38\},?\s*', '', content)
            content = re.sub(r'\{py39\},?\s*', '', content)

        if content != original:
            tox_config.write_text(content)
            print(f'  ✓ Updated {tox_config.relative_to(charm_root)}')


def update_pyproject_python_version(
    pyproject: Path, charm_root: Path, max_version: str | None = None
) -> None:
    """Update requires-python in pyproject.toml.

    Args:
        pyproject: Path to pyproject.toml
        charm_root: Root directory of charm (for relative path display)
        max_version: Optional maximum Python version (e.g., "3.12")
    """
    content = pyproject.read_text()

    # Parse TOML
    try:
        data = tomllib.loads(content)
    except tomllib.TOMLDecodeError:
        # Fall back to regex if TOML parsing fails
        print(f'  ⚠ Warning: Could not parse {pyproject.name} as TOML, using regex fallback')
        original = content
        if max_version:
            version_constraint = f'">=3.10,<{max_version}"'
            content = re.sub(
                r'requires-python = ["\'][^"\']+["\']',
                f'requires-python = {version_constraint}',
                content,
            )
        else:
            content = re.sub(
                r'requires-python = ["\']>=3\.[89](\.[0-9]+)?["\']',
                'requires-python = ">=3.10"',
                content,
            )
        if content != original:
            pyproject.write_text(content)
            print(f'  ✓ Updated {pyproject.relative_to(charm_root)}')
        return

    # Update requires-python if it exists
    modified = False
    if 'project' in data and 'requires-python' in data['project']:
        requires_python = data['project']['requires-python']

        if max_version:
            # Cap at max_version
            new_requires = f'>=3.10,<{max_version}'
        elif re.match(r'>=3\.[89]', requires_python):
            # Update to >=3.10 if currently <3.10
            new_requires = '>=3.10'
        else:
            new_requires = None

        if new_requires:
            # Use regex to preserve the exact format (quotes, whitespace)
            content = re.sub(
                r'(requires-python\s*=\s*)["\'][^"\']+["\']', f'\\1"{new_requires}"', content
            )
            modified = True

    if modified:
        pyproject.write_text(content)
        print(f'  ✓ Updated {pyproject.relative_to(charm_root)}')


def update_python_version_file(
    python_version_file: Path, charm_root: Path, max_version: str | None = None
) -> None:
    """Update .python-version file.

    Args:
        python_version_file: Path to .python-version
        charm_root: Root directory of charm (for relative path display)
        max_version: Optional maximum Python version (e.g., "3.12")
    """
    content = python_version_file.read_text().strip()
    # Replace any 3.8 or 3.9 version with 3.10 (or 3.11 if max_version is 3.12)
    # Use fullmatch with explicit minor versions to avoid matching 3.80, 3.81, etc.
    if re.fullmatch(r'3\.(8|9)(\.\d+)?', content):
        new_version = '3.11' if max_version == '3.12' else '3.10'
        python_version_file.write_text(new_version + '\n')
        print(f'  ✓ Updated {python_version_file.relative_to(charm_root)} to {new_version}')


def update_python_version_requirements(charm_root: Path, max_version: str | None = None) -> None:
    """Update Python version requirements to >=3.10 (and optionally cap at max_version).

    Args:
        charm_root: Root directory of the charm
        max_version: Optional maximum Python version (e.g., "3.12")
    """
    print('\nUpdating Python version requirements...')

    # Update tox.ini or tox.toml
    tox_config = get_tox_config_path(charm_root)
    if tox_config:
        update_tox_python_version(tox_config, charm_root)

    # Update pyproject.toml requires-python
    pyproject = charm_root / 'pyproject.toml'
    if pyproject.exists():
        update_pyproject_python_version(pyproject, charm_root, max_version)

    # Update .python-version
    python_version_file = charm_root / '.python-version'
    if python_version_file.exists():
        update_python_version_file(python_version_file, charm_root, max_version)


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


def add_tox_pip_commands_ini(
    tox_ini_path: Path, section: str, ops_wheel: str, ops_scenario_wheel: str, use_uv_pip: bool
) -> None:
    """Add pip to allowlist_externals and commands_post to force-reinstall ops wheels (INI format).

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

    print(f'  Adding pip to allowlist_externals and commands_post in [{section}]')

    pip_cmd = 'uv pip install' if use_uv_pip else 'pip install'

    # Add pip to allowlist_externals
    if config.has_option(section, 'allowlist_externals'):
        allowlist = config.get(section, 'allowlist_externals')
        if 'pip' not in allowlist.split():
            print('    Found existing allowlist_externals, appending pip')
            # Preserve multi-line format if it exists
            if '\n' in allowlist:
                config.set(section, 'allowlist_externals', allowlist + '\n    pip')
            else:
                config.set(section, 'allowlist_externals', allowlist + '\n    pip')
    else:
        print('    Creating new allowlist_externals with pip')
        config.set(section, 'allowlist_externals', 'pip')

    # Add commands_post
    print(f"    Adding commands_post to force-reinstall ops 3.x (using '{pip_cmd}')")
    commands_post = (
        f'\n    {pip_cmd} --force-reinstall --no-deps {ops_wheel}'
        f'\n    {pip_cmd} --no-deps {ops_scenario_wheel}'
    )
    config.set(section, 'commands_post', commands_post)

    with open(tox_ini_path, 'w') as f:
        config.write(f)


def add_tox_pip_commands_toml(
    tox_toml_path: Path, section: str, ops_wheel: str, ops_scenario_wheel: str, use_uv_pip: bool
) -> None:
    """Add pip to allowlist_externals and commands_post to force-reinstall ops wheels.

    This function handles TOML format tox configuration files.

    Args:
        tox_toml_path: Path to tox.toml
        section: Section name (e.g., "testenv:unit" or "testenv")
        ops_wheel: Path to ops wheel file
        ops_scenario_wheel: Path to ops-scenario wheel file
        use_uv_pip: Whether to use 'uv pip install' instead of 'pip install'
    """
    content = tox_toml_path.read_text()

    # Parse to check if section exists and what keys are already present
    try:
        data = tomllib.loads(content)
    except tomllib.TOMLDecodeError as e:
        print(f'  ⚠ Warning: Could not parse tox.toml: {e}')
        return

    # Convert section name format: testenv:unit -> env.unit, testenv -> env_run_base
    if section == 'testenv':
        toml_section = 'env_run_base'
    elif section.startswith('testenv:'):
        env_name = section.split(':', 1)[1]
        toml_section = f'env.{env_name}'
    else:
        print(f'  Unknown section format: {section}, skipping')
        return

    # Check if section exists in TOML
    section_parts = toml_section.split('.')
    current = data
    for part in section_parts:
        if part not in current:
            print(f'  Section {toml_section} not found in tox.toml, skipping')
            return
        current = current[part]

    # Check what already exists in this section
    has_allowlist = 'allowlist_externals' in current
    has_commands_post = 'commands_post' in current

    print(f'  Adding pip to allowlist_externals and commands_post in [{toml_section}]')

    pip_cmd = 'uv pip install' if use_uv_pip else 'pip install'

    if not has_allowlist:
        print('    Creating new allowlist_externals with pip')
        # Add after section header - find the line after the section header
        content = re.sub(
            rf'(\[{re.escape(toml_section)}\]\s*\n)',
            r'\1allowlist_externals = ["pip"]\n',
            content,
        )
    else:
        print('    Found existing allowlist_externals, appending pip')
        # Check if "pip" is already in the array
        if (
            isinstance(current['allowlist_externals'], list)
            and 'pip' not in current['allowlist_externals']
        ):
            # Add pip to the existing array
            content = re.sub(
                r'(allowlist_externals\s*=\s*\[)([^\]]*?)(\])',
                lambda m: (
                    f'{m.group(1)}{m.group(2)}, "pip"{m.group(3)}'
                    if m.group(2).strip()
                    else f'{m.group(1)}"pip"{m.group(3)}'
                ),
                content,
                count=1,
            )
        else:
            print('      pip already in allowlist_externals, skipping')

    if not has_commands_post:
        print(f"    Adding commands_post to force-reinstall ops 3.x (using '{pip_cmd}')")
        commands_post_str = (
            f'commands_post = [\n'
            f'    "{pip_cmd} --force-reinstall --no-deps {ops_wheel}",\n'
            f'    "{pip_cmd} --no-deps {ops_scenario_wheel}",\n'
            f']'
        )

        # Add after allowlist_externals if it exists, otherwise after section header
        if 'allowlist_externals' in content:
            # Add after the allowlist_externals line(s)
            content = re.sub(
                r'(allowlist_externals\s*=\s*\[[^\]]*\]\s*\n)',
                rf'\1{commands_post_str}\n',
                content,
                count=1,
            )
        else:
            # Add after section header
            content = re.sub(
                rf'(\[{re.escape(toml_section)}\]\s*\n)', rf'\1{commands_post_str}\n', content
            )
    else:
        print('    commands_post already exists, skipping')

    tox_toml_path.write_text(content)


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
    try:
        with open(tox_config, 'rb') as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError:
        print(f'  ⚠ Warning: Could not parse {tox_config.name}')
        return False

    use_uv_pip = _detect_tox_uv_toml(data)
    if use_uv_pip:
        print("  Detected tox-uv, will use 'uv pip install'")

    # Patch env_run_base (equivalent to [testenv])
    if 'env_run_base' in data:
        add_tox_pip_commands_toml(
            tox_config, 'testenv', ops_wheel, ops_scenario_wheel, use_uv_pip
        )

    # Patch specific envs
    if 'env' in data:
        for env_name in sorted(data['env'].keys()):
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

    # Find all testenv sections
    testenv_sections = [s for s in config.sections() if s.startswith('testenv')]
    if not testenv_sections:
        return False

    for section in sorted(testenv_sections):
        add_tox_pip_commands_ini(
            tox_config, section, ops_wheel, ops_scenario_wheel, use_uv_pip
        )

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

    # Find all requirements files using glob
    req_files = list(charm_root.glob('*requirements*.txt'))
    for req_file in req_files:
        print(f'  Patching {req_file.name}')
        content = req_file.read_text()

        # Remove existing ops and ops-scenario entries
        lines = [line for line in content.split('\n') if not _is_ops_dependency_line(line)]

        # Add wheel paths
        lines.extend(['', ops_wheel, '', ops_scenario_wheel])

        req_file.write_text('\n'.join(lines))
        print(f'    ✓ Updated {req_file.name} with ops 3.x')
        updated = True

    # Also patch inline deps in tox config if present
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
        # Remove ops and ops-scenario deps using the helper function
        new_deps_lines = [
            line.strip()
            for line in deps.split('\n')
            if line.strip() and not _is_ops_dependency_line(line.strip())
        ]

        original_count = len([ln for ln in deps.split('\n') if ln.strip()])
        if len(new_deps_lines) == original_count:
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


def patch_uv(charm_root: Path, ops_wheel: str, ops_scenario_wheel: str) -> bool:
    """Patch uv-based charm dependencies.

    Returns:
        True if patched successfully, False otherwise
    """
    print('✓ Found uv-based charm')
    print('  Strategy: Force-reinstall wheels via tox after uv install')

    # uv doesn't support adding local wheels to the lock file
    # Instead, patch tox config to force-reinstall the wheels after uv installs its dependencies
    if patch_tox_testenv_sections(charm_root, ops_wheel, ops_scenario_wheel):
        print('    ✓ Updated tox config to force-reinstall ops 3.x wheels')
        return True
    else:
        print('    ✗ Error: uv-based charm has no tox config to patch')
        return False


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Patch charm dependencies to use ops 3.x for compatibility testing'
    )
    parser.add_argument('ops_wheel', help='Path to ops wheel file')
    parser.add_argument('ops_scenario_wheel', help='Path to ops-scenario wheel file')
    parser.add_argument(
        '--max-python-version',
        help="Maximum Python version to support (e.g., '3.12'). "
        'If specified, requires-python will be capped.',
    )
    parser.add_argument(
        '--charm-root',
        type=Path,
        default=Path.cwd(),
        help='Root directory of the charm (default: current directory)',
    )

    args = parser.parse_args()

    print('=========================================')
    print('Patching charm dependencies for ops 3.x compatibility testing')
    print(f'OPS WHEEL: {args.ops_wheel}')
    print(f'OPS-SCENARIO WHEEL: {args.ops_scenario_wheel}')
    if args.max_python_version:
        print(f'MAX PYTHON VERSION: {args.max_python_version}')
    print('=========================================')

    # Update Python version requirements
    update_python_version_requirements(args.charm_root, args.max_python_version)

    # Track whether we successfully updated any dependencies
    updated = False

    # Detect dependency management system and patch accordingly
    print('\nDetecting dependency management system...')

    # 1. Handle requirements.txt-based charms
    req_files = list(args.charm_root.glob('*requirements*.txt'))
    if req_files:
        updated = patch_requirements_txt(args.charm_root, args.ops_wheel, args.ops_scenario_wheel)

    # 2. Handle Poetry-based charms
    elif (args.charm_root / 'poetry.lock').exists():
        updated = patch_poetry(args.charm_root, args.ops_wheel, args.ops_scenario_wheel)

    # 3. Handle uv-based charms
    elif (args.charm_root / 'uv.lock').exists():
        updated = patch_uv(args.charm_root, args.ops_wheel, args.ops_scenario_wheel)

    else:
        print(
            '✗ Error: No recognised dependency files found '
            '(requirements.txt, poetry.lock, or uv.lock)'
        )
        print('  Cannot update ops dependencies without a dependency file.')

    print()

    # Fail if we didn't successfully update any dependencies
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
        print('The test cannot proceed without updating ops to 3.x.')
        return 1

    print('=========================================')
    print('✓ Dependency patching complete')
    print('=========================================')
    return 0


if __name__ == '__main__':
    sys.exit(main())
