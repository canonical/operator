---
myst:
  html_meta:
    description: Manage system packages (APT and snaps) and workloads in a machine charm, with unit tests using ops.testing and integration tests using Jubilant.
---

(run-workloads-with-a-charm-machines)=
# How to run workloads with a machine charm

A machine charm typically installs one or more system packages (from APT or as snaps), then starts and manages the workload as a long-running service. This guide shows patterns for structuring that code, installing packages, managing the service lifecycle, and testing the charm.

For a complete worked example, see the [machine-tinyproxy](https://github.com/canonical/operator/tree/main/examples/machine-tinyproxy) example charm and the {ref}`machine-charm-tutorial` tutorial. For a production charm, see [ubuntu-manpages-operator](https://github.com/canonical/ubuntu-manpages-operator).

## Put workload logic in its own module

Keep charming concerns (event handlers, status, config parsing) in `src/charm.py`, and put workload-specific logic (installing, starting, configuring, stopping the workload) in a separate module such as `src/myworkload.py`. The charm calls the module; the module doesn't know about Ops.

This separation:

- Makes the workload code reusable and easy to read.
- Lets you unit test the charm by mocking the module (no `subprocess` patching in state-transition tests).
- Lets you unit test the module on its own, patching only its direct system calls.

If you use `charmcraft init --profile machine`, Charmcraft creates `charm.py` and `<workload>.py` placeholders in the `src` directory.

Call the workload module from `charm.py`:

```python
import ops
import myworkload


class MyCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on.install, self._on_install)
        framework.observe(self.on.start, self._on_start)
        framework.observe(self.on.stop, self._on_stop)
        framework.observe(self.on.remove, self._on_remove)
        framework.observe(self.on.collect_unit_status, self._on_collect_status)

    def _on_install(self, event: ops.InstallEvent) -> None:
        if not myworkload.is_installed():
            myworkload.install()
            self.unit.set_workload_version(myworkload.get_version())

    def _on_start(self, event: ops.StartEvent) -> None:
        myworkload.start()

    def _on_stop(self, event: ops.StopEvent) -> None:
        myworkload.stop()

    def _on_remove(self, event: ops.RemoveEvent) -> None:
        # On shared machines, avoid automatically uninstalling system packages.
        # Stop the workload here, and only remove packages as an explicit,
        # charm-specific step when you know the machine is dedicated to it.
        myworkload.stop()

    def _on_collect_status(self, event: ops.CollectStatusEvent) -> None:
        if not myworkload.is_installed():
            event.add_status(ops.MaintenanceStatus("Installing workload"))
        if not myworkload.is_running():
            event.add_status(ops.MaintenanceStatus("Starting workload"))
        event.add_status(ops.ActiveStatus())
```

For more guidance, see {ref}`design-your-python-modules`.

## Install system packages

Prefer purpose-built Python libraries over subprocess calls to `apt-get` or `snap`. Libraries give you typed errors, idempotent operations, and avoid the pitfalls of parsing CLI output.

### APT packages

Use {external+charmlibs:ref}`charmlibs-apt <charmlibs-apt>`. Add it to `pyproject.toml`:

```toml
dependencies = [
    "charmlibs-apt>=1,<2",
    # ...
]
```

Then install a pinned version of the package from the charm's base:

```python
# src/myworkload.py
from charmlibs import apt


def install() -> None:
    apt.update()
    # Pin to a specific version so deployments are reproducible.
    apt.add_package("tinyproxy-bin", "1.11.1-3")
    # On failure, apt raises charmlibs.apt.PackageError, which puts the
    # charm into error status with a clear message in the Juju logs.


def uninstall() -> None:
    apt.remove_package("tinyproxy-bin")
```

```{admonition} Best practice
:class: hint

Pin workload versions rather than installing the latest available package. A charm that silently upgrades between reconciliations is hard to debug, and can break if upstream introduces a breaking change.
```

### Snap packages

Use {external+charmlibs:ref}`charmlibs-snap <charmlibs-snap>`:

```toml
dependencies = [
    "charmlibs-snap>=1,<2",
    # ...
]
```

```python
# src/myworkload.py
from charmlibs import snap


def install() -> None:
    cache = snap.SnapCache()
    workload = cache["my-workload"]
    workload.ensure(snap.SnapState.Latest, channel="stable")


def start() -> None:
    snap.SnapCache()["my-workload"].start(enable=True)


def stop() -> None:
    snap.SnapCache()["my-workload"].stop(disable=True)
```

### When there's no library

If no library is available for installing the workload, use `subprocess` to run commands that install and start the workload. Keep these calls isolated in the workload module.

```{admonition} Best practice
:class: hint

When running subprocesses:
- Use absolute paths to avoid PATH-based attacks. For example, `/usr/bin/apt` rather than `apt`.
- Pass arguments as a list, not a shell string, so the shell doesn't interpret them.
- Use `check=True` so that failures raise. Generally you will want to catch that exception, then log the return code and possibly `stderr`. Use `capture_output=True` so that output from the command doesn't leak into the Juju log.
```

### Uninstall with care on shared machines

A machine charm doesn't necessarily own its machine. Another charm may have installed the same package before you did, may install it after you, or may rely on it for an unrelated purpose. Removing the package on `remove` can break those other consumers.

In your `remove` handler, always clean up the things that are unambiguously yours:

- Config files and data directories your charm wrote.
- systemd drop-ins or unit files your charm created.
- Workload state that no other consumer would expect to find, such as a PID file you maintain.

Be more cautious about the package itself. If you can't be sure that you're the only consumer, leave the package installed and just stop the service you started. The cost of leaving an unused package on a machine is much smaller than the cost of breaking another charm.

## Manage the service lifecycle

How you start, stop, and signal the workload depends on how the package runs it:

- **systemd units** (most APT packages) — use {external+charmlibs:ref}`charmlibs-systemd <charmlibs-systemd>`, or call `systemctl` as a subprocess.
- **snap services** — use `start`, `stop`, and `restart` methods of the {external+charmlibs:ref}`charmlibs-snap <charmlibs-snap>` library.
- **A process you launch directly** — use `subprocess.run` to start the daemon. The charm process is short-lived, so the command you run should return immediately and have a daemonized process. Send signals with `os.kill` (such as `SIGTERM` to stop and `SIGUSR1` to reload config). Read the workload's man page for the signals it supports.

For example, signalling a directly-launched process to reload its config:

```python
import os
import signal

from charmlibs import pathops

PID_FILE = pathops.LocalPath("/var/run/myworkload.pid")


def reload_config() -> None:
    pid = int(PID_FILE.read_text())
    os.kill(pid, signal.SIGUSR1)
```

## Observe the right events

For a long-running workload, the core lifecycle is:

- `install` — install packages and set the workload version.
- `start` — start the service.
- `config_changed` — write a new config file and signal the workload (or restart it).
- `stop` / `remove` — stop the service and uninstall packages.
- `collect_unit_status` — report status to Juju at the end of every hook, based on the current state of the workload.

For a longer-lived charm that may be upgraded in place, also observe `upgrade_charm` and re-run the install and config steps so that packages and config stay in sync with the charm revision.

## Write unit tests

Unit tests for a machine charm come in two layers, matching the charm's modules. Together they cover the whole charm without ever installing the real package.

### State-transition tests for the charm

Use `ops.testing.Context` and `ops.testing.State` to simulate events. Because the charm only calls the workload module, you mock the module — not `subprocess` or `apt` — so the tests stay readable and stable.

```python
# tests/unit/test_charm.py
import pytest
from ops import testing

from charm import MyCharm


class MockWorkload:
    """In-memory stand-in for the workload module."""

    def __init__(self, installed: bool = False, running: bool = False):
        self.installed = installed
        self.running = running
        self.signals: list[str] = []

    def install(self) -> None:
        self.installed = True

    def uninstall(self) -> None:
        self.installed = False

    def is_installed(self) -> bool:
        return self.installed

    def start(self) -> None:
        self.running = True

    def stop(self) -> None:
        self.running = False

    def is_running(self) -> bool:
        return self.running

    def reload_config(self) -> None:
        self.signals.append("SIGUSR1")

    def get_version(self) -> str:
        return "1.0.0"


@pytest.fixture
def workload(monkeypatch: pytest.MonkeyPatch) -> MockWorkload:
    mock = MockWorkload()
    monkeypatch.setattr("charm.myworkload", mock)
    return mock


def test_install(workload: MockWorkload):
    # Arrange
    ctx = testing.Context(MyCharm)
    # Act
    state_out = ctx.run(ctx.on.install(), testing.State())
    # Assert
    assert workload.is_installed()
    assert state_out.workload_version == "1.0.0"


def test_start(workload: MockWorkload):
    workload.installed = True
    ctx = testing.Context(MyCharm)
    state_out = ctx.run(ctx.on.start(), testing.State())
    assert workload.is_running()
    assert state_out.unit_status == testing.ActiveStatus()


def test_stop(workload: MockWorkload):
    workload.installed = True
    workload.running = True
    ctx = testing.Context(MyCharm)
    ctx.run(ctx.on.stop(), testing.State())
    assert not workload.is_running()
```

### Tests for the workload module

Test the module directly by patching the things it actually calls — `apt`, `subprocess.run`, `os.kill`, the snap cache, and so on. Keep these tests small: they exist to check that the module invokes its dependencies correctly, not to test those dependencies.

```python
# tests/unit/test_myworkload.py
import signal

import pytest

from charm import myworkload


def test_install_calls_apt(monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "charm.myworkload.apt.update", lambda: calls.append(("update", "")),
    )
    monkeypatch.setattr(
        "charm.myworkload.apt.add_package",
        lambda name, version: calls.append((name, version)),
    )
    myworkload.install()
    assert calls == [("update", ""), ("tinyproxy-bin", "1.11.1-3")]


def test_reload_config_sends_sigusr1(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
):
    pid_file = tmp_path / "myworkload.pid"
    pid_file.write_text("1234")
    monkeypatch.setattr("charm.myworkload.PID_FILE", pid_file)

    sent: list[tuple[int, int]] = []
    monkeypatch.setattr("os.kill", lambda pid, sig: sent.append((pid, sig)))

    myworkload.reload_config()
    assert sent == [(1234, signal.SIGUSR1)]


def test_start_runs_subprocess(monkeypatch: pytest.MonkeyPatch):
    commands: list[list[str]] = []
    monkeypatch.setattr(
        "subprocess.run",
        lambda cmd, **kwargs: commands.append(cmd) or None,
    )
    myworkload.start()
    assert commands == [["myworkload"]]
```

### Run the tests

Run all your unit tests with:

```text
tox -e unit
```

For more on state-transition testing — including `State.from_context`, reusing state across events, and accessing the charm instance — see {ref}`write-unit-tests-for-a-charm`.

## Write integration tests

Integration tests deploy the packed charm to a real Juju model and check that the workload actually installs, starts, and behaves correctly. Use {external+jubilant:doc}`Jubilant <index>` and [`pytest-jubilant`](https://github.com/canonical/pytest-jubilant).

```python
# tests/integration/test_charm.py
import pathlib

import jubilant


def test_deploy(charm: pathlib.Path, juju: jubilant.Juju):
    juju.deploy(charm.resolve(), app="myworkload")
    juju.wait(jubilant.all_active, timeout=600)


def test_workload_version(juju: jubilant.Juju):
    version = juju.status().apps["myworkload"].version
    assert version == "1.11.1"  # The version we pinned in install(), as reported by the workload.


def test_blocks_on_invalid_config(juju: jubilant.Juju):
    juju.config("myworkload", {"slug": "not/valid"})
    juju.wait(jubilant.all_blocked)
    juju.config("myworkload", reset="slug")
```

The `juju` fixture from `pytest-jubilant` creates a temporary model per test file and tears it down afterwards. You supply a `charm` fixture that locates the packed `.charm` file. For an example, see [`conftest.py` in machine-tinyproxy's integration tests](https://github.com/canonical/operator/blob/main/examples/machine-tinyproxy/tests/integration/conftest.py).

If you use `charmcraft init --profile machine`, Charmcraft creates a `charm` fixture and placeholder files for your tests.

For guidance on running the tests, see:

- {ref}`write-integration-tests-for-a-charm`
- {ref}`set-up-ci`

## Examples

- [machine-tinyproxy](https://github.com/canonical/operator/tree/main/examples/machine-tinyproxy) — the example charm from the {ref}`machine-charm-tutorial` tutorial, showing the full workload-module pattern, APT install, signal-based config reload, and both test layers.
- [ubuntu-manpages-operator](https://github.com/canonical/ubuntu-manpages-operator) — a production machine charm. See its [`tests/unit`](https://github.com/canonical/ubuntu-manpages-operator/tree/main/tests/unit) for a real-world example of the test patterns above.
- [openstack-exporter-operator](https://github.com/canonical/openstack-exporter-operator) — a production machine charm that installs its workload as a snap. The workload module is in [`src/service.py`](https://github.com/canonical/openstack-exporter-operator/blob/main/src/service.py).

## See also

- {external+charmlibs:ref}`charmlibs-apt <charmlibs-apt>`
- {external+charmlibs:ref}`charmlibs-snap <charmlibs-snap>`
- {external+charmlibs:ref}`charmlibs-systemd <charmlibs-systemd>`
- {external+charmlibs:ref}`charmlibs-pathops <charmlibs-pathops>`
