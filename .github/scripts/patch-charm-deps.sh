#!/bin/bash
# Patch charm dependencies to use ops 3.x for compatibility testing
#
# This script handles multiple dependency management systems (pip, Poetry, uv)
# and updates them to use the specified version of ops and ops-scenario.
#
# Usage: patch-charm-deps.sh <ops-wheel> <ops-scenario-wheel>
#   ops-wheel: Path to ops wheel file (e.g., /path/to/ops-3.6.0-py3-none-any.whl)
#   ops-scenario-wheel: Path to ops-scenario wheel file (e.g., /path/to/ops_scenario-8.6.0-py3-none-any.whl)

set -euo pipefail

OPS_WHEEL="${1:-}"
OPS_SCENARIO_WHEEL="${2:-}"

if [ -z "$OPS_WHEEL" ] || [ -z "$OPS_SCENARIO_WHEEL" ]; then
  echo "Error: Missing required arguments"
  echo "Usage: $0 <ops-wheel> <ops-scenario-wheel>"
  exit 1
fi

echo "========================================="
echo "Patching charm dependencies for ops 3.x compatibility testing"
echo "OPS WHEEL: $OPS_WHEEL"
echo "OPS-SCENARIO WHEEL: $OPS_SCENARIO_WHEEL"
echo "========================================="

# Function to add pip to allowlist_externals and commands_post to a tox.ini section
# Args: $1 = section name (e.g., "testenv:unit" or "testenv")
add_tox_pip_commands() {
  local section="$1"
  local section_pattern="^\[${section}\]"
  
  if ! grep -q "$section_pattern" tox.ini; then
    echo "  Section [$section] not found in tox.ini, skipping"
    return
  fi
  
  echo "  Adding pip to allowlist_externals and commands_post in [$section]"
  
  # Check if allowlist_externals already exists
  if grep -A5 "$section_pattern" tox.ini | grep -q "^allowlist_externals"; then
    echo "    Found existing allowlist_externals, appending pip"
    # Append pip to existing allowlist_externals multi-line list
    sed -i "/$section_pattern/,/^\[testenv:/ { /^allowlist_externals[[:space:]]*=/a\    pip\n}" tox.ini
  else
    echo "    Creating new allowlist_externals with pip"
    sed -i "/$section_pattern/a allowlist_externals = pip" tox.ini
  fi
  
  # Add commands_post to force-reinstall ops after regular install
  echo "    Adding commands_post to force-reinstall ops 3.x"
  sed -i "/$section_pattern/a commands_post =\n    pip install --force-reinstall --no-deps $OPS_WHEEL\n    pip install --no-deps $OPS_SCENARIO_WHEEL" tox.ini
}

# Detect dependency management system and patch accordingly
echo ""
echo "Detecting dependency management system..."

# 1. Handle requirements.txt-based charms
if [ -e "test-requirements.txt" ] || [ -e "requirements-charmcraft.txt" ] || [ -e "requirements.txt" ]; then
  echo "✓ Found requirements.txt-based charm"
  
  for req_file in test-requirements.txt requirements-charmcraft.txt requirements.txt; do
    if [ -e "$req_file" ]; then
      echo "  Patching $req_file"
      # Remove existing ops and ops-scenario entries
      sed -i -e "/^ops[ ><=]/d" -e "/canonical\/operator/d" -e "/#egg=ops/d" "$req_file"
      echo -e "\n$OPS_WHEEL" >> "$req_file"
      sed -i -e "/^ops-scenario[ ><=]/d" -e "/^ops\[testing\][ ><=]/d" "$req_file"
      echo -e "\n$OPS_SCENARIO_WHEEL" >> "$req_file"
      echo "    ✓ Updated $req_file with ops 3.x"
    fi
  done
  
  # Also patch inline deps in tox.ini if present
  if [ -e "tox.ini" ] && grep -q "^[[:space:]]*ops" tox.ini; then
    echo "  Found inline ops deps in tox.ini, patching..."
    # Remove ops and ops-scenario deps from tox.ini deps sections
    sed -i -E "/^[[:space:]]*(ops\[testing\]|ops)[>=<]/d" tox.ini
    sed -i -E "/^[[:space:]]*ops-scenario[>=<]/d" tox.ini
    echo "    ✓ Removed inline ops deps from tox.ini"
    
    # Add commands_post to force-reinstall
    if grep -q "^\[testenv:unit\]" tox.ini; then
      add_tox_pip_commands "testenv:unit"
    fi
  fi
  
# 2. Handle Poetry-based charms
elif [ -e "poetry.lock" ]; then
  echo "✓ Found Poetry-based charm"
  echo "  Strategy: Update poetry.lock with wheel files"
  
  poetry add "$OPS_WHEEL" --lock
  poetry add "$OPS_SCENARIO_WHEEL" --lock
  echo "    ✓ Updated poetry.lock with ops 3.x wheels"

# 3. Handle uv-based charms
elif [ -e "uv.lock" ]; then
  echo "✓ Found uv-based charm"
  echo "  Strategy: Update uv.lock with wheel files"
  
  uv add --frozen --raw-sources "$OPS_WHEEL"
  uv add --frozen --raw-sources "$OPS_SCENARIO_WHEEL"
  uv lock
  echo "    ✓ Updated uv.lock with ops 3.x wheels"

else
  echo "⚠ Warning: No recognised dependency files found (requirements.txt, poetry.lock, or uv.lock)"
  echo "  The charm may not use Python dependencies or may have a non-standard setup."
  echo "  Skipping ops version update."
fi

echo ""
echo "========================================="
echo "✓ Dependency patching complete"
echo "========================================="
