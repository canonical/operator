#!/usr/bin/env python3
"""Patch charm dependencies to use ops 3.x for compatibility testing.

This script handles multiple dependency management systems (pip, Poetry, uv)
and updates them to use the specified version of ops and ops-scenario.

Usage: patch-charm-deps.py <ops-wheel> <ops-scenario-wheel>
"""

import argparse
import re
import sys
from pathlib import Path


def update_python_version_requirements(charm_root: Path, max_version: str | None = None) -> None:
    """Update Python version requirements to >=3.10 (and optionally cap at max_version).
    
    Args:
        charm_root: Root directory of the charm
        max_version: Optional maximum Python version (e.g., "3.12")
    """
    print("\nUpdating Python version requirements...")
    
    # Update tox.ini
    tox_ini = charm_root / "tox.ini"
    if tox_ini.exists():
        content = tox_ini.read_text()
        original = content
        
        # Update basepython to use python3.10 if it's set to 3.8 or 3.9
        content = re.sub(r'^basepython = python3\.[89]$', 'basepython = python3.10', content, flags=re.MULTILINE)
        
        # Update py3X environment factors to py310 minimum
        content = re.sub(r'\{py3[89]\}', '{py310}', content)
        content = re.sub(r'py3[89]', 'py310', content)
        
        if content != original:
            tox_ini.write_text(content)
            print(f"  ✓ Updated {tox_ini.relative_to(charm_root)}")
    
    # Update pyproject.toml requires-python
    pyproject = charm_root / "pyproject.toml"
    if pyproject.exists():
        content = pyproject.read_text()
        original = content
        
        if max_version:
            # Cap at max_version
            version_constraint = f'">=3.10,<{max_version}"'
            content = re.sub(
                r'requires-python = ["\'][^"\']+["\']',
                f'requires-python = {version_constraint}',
                content
            )
        else:
            # Update requires-python to >=3.10 if it's <3.10 (handles >=3.8, >=3.9, >=3.8.6, etc.)
            content = re.sub(
                r'requires-python = ["\']>=3\.[89](\.[0-9]+)?["\']',
                'requires-python = ">=3.10"',
                content
            )
        
        if content != original:
            pyproject.write_text(content)
            print(f"  ✓ Updated {pyproject.relative_to(charm_root)}")
    
    # Update .python-version
    python_version = charm_root / ".python-version"
    if python_version.exists():
        content = python_version.read_text()
        # Replace any 3.8 or 3.9 version with 3.10 (or 3.11 if max_version is 3.12)
        if max_version == "3.12":
            new_version = "3.11\n"
        else:
            new_version = "3.10\n"
        
        if re.match(r'^3\.[89]\.', content):
            python_version.write_text(new_version)
            print(f"  ✓ Updated {python_version.relative_to(charm_root)} to {new_version.strip()}")


def add_tox_pip_commands(tox_ini_path: Path, section: str, ops_wheel: str, ops_scenario_wheel: str, use_uv_pip: bool) -> None:
    """Add pip to allowlist_externals and commands_post to force-reinstall ops wheels.
    
    Args:
        tox_ini_path: Path to tox.ini
        section: Section name (e.g., "testenv:unit" or "testenv")
        ops_wheel: Path to ops wheel file
        ops_scenario_wheel: Path to ops-scenario wheel file
        use_uv_pip: Whether to use 'uv pip install' instead of 'pip install'
    """
    content = tox_ini_path.read_text()
    lines = content.split('\n')
    
    section_pattern = f'[{section}]'
    section_idx = None
    
    # Find the section
    for i, line in enumerate(lines):
        if line.strip() == section_pattern:
            section_idx = i
            break
    
    if section_idx is None:
        print(f"  Section [{section}] not found in tox.ini, skipping")
        return
    
    print(f"  Adding pip to allowlist_externals and commands_post in [{section}]")
    
    # Find the next section or end of file
    next_section_idx = len(lines)
    for i in range(section_idx + 1, len(lines)):
        if lines[i].startswith('[testenv'):
            next_section_idx = i
            break
    
    # Check if allowlist_externals already exists in this section
    allowlist_idx = None
    for i in range(section_idx, next_section_idx):
        if re.match(r'^allowlist_externals\s*=', lines[i]):
            allowlist_idx = i
            break
    
    pip_cmd = "uv pip install" if use_uv_pip else "pip install"
    
    if allowlist_idx is not None:
        print("    Found existing allowlist_externals, appending pip")
        # Insert pip as an indented entry after allowlist_externals
        lines.insert(allowlist_idx + 1, "    pip")
    else:
        print("    Creating new allowlist_externals with pip")
        lines.insert(section_idx + 1, "allowlist_externals = pip")
    
    # Add commands_post
    print(f"    Adding commands_post to force-reinstall ops 3.x (using '{pip_cmd}')")
    lines.insert(section_idx + 1, "commands_post =")
    lines.insert(section_idx + 2, f"    {pip_cmd} --force-reinstall --no-deps {ops_wheel}")
    lines.insert(section_idx + 3, f"    {pip_cmd} --no-deps {ops_scenario_wheel}")
    
    tox_ini_path.write_text('\n'.join(lines))


def patch_tox_testenv_sections(charm_root: Path, ops_wheel: str, ops_scenario_wheel: str) -> bool:
    """Patch all testenv sections in tox.ini.
    
    Returns:
        True if any sections were patched, False otherwise
    """
    tox_ini = charm_root / "tox.ini"
    if not tox_ini.exists():
        return False
    
    content = tox_ini.read_text()
    
    # Detect if tox-uv is being used
    use_uv_pip = (
        re.search(r'^runner\s*=\s*["\']?uv-venv', content, re.MULTILINE) is not None or
        re.search(r'^package\s*=\s*["\']?uv', content, re.MULTILINE) is not None
    )
    
    if use_uv_pip:
        print("  Detected tox-uv, will use 'uv pip install'")
    
    # Find all testenv sections
    sections = set(re.findall(r'^\[(testenv(?::[^\]]+)?)\]', content, re.MULTILINE))
    
    if not sections:
        return False
    
    for section in sorted(sections):
        add_tox_pip_commands(tox_ini, section, ops_wheel, ops_scenario_wheel, use_uv_pip)
    
    return True


def patch_requirements_txt(charm_root: Path, ops_wheel: str, ops_scenario_wheel: str) -> bool:
    """Patch requirements.txt-based charm dependencies.
    
    Returns:
        True if any files were patched, False otherwise
    """
    print("✓ Found requirements.txt-based charm")
    updated = False
    
    for req_file_name in ["test-requirements.txt", "requirements-charmcraft.txt", "requirements.txt"]:
        req_file = charm_root / req_file_name
        if req_file.exists():
            print(f"  Patching {req_file_name}")
            content = req_file.read_text()
            
            # Remove existing ops and ops-scenario entries
            lines = content.split('\n')
            lines = [
                line for line in lines
                if not (
                    re.match(r'^ops[ ><=]', line) or
                    'canonical/operator' in line or
                    '#egg=ops' in line or
                    re.match(r'^ops-scenario[ ><=]', line) or
                    re.match(r'^ops\[testing\][ ><=]', line)
                )
            ]
            
            # Add wheel paths
            lines.append('')
            lines.append(ops_wheel)
            lines.append('')
            lines.append(ops_scenario_wheel)
            
            req_file.write_text('\n'.join(lines))
            print(f"    ✓ Updated {req_file_name} with ops 3.x")
            updated = True
    
    # Also patch inline deps in tox.ini if present
    tox_ini = charm_root / "tox.ini"
    if tox_ini.exists():
        content = tox_ini.read_text()
        if re.search(r'^\s+ops', content, re.MULTILINE):
            print("  Found inline ops deps in tox.ini, patching...")
            # Remove ops and ops-scenario deps from tox.ini deps sections
            content = re.sub(r'^\s+(ops\[testing\]|ops)[>=<].*\n', '', content, flags=re.MULTILINE)
            content = re.sub(r'^\s+ops-scenario[>=<].*\n', '', content, flags=re.MULTILINE)
            tox_ini.write_text(content)
            print("    ✓ Removed inline ops deps from tox.ini")
            patch_tox_testenv_sections(charm_root, ops_wheel, ops_scenario_wheel)
    
    return updated


def patch_poetry(charm_root: Path, ops_wheel: str, ops_scenario_wheel: str) -> bool:
    """Patch Poetry-based charm dependencies.
    
    Returns:
        True if patched successfully, False otherwise
    """
    print("✓ Found Poetry-based charm")
    print("  Strategy: Force-reinstall wheels via tox after Poetry install")
    
    # Poetry doesn't support adding local wheels directly to the lock file
    # Instead, patch tox.ini to force-reinstall the wheels after Poetry installs its dependencies
    if patch_tox_testenv_sections(charm_root, ops_wheel, ops_scenario_wheel):
        print("    ✓ Updated tox.ini to force-reinstall ops 3.x wheels")
        return True
    
    return False


def patch_uv(charm_root: Path, ops_wheel: str, ops_scenario_wheel: str) -> bool:
    """Patch uv-based charm dependencies.
    
    Returns:
        True if patched successfully, False otherwise
    """
    print("✓ Found uv-based charm")
    print("  Strategy: Force-reinstall wheels via tox after uv install")
    
    # uv doesn't support adding local wheels to the lock file
    # Instead, patch tox.ini to force-reinstall the wheels after uv installs its dependencies
    if patch_tox_testenv_sections(charm_root, ops_wheel, ops_scenario_wheel):
        print("    ✓ Updated tox.ini to force-reinstall ops 3.x wheels")
        return True
    else:
        print("    ✗ Error: uv-based charm has no tox.ini to patch")
        return False


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Patch charm dependencies to use ops 3.x for compatibility testing"
    )
    parser.add_argument("ops_wheel", help="Path to ops wheel file")
    parser.add_argument("ops_scenario_wheel", help="Path to ops-scenario wheel file")
    parser.add_argument(
        "--max-python-version",
        help="Maximum Python version to support (e.g., '3.12'). If specified, requires-python will be capped.",
    )
    parser.add_argument(
        "--charm-root",
        type=Path,
        default=Path.cwd(),
        help="Root directory of the charm (default: current directory)",
    )
    
    args = parser.parse_args()
    
    print("=========================================")
    print("Patching charm dependencies for ops 3.x compatibility testing")
    print(f"OPS WHEEL: {args.ops_wheel}")
    print(f"OPS-SCENARIO WHEEL: {args.ops_scenario_wheel}")
    if args.max_python_version:
        print(f"MAX PYTHON VERSION: {args.max_python_version}")
    print("=========================================")
    
    # Update Python version requirements
    update_python_version_requirements(args.charm_root, args.max_python_version)
    
    # Track whether we successfully updated any dependencies
    updated = False
    
    # Detect dependency management system and patch accordingly
    print("\nDetecting dependency management system...")
    
    # 1. Handle requirements.txt-based charms
    if any((args.charm_root / f).exists() for f in ["test-requirements.txt", "requirements-charmcraft.txt", "requirements.txt"]):
        updated = patch_requirements_txt(args.charm_root, args.ops_wheel, args.ops_scenario_wheel)
    
    # 2. Handle Poetry-based charms
    elif (args.charm_root / "poetry.lock").exists():
        updated = patch_poetry(args.charm_root, args.ops_wheel, args.ops_scenario_wheel)
    
    # 3. Handle uv-based charms
    elif (args.charm_root / "uv.lock").exists():
        updated = patch_uv(args.charm_root, args.ops_wheel, args.ops_scenario_wheel)
    
    else:
        print("✗ Error: No recognised dependency files found (requirements.txt, poetry.lock, or uv.lock)")
        print("  Cannot update ops dependencies without a dependency file.")
    
    print()
    
    # Fail if we didn't successfully update any dependencies
    if not updated:
        print("=========================================")
        print("✗ FAILURE: No dependency files were updated")
        print("=========================================")
        print("ERROR: Unable to patch ops dependencies - no recognised dependency management system found.")
        print("This charm either:")
        print("  1. Does not use Python dependencies")
        print("  2. Has a non-standard dependency setup")
        print("  3. Is missing dependency files that should be present")
        print()
        print("The test cannot proceed without updating ops to 3.x.")
        return 1
    
    print("=========================================")
    print("✓ Dependency patching complete")
    print("=========================================")
    return 0


if __name__ == "__main__":
    sys.exit(main())
