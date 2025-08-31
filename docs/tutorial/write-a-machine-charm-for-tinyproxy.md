# Write a machine charm for tinyproxy

```{important}
This tutorial is a **work in progress**. Some steps don't work yet. For now, please use [](./write-your-first-machine-charm).
```

TODO:

- What you'll need.
- One/two sentence summary of what you'll do.
- How to get help, including linking to the code in the Ops repo.

## Study your application

TODO:

- Briefly introduce tinyproxy.
- Briefly introduce how a machine charm works.
- Summarise the experience the charm will provide - reverse proxy with a configurable slug.

## Set up your environment

### Create a virtual machine

TODO: Multipass

### Install Juju and charm development tools

TODO: Charmcraft, Juju, LXD (all using Concierge)

### Install Python development tools

TODO: uv (as an extra snap from Concierge), tox (with `uv tool`)

## Create a charm project

You'll need to work inside the virtual machine again. Open a terminal, then run:

```text
multipass shell juju-sandbox
```

The terminal prompt is now `ubuntu@juju-sandbox:~$`.

Next, create a project directory and use Charmcraft to create the initial version of your charm:

```text
mkdir tinyproxy
cd tinyproxy
charmcraft init --profile machine
```

TODO:

- Briefly summarise the most important files that Charmcraft creates.
- Edit charmcraft.yaml to set the title, description, summary, and platform.
- Suggest using nano to edit files.

## Write your charm

### Write a helper module

Your charm will interact with tinyproxy, so it's a good idea to start by writing a helper module that wraps tinyproxy.
Charmcraft created `src/tinyproxy.py` as a placeholder helper module.

The helper module will be independent of the main logic of your charm. This will make it easier to test your charm. However, the helper module won't be a general-purpose wrapper for tinyproxy. The helper module will contain opinionated functions for managing tinyproxy on Ubuntu.

The helper module will depend on some libraries that are useful when writing charms. Add the libraries to your charm's dependencies:

```text
uv add charmlibs-apt charmlibs-pathops
```

This has added the following Python packages to the `dependencies` list in `pyproject.toml`:

- [`charmlibs-apt`](https://documentation.ubuntu.com/charmlibs/reference/charmlibs/apt/) - A library for using APT to manage system packages. This is how your charm will install tinyproxy.
- [`charmlibs-pathops`](https://documentation.ubuntu.com/charmlibs/reference/charmlibs/pathops/) - A file operations library, similar to `pathlib` from the standard library.

TODO: Can we make these intersphinx links?

Next, replace the contents of `src/tinyproxy.py` with:

```python
import logging
import os
import re
import shutil
import signal
import subprocess

from charmlibs import apt, pathops

logger = logging.getLogger(__name__)

CONFIG_FILE = "/etc/tinyproxy/tinyproxy.conf"
PID_FILE = "/var/run/tinyproxy.pid"


def check_slug(slug: str) -> None:
    """Check that the URL slug is valid. Raise ValueError otherwise."""
    if not re.fullmatch(r"[a-z0-9-]+", slug):
        raise ValueError(f"Invalid slug: '{slug}'. Slug must match the regex [a-z0-9-]+")


def ensure_config(port: int, slug: str) -> bool:
    """Ensure that tinyproxy is configured. Return True if any changes were made."""
    # For the config file format, see https://manpages.ubuntu.com/manpages/jammy/en/man5/tinyproxy.conf.5.html
    config = f"""\
PidFile "{PID_FILE}"
Port {port}
Timeout 600
ReverseOnly Yes
ReversePath "/{slug}/" "http://www.example.com/"
"""
    return pathops.ensure_contents(CONFIG_FILE, config)


def install() -> None:
    """Use APT to install the tinyproxy executable."""
    apt.update()
    try:
        apt.add_package("tinyproxy-bin")
    except apt.PackageError as e:
        logger.error("Unable to install tinyproxy-bin. %s", e.message)
        raise


def is_installed() -> bool:
    """Return whether the tinyproxy executable is available."""
    return shutil.which("tinyproxy") is not None


def is_running() -> bool:
    """Return whether tinyproxy is running."""
    return pathops.LocalPath(PID_FILE).exists()


def start() -> None:
    """Start tinyproxy."""
    subprocess.run(["tinyproxy"], check=True)


def stop() -> None:
    """Stop tinyproxy."""
    os.kill(_get_pid(), signal.SIGTERM)


def reload_config() -> None:
    """Ask tinyproxy to reload config."""
    # See https://manpages.ubuntu.com/manpages/jammy/en/man8/tinyproxy.8.html#signals
    os.kill(_get_pid(), signal.SIGUSR1)


def _get_pid() -> int:
    """Return the PID of tinyproxy."""
    return int(pathops.LocalPath(PID_FILE).read_text())
```

Notice that the helper module is stateless. In fact, your charm as a whole will be stateless. The main logic of your charm will:

1. Receive an event from Juju. For example, the `start` event, meaning "it's time to start tinyproxy".
2. Use the functions in the helper module to manage tinyproxy and check its status.
3. Report the status back to Juju.

```{tip}
After adding code to your charm, run `tox -e lint` to check the code against coding style standards and run static checks. If the code has formatting issues, you can use `tox -e format` to format the code.
```

### Define a configuration option

TODO: Add commentary to this section.

`charmcraft.yaml`:

```yaml
config:
  options:
    slug:
      description: |
        Configures the path of the reverse proxy.

        Must match the regex [a-z0-9-]+
      default: example
      type: string
```

`src/charm.py`:

```python
@dataclasses.dataclass(frozen=True)
class TinyproxyConfig:
    """Schema for the configuration of the tinyproxy charm."""

    slug: str = "example"
    """Configures the path of the reverse proxy."""

    def __post_init__(self):
        tinyproxy.check_slug(self.slug)  # Raises ValueError if slug is invalid.
```

### Write the charm code (placeholder title)

TODO: Split this section up, building the code in logical steps, with commentary.

`src/charm.py`:

```python
import dataclasses
import logging

import ops

import tinyproxy

logger = logging.getLogger(__name__)

PORT = 8000


@dataclasses.dataclass(frozen=True)
class TinyproxyConfig:
    """Schema for the charm's config options."""

    slug: str = "example"
    """Configures the path of the reverse proxy."""

    def __post_init__(self):
        tinyproxy.check_slug(self.slug)  # Raises ValueError if slug is invalid.


class TinyproxyCharm(ops.CharmBase):
    """Charm the application."""

    def __init__(self, framework: ops.Framework) -> None:
        super().__init__(framework)
        framework.observe(self.on.collect_unit_status, self._on_collect_status)
        framework.observe(self.on.install, self._on_install)
        framework.observe(self.on.start, self._on_start)
        framework.observe(self.on.config_changed, self._on_config_changed)
        framework.observe(self.on.stop, self._on_stop)

    def _on_collect_status(self, event: ops.CollectStatusEvent):
        """Report the status of tinyproxy (runs after each event)."""
        try:
            self.load_config(TinyproxyConfig)
        except ValueError as e:
            event.add_status(ops.BlockedStatus(str(e)))
        if not tinyproxy.is_installed():
            event.add_status(ops.MaintenanceStatus("Waiting for tinyproxy to be installed"))
        if not tinyproxy.is_running():
            event.add_status(ops.MaintenanceStatus("Waiting for tinyproxy to start"))
        event.add_status(ops.ActiveStatus())

    def _on_install(self, event: ops.InstallEvent) -> None:
        """Install tinyproxy on the machine."""
        if not tinyproxy.is_installed():
            tinyproxy.install()

    def _on_start(self, event: ops.StartEvent) -> None:
        """Handle start event."""
        self._configure_and_restart()

    def _on_config_changed(self, event: ops.ConfigChangedEvent) -> None:
        """Handle config-changed event."""
        self._configure_and_restart()

    def _on_stop(self, event: ops.StopEvent) -> None:
        """Handle stop event."""
        tinyproxy.stop()

    def _configure_and_restart(self) -> None:
        """Ensure that tinyproxy is running with the correct config."""
        try:
            config = self.load_config(TinyproxyConfig)
        except ValueError:
            return
        if not tinyproxy.is_installed():
            return
        changed = tinyproxy.ensure_config(PORT, config.slug)
        if not tinyproxy.is_running():
            tinyproxy.start()
        elif changed:
            logger.info("Config changed while tinyproxy is running. Updating tinyproxy config")
            tinyproxy.reload_config()


if __name__ == "__main__":  # pragma: nocover
    ops.main(TinyproxyCharm)
```

## Try your charm

### Pack your charm

TODO: Add commentary to this section.

```text
charmcraft pack
```

This created the charm:

```text
CONTRIBUTING.md  charmcraft.yaml  src                    tox.ini
LICENSE          lib              tests                  uv.lock
README.md        pyproject.toml   tinyproxy_amd64.charm
```

(The charm filename depends on architecture)

### Deploy your charm

TODO: Add commentary to this section.

Open another terminal, using `multipass shell juju-sandbox`. Use this terminal to watch Juju status`. In the other terminal, deploy the charm:

```text
juju deploy ./tinyproxy_amd64.charm
```

(The charm filename depends on architecture)

When the charm is ready, you'll see:

```text
Model    Controller     Cloud/Region         Version  SLA          Timestamp
testing  concierge-lxd  localhost/localhost  3.6.8    unsupported  09:00:38+08:00

App        Version  Status  Scale  Charm      Channel  Rev  Exposed  Message
tinyproxy           active      1  tinyproxy             0  no

Unit          Workload  Agent  Machine  Public address  Ports  Message
tinyproxy/0*  active    idle   0        10.71.67.208

Machine  State    Address       Inst id        Base          AZ  Message
0        started  10.71.67.208  juju-8e7bd9-0  ubuntu@22.04      Running
```

Make a note of the IP address of the machine (10.71.67.208).

### Try the proxy

TODO: Add commentary to this section.

```text
curl <address>:8000/example/
```

Output:

```text
<!doctype html>
<html>
<head>
    <title>Example Domain</title>
    ...
</head>

<body>
<div>
    <h1>Example Domain</h1>
    <p>This domain is for use in illustrative examples in documents. You may use this
    domain in literature without prior coordination or asking for permission.</p>
    <p><a href="https://www.iana.org/domains/example">More information...</a></p>
</div>
</body>
</html>
```

### Change the configuration

TODO: Add commentary to this section.

```text
juju config tinyproxy slug=foo
curl <address>:8000/foo/  # Returns the same HTML as before.
curl <address>:8000/example/  # Returns an error page.
juju config tinyproxy slug=foo/bar  # Puts the charm into blocked status.
juju config tinyproxy --reset slug  # Makes the charm active, with the original config.
```

## Write unit tests for your charm

### Write tests for the helper module

TODO: Add commentary to this section.

`tests/unit/test_tinyproxy.py`:

```python
import pytest

from charm import tinyproxy


def test_slug_valid():
    tinyproxy.check_slug("example")  # No error raised.


def test_slug_invalid():
    with pytest.raises(ValueError):
        tinyproxy.check_slug("foo/bar")
```

### Write state-transition tests

TODO: Add commentary to this section.

`tests/unit/test_charm.py`:

```python
from dataclasses import dataclass

import pytest
from ops import testing

from charm import PORT, TinyproxyCharm


@dataclass
class MockTinyproxy:
    """Mock object that represents tinyproxy."""

    config: None | tuple[int, str] = None
    installed: bool = False
    reloaded_config: bool = False
    running: bool = False

    def ensure_config(self, port: int, slug: str) -> bool:
        old_config = self.config
        self.config = (port, slug)
        return self.config != old_config

    def install(self) -> None:
        self.installed = True

    def is_installed(self) -> bool:
        return self.installed

    def is_running(self) -> bool:
        return self.running

    def start(self) -> None:
        self.running = True

    def stop(self) -> None:
        self.running = False

    def reload_config(self) -> None:
        self.reloaded_config = True


def patch_charm(monkeypatch: pytest.MonkeyPatch, tinyproxy: MockTinyproxy):
    """Patch the helper module to use mock functions for interacting with tinyproxy."""
    monkeypatch.setattr("charm.tinyproxy.ensure_config", tinyproxy.ensure_config)
    monkeypatch.setattr("charm.tinyproxy.install", tinyproxy.install)
    monkeypatch.setattr("charm.tinyproxy.is_installed", tinyproxy.is_installed)
    monkeypatch.setattr("charm.tinyproxy.is_running", tinyproxy.is_running)
    monkeypatch.setattr("charm.tinyproxy.start", tinyproxy.start)
    monkeypatch.setattr("charm.tinyproxy.stop", tinyproxy.stop)
    monkeypatch.setattr("charm.tinyproxy.reload_config", tinyproxy.reload_config)


def test_install(monkeypatch: pytest.MonkeyPatch):
    """Test that the charm correctly handles the install event."""
    # Arrange:
    tinyproxy = MockTinyproxy()
    patch_charm(monkeypatch, tinyproxy)
    ctx = testing.Context(TinyproxyCharm)
    # Act:
    ctx.run(ctx.on.install(), testing.State())
    # Assert:
    assert tinyproxy.is_installed()


def test_start(monkeypatch: pytest.MonkeyPatch):
    """Test that the charm correctly handles the start event."""
    # Arrange:
    tinyproxy = MockTinyproxy(installed=True)
    patch_charm(monkeypatch, tinyproxy)
    ctx = testing.Context(TinyproxyCharm)
    # Act:
    state_out = ctx.run(ctx.on.start(), testing.State())
    # Assert:
    assert state_out.unit_status == testing.ActiveStatus()
    assert tinyproxy.is_running()
    assert tinyproxy.config == (PORT, "example")


def test_config_changed(monkeypatch: pytest.MonkeyPatch):
    """Test that the charm correctly handles the config-changed event."""
    # Arrange:
    tinyproxy = MockTinyproxy(config=(PORT, "example"), installed=True, running=True)
    patch_charm(monkeypatch, tinyproxy)
    ctx = testing.Context(TinyproxyCharm)
    state_in = testing.State(config={"slug": "foo"})
    # Act:
    state_out = ctx.run(ctx.on.config_changed(), state_in)
    # Assert:
    assert state_out.unit_status == testing.ActiveStatus()
    assert tinyproxy.is_running()
    assert tinyproxy.config == (PORT, "foo")
    assert tinyproxy.reloaded_config


def test_start_invalid_config(monkeypatch: pytest.MonkeyPatch):
    """Test that the charm fails to start if the config is invalid."""
    # Arrange:
    tinyproxy = MockTinyproxy(installed=True)
    patch_charm(monkeypatch, tinyproxy)
    ctx = testing.Context(TinyproxyCharm)
    state_in = testing.State(config={"slug": "foo/bar"})  # Invalid value!
    # Act:
    state_out = ctx.run(ctx.on.start(), state_in)
    # Assert:
    assert state_out.unit_status == testing.BlockedStatus(
        "Invalid slug: 'foo/bar'. Slug must match the regex [a-z0-9-]+"
    )
    assert not tinyproxy.is_running()
    assert tinyproxy.config is None


def test_config_changed_invalid_config(monkeypatch: pytest.MonkeyPatch):
    """Test that the charm fails to change config if the config is invalid."""
    # Arrange:
    tinyproxy = MockTinyproxy(config=(PORT, "example"), installed=True, running=True)
    patch_charm(monkeypatch, tinyproxy)
    ctx = testing.Context(TinyproxyCharm)
    state_in = testing.State(config={"slug": "foo/bar"})  # Invalid value!
    # Act:
    state_out = ctx.run(ctx.on.config_changed(), state_in)
    # Assert:
    assert state_out.unit_status == testing.BlockedStatus(
        "Invalid slug: 'foo/bar'. Slug must match the regex [a-z0-9-]+"
    )
    assert tinyproxy.is_running()  # tinyproxy should still be running...
    assert tinyproxy.config == (PORT, "example")  # ...with the original config.
    assert not tinyproxy.reloaded_config


def test_stop(monkeypatch: pytest.MonkeyPatch):
    """Test that the charm correctly handles the stop event."""
    # Arrange:
    tinyproxy = MockTinyproxy(installed=True)
    patch_charm(monkeypatch, tinyproxy)
    ctx = testing.Context(TinyproxyCharm)
    # Act:
    state_out = ctx.run(ctx.on.stop(), testing.State())
    # Assert:
    assert state_out.unit_status == testing.MaintenanceStatus("Waiting for tinyproxy to start")
    assert not tinyproxy.is_running()
```

### Run the tests

TODO: Add commentary to this section.

```text
tox -e unit
```

## Tear things down

TODO:

- How to remove the application from Juju.
- How to save the code that you created inside the virtual machine.
- How to stop the virtual machine.
- How to delete the virtual machine.
- How to uninstall Multipass.

## Next steps

TODO:

- Links to more detail on the concepts covered in the tutorial.
- Suggestions for real machine charms to look at.
- Suggestions for what to learn next, e.g., learn about relations.
- Challenge: Try modifying this tutorial charm to make the port configurable too.
