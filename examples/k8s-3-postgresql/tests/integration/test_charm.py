# Copyright 2026 Canonical Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# The integration tests use the Jubilant library and the pytest-jubilant plugin.
# See https://canonical.com/juju/docs/ops/latest/howto/write-integration-tests-for-a-charm/
#
# pytest-jubilant provides a module-scoped `juju` fixture that creates a temporary Juju model.
# The `charm` fixture is defined in conftest.py.

import logging
import pathlib
import subprocess
import time

import jubilant
import pytest
import yaml

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(pathlib.Path("charmcraft.yaml").read_text())
APP_NAME = METADATA["name"]


@pytest.mark.juju_setup
def test_deploy(charm: pathlib.Path, juju: jubilant.Juju):
    """Deploy the charm under test.

    Assert on the unit status before any relations/configurations take place.
    """
    resources = {
        "demo-server-image": METADATA["resources"]["demo-server-image"]["upstream-source"]
    }

    # Deploy the charm and wait for it to report blocked, as it needs Postgres.
    juju.deploy(charm, app=APP_NAME, resources=resources)
    juju.wait(jubilant.all_blocked)


def test_workload_version_is_set(charm: pathlib.Path, juju: jubilant.Juju):
    """Verify that the workload version has been set."""
    expected_version = "2.1.0"  # Hardcoded for simplicity.
    juju.wait(lambda status: status.apps[APP_NAME].version == expected_version)


@pytest.mark.juju_setup
def test_database_integration(charm: pathlib.Path, juju: jubilant.Juju):
    """Verify that the charm integrates with the database.

    Assert that the charm is active if the integration is established.

    This test includes diagnostic logging to investigate why postgresql-k8s
    sometimes takes a long time to reach active status.
    """
    juju.deploy("postgresql-k8s", channel="14/stable", trust=True)
    juju.integrate(APP_NAME, "postgresql-k8s")

    # Poll for active status with diagnostic logging instead of a black-box wait.
    timeout = 20 * 60
    interval = 15
    start = time.monotonic()
    last_status = None

    while time.monotonic() - start < timeout:
        status = juju.status()
        pg = status.apps.get("postgresql-k8s")
        if pg is None:
            logger.info("[%.0fs] postgresql-k8s not yet in status", time.monotonic() - start)
            time.sleep(interval)
            continue

        app_current = pg.app_status.current
        app_message = pg.app_status.message
        unit = pg.units.get("postgresql-k8s/0")
        unit_current = unit.workload_status.current if unit else "unknown"
        unit_message = unit.workload_status.message if unit else "unknown"

        current = (app_current, app_message, unit_current, unit_message)
        if current != last_status:
            elapsed = time.monotonic() - start
            logger.info(
                "[%.0fs] postgresql-k8s: app=%s (%s), unit=%s (%s)",
                elapsed, app_current, app_message, unit_current, unit_message,
            )
            last_status = current

            # When the unit is waiting, run diagnostics to understand the delay.
            if unit_current == "waiting" and "primary endpoint" in (unit_message or ""):
                _log_diagnostics(juju, elapsed)

        if jubilant.all_active(status):
            logger.info(
                "postgresql-k8s became active after %.1f seconds", time.monotonic() - start
            )
            return

        time.sleep(interval)

    # Final status before timeout.
    status = juju.status()
    raise TimeoutError(
        f"wait timed out after {timeout}s\n{status}"
    )


def _log_diagnostics(juju: jubilant.Juju, elapsed: float):
    """Log diagnostic information about the postgresql-k8s pod and Patroni."""
    # Show the pod status and recent events.
    _run_and_log(elapsed, "kubectl get pods -A", timeout=10)
    _run_and_log(elapsed, "kubectl get svc -A | grep -i postgres", timeout=10)
    _run_and_log(elapsed, "kubectl get endpoints -A | grep -i postgres", timeout=10)

    # Check if the postgresql-k8s Patroni REST API is responding.
    _run_and_log(
        elapsed,
        "kubectl exec -n $(juju models --format=json | "
        "python3 -c 'import json,sys; print(json.load(sys.stdin)[\"models\"][0][\"short-name\"])') "
        "postgresql-k8s-0 -- curl -s http://localhost:8008/health 2>&1 || true",
        timeout=15,
    )

    # Show recent postgresql-k8s charm logs.
    _run_and_log(
        elapsed,
        "juju debug-log --replay --limit 20 2>&1 | grep -i 'postgresql-k8s' | tail -10",
        timeout=15,
    )


def _run_and_log(elapsed: float, cmd: str, timeout: int = 10):
    """Run a shell command and log its output with a timestamp prefix."""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout,
        )
        output = (result.stdout + result.stderr).strip()
        if output:
            for line in output.splitlines():
                logger.info("[%.0fs] diag: %s", elapsed, line)
    except subprocess.TimeoutExpired:
        logger.info("[%.0fs] diag: (command timed out: %s)", elapsed, cmd)
    except Exception as e:
        logger.info("[%.0fs] diag: (error running command: %s)", elapsed, e)
