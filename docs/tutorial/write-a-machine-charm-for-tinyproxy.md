# Write a machine charm for tinyproxy

TODO:

- What you'll need.
- One/two sentence summary of what you'll do.
- How to get help, including linking to the code in the Ops repo.

## Study your application

TODO:

- Briefly introduce tinyproxy. Introduce the term "workload".
- Briefly introduce how a machine charm works. Mention that the workload and charm code run on the same machine, but that the charm code is usually not running. Explain that "receiving an event" means that Juju runs the charm code on demand, passing data in the environment. Ops provides a higher-level framework for handling events (based on the passed data) and responding to Juju.
- Summarise the experience the charm will provide: a reverse proxy with a configurable slug.

## Set up your environment

PRIMARY TODO:

- Configure nano to use spaces for indentation. (Check whether this is needed.) Or install a different editor if you like.

### Create a virtual machine

You'll work inside an Ubuntu virtual machine that's running on your computer. The virtual machine will provide an isolated environment that's safe for you to experiment in, without affecting your usual operating system.

First, install Multipass for managing virtual machines. See the [installation instructions](https://canonical.com/multipass/install).

Next, open a terminal, then run:

```text
multipass launch --cpus 4 --memory 8G --disk 50G --name juju-sandbox
```

This creates a virtual machine called `juju-sandbox`.

Multipass allocates some of your computer's memory and disk space to the virtual machine. The options we've chosen for `multipass launch` ensure that the virtual machine will be powerful enough to run Juju and deploy medium-sized charms.

It will take up to 10 minutes for Multipass to create the virtual machine, depending on your computer's specifications. When the virtual machine has been created, you'll see the message:

```text
Launched: juju-sandbox
```

Now run:

```text
multipass shell juju-sandbox
```

This switches the terminal so that you're working inside the virtual machine.

You'll see a message with information about the virtual machine. You'll also see a new prompt:

```text
ubuntu@juju-sandbox:~$
```

### Install Juju and charm development tools

Now that you have a virtual machine, you need to install the following tools in your virtual machine:

- **Charmcraft, Juju, and LXD** - You'll use Charmcraft to create the initial version of your charm and prepare your charm for deployment. When you deploy your charm, Juju will use LXD to manage the machine where your charm runs.
- **uv and tox** - You'll implement your charm using Python code. uv is a Python project manager that will install dependencies for checks and tests. You'll use tox to select which checks or tests to run.

Instead of manually installing and configuring each tool, we recommend using Concierge, Canonical's tool for setting up charm development environments.

In your virtual machine, run:

```text
sudo snap install --classic concierge
sudo concierge prepare -p machine --extra-snaps astral-uv
```

This first installs Concierge, then uses Concierge to install and configure the other tools (except tox). The option `-p machine` tells Concierge that we want tools for developing machine charms.

It will take up to 15 minutes to install the tools, depending on your computer's specifications. When the tools have been installed, you'll see a message that ends with:

```text
msg="Bootstrapped Juju" provider=lxd
```

To install tox, run:

```text
uv tool install tox --with tox-uv
uv tool update-shell
```

When tox has been installed, you'll see the message:

```text
Restart your shell to apply changes
```

It's important to exit your virtual machine at this point. If you don't exit your virtual machine, you won't be able to use tox later in the tutorial.

To exit your virtual machine, run:

```text
exit
```

The terminal switches back to your usual operating system. Your virtual machine is still running in the background.

## Create a charm project

You'll need to work inside your virtual machine again. Open a terminal, then run:

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

Charmcraft created several files, including:

- `charmcraft.yaml` - Metadata about your charm. Used by Juju and Charmcraft.
- `pyproject.toml` - Python project configuration. Lists the dependencies of your charm.
- `src/charm.py` - The Python file that will contain the main logic of your charm.
- `src/tinyproxy.py` - A helper module that will contain functions for interacting with tinyproxy.

These files currently contain placeholder code and configuration. It would be possible to deploy your charm to Juju, but it wouldn't do anything useful at this stage.

## Write your charm

### Edit the metadata

We'll start by editing the metadata in `charmcraft.yaml`.

In your virtual machine, make sure that the working directory is `~/tinyproxy`. Then run:

```text
nano charmcraft.yaml
```

This opens the "nano" text editor. If you haven't used nano before, see [nano tips on Ask Ubuntu](https://askubuntu.com/a/54222).

In nano, change the values of `title`, `summary`, and `description` to:

```yaml
title: Reverse Proxy Demo
summary: A demo charm that configures tinyproxy as a reverse proxy.
description: |
  This charm demonstrates how to write a machine charm with Ops.
```

Then save the file and exit nano.

### Write a helper module

Your charm will interact with tinyproxy, so it's a good idea to write a helper module that wraps tinyproxy.
Charmcraft created `src/tinyproxy.py` as a placeholder helper module.

The helper module will be independent of the main logic of your charm. This will make it easier to test your charm. However, the helper module won't be a general-purpose wrapper for tinyproxy. The helper module will contain opinionated functions for managing tinyproxy on Ubuntu.

The helper module will depend on some libraries that are useful when writing charms.

To add the libraries to your charm's dependencies, run:

```text
uv add charmlibs-apt charmlibs-pathops
```

This has added the following Python packages to the `dependencies` list in `pyproject.toml`:

- [`charmlibs-apt`](https://documentation.ubuntu.com/charmlibs/reference/charmlibs/apt/) - A library for using APT to manage system packages. This is how your charm will install tinyproxy.
- [`charmlibs-pathops`](https://documentation.ubuntu.com/charmlibs/reference/charmlibs/pathops/) - A file operations library, similar to `pathlib` from the standard library.

Next, replace the contents of `src/tinyproxy.py` with:

```python
import logging
import os
import shutil
import signal
import subprocess

from charmlibs import apt, pathops

logger = logging.getLogger(__name__)

CONFIG_FILE = "/etc/tinyproxy/tinyproxy.conf"
PID_FILE = "/var/run/tinyproxy.pid"


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


def get_version() -> str:
    """Get the version of tinyproxy that is installed."""
    result = subprocess.run(["tinyproxy", "-v"], check=True, capture_output=True, text=True)
    return result.stdout.removeprefix("tinyproxy").strip()


def install() -> None:
    """Use APT to install the tinyproxy executable."""
    apt.update()
    apt.add_package("tinyproxy-bin")
    # If this call fails, the charm will go into error status. The Juju logs will show the error:
    # charmlibs.apt.PackageError: Failed to install packages: tinyproxy-bin


def is_installed() -> bool:
    """Return whether the tinyproxy executable is available."""
    return shutil.which("tinyproxy") is not None


def is_running() -> bool:
    """Return whether tinyproxy is running."""
    return bool(_get_pid())


def reload_config() -> None:
    """Ask tinyproxy to reload config."""
    pid = _get_pid()
    if not pid:
        raise RuntimeError("tinyproxy is not running")
    # Sending signal SIGUSR1 doesn't terminate the process. It asks the process to reload config.
    # See https://manpages.ubuntu.com/manpages/jammy/en/man8/tinyproxy.8.html#signals
    os.kill(pid, signal.SIGUSR1)


def start() -> None:
    """configure_and_runproxy."""
    subprocess.run(["tinyproxy"], check=True, capture_output=True, text=True)


def stop() -> None:
    """Stop tinyproxy."""
    pid = _get_pid()
    if pid:
        os.kill(pid, signal.SIGTERM)


def uninstall() -> None:
    """Uninstall the tinyproxy executable and remove files."""
    apt.remove_package("tinyproxy-bin")
    pathops.LocalPath(PID_FILE).unlink(missing_ok=True)
    pathops.LocalPath(CONFIG_FILE).unlink(missing_ok=True)
    pathops.LocalPath(CONFIG_FILE).parent.rmdir()


def _get_pid() -> int | None:
    """Return the PID of the tinyproxy process, or None if the process can't be found."""
    if not pathops.LocalPath(PID_FILE).exists():
        return None
    pid = int(pathops.LocalPath(PID_FILE).read_text())
    try:
        # Sending signal 0 doesn't terminate the process. It just checks whether the PID exists.
        os.kill(pid, 0)
    except ProcessLookupError:
        return None
    return pid
```

Notice that the helper module is stateless. In fact, your charm as a whole will be stateless. The main logic of your charm will:

1. Receive an event from Juju.
2. Use the functions in the helper module to manage tinyproxy and check its status.
3. Report the status back to Juju.

```{tip}
After adding code to your charm, run `tox -e format` to format the code. Then run `tox -e lint` to check the code against coding style standards and run static checks.
```

### Handle the install event

We'll now write the charm code that handles events from Juju. Charmcraft created `src/charm.py` as the location for this logic, containing a class called `TinyproxyCharm`. We'll refer to `TinyproxyCharm` as the "charm class".

In `src/charm.py`, replace the `_on_install` method of the charm class with:

```python
    def _on_install(self, event: ops.InstallEvent) -> None:
        """Install tinyproxy on the machine."""
        if not tinyproxy.is_installed():
            tinyproxy.install()
            version = tinyproxy.get_version()
            self.unit.set_workload_version(version)
```

When your charm receives the "install" event from Juju, Ops runs this method and responds to Juju with the version of tinyproxy that's installed on the machine. Juju shows the tinyproxy version in its status output.

### Define a configuration option

After deploying your charm, you'll use the `juju config` command to change the path of the reverse proxy, so we need to define a configuration option called `slug`. We'll do this in two places:

- In `charmcraft.yaml`, to tell Juju and Ops about the configuration option.
- In the charm code, to additionally tell Ops how to validate values of the configuration option.

In `charmcraft.yaml`, replace the `config` block with:

```yaml
config:
  options:
    slug:
      description: "Configures the path of the reverse proxy. Must match the regex [a-z0-9-]+"
      default: example
      type: string
```

Then add the following class to `src/charm.py`:

```python
class TinyproxyConfig(pydantic.BaseModel):
    """Schema for the charm's config options."""

    slug: str = pydantic.Field(
        "example",
        pattern=r"^[a-z0-9-]+$",
        description="Configures the path of the reverse proxy. Must match the regex [a-z0-9-]+",
    )
```

Also add the following line at the beginning of `src/charm.py`:

```python
import pydantic
```

The `TinyproxyConfig` class uses [Pydantic](https://docs.pydantic.dev) to specify how to validate values of `slug`. The class doesn't actually load the configured value of `slug`; we'll do that elsewhere in the charm code.

To add Pydantic to your charm's dependencies, run:

```text
uv add pydantic
```

### Start tinyproxy and handle configuration changes

Your charm now needs a way to load the value of the `slug` configuration option, write a configuration file on the machine, then start tinyproxy:

1. To load the value of `slug`, we'll use the `load_config` method that Ops provides. This method also validates the value of `slug` using the `TinyproxyConfig` class that we just defined.
2. To write a configuration file, we'll use the `ensure_config` function from the helper module.
3. To start tinyproxy, we'll use the `start` function from the helper module.

In `src/charm.py`, add the following methods to the charm class:

```python
    def configure_and_run(self) -> None:
        """Ensure that tinyproxy is running with the correct config."""
        try:
            config = self.load_config(TinyproxyConfig)
        except pydantic.ValidationError:
            # The collect-status handler will run next and will set status for the user to see.
            return
        if not tinyproxy.is_installed():
            return
        changed = tinyproxy.ensure_config(PORT, config.slug)
        if not tinyproxy.is_running():
            tinyproxy.start()
            self.wait_for_running()
        elif changed:
            logger.info("Config changed while tinyproxy is running. Updating tinyproxy config")
            tinyproxy.reload_config()

    def wait_for_running(self) -> None:
        """Wait for tinyproxy to be running."""
        for _ in range(3):
            if tinyproxy.is_running():
                return
            time.sleep(1)
        raise RuntimeError("tinyproxy was not running within the expected time")
        # Raising a runtime error will put the charm into error status. The error message is for
        # you (the charm author) to see in the Juju logs, not for the user of the charm.
```

Then add the following lines at the beginning of `src/charm.py`:

```python
import time

PORT = 8000
```

The `configure_and_run` method ensures that tinyproxy is running and correctly configured, regardless of whether tinyproxy was already running. We can therefore use this method to handle two different Juju events: "start" and "config-changed".

Replace the `_on_start` method of the charm class with:

```python
    def _on_start(self, event: ops.StartEvent) -> None:
        """Handle start event."""
        self.configure_and_run()
```

Next, add the following line to the `__init__` method of the charm class:

```python
        framework.observe(self.on.config_changed, self._on_config_changed)
```

Then add the following method to the charm class:

```python
    def _on_config_changed(self, event: ops.ConfigChangedEvent) -> None:
        """Handle config-changed event."""
        self.configure_and_run()
```

### Report status to Juju

Your charm should report the machine's status to Juju after handling each event. This enables you to use Juju's status output to see whether tinyproxy is running and correctly configured.

One option would be to modify each method in the charm class to report an appropriate status. However, this tends to be awkward in practice, because the logic to decide which status is most appropriate can become complex. Instead, we'll handle a special "collect-unit-status" event that is produced by Ops.

Add the following line to the `__init__` method of the charm class:

```python
        framework.observe(self.on.collect_unit_status, self._on_collect_status)
```

Then add the following method to the charm class:

```python
    def _on_collect_status(self, event: ops.CollectStatusEvent) -> None:
        """Report the status of tinyproxy (runs after each event)."""
        try:
            self.load_config(TinyproxyConfig)
        except pydantic.ValidationError as e:
            slug_error = e.errors()[0]  # Index 0 because 'slug' is the only option validated.
            slug_value = slug_error["input"]
            message = f"Invalid slug: '{slug_value}'. Slug must match the regex [a-z0-9-]+"
            event.add_status(ops.BlockedStatus(message))
        if not tinyproxy.is_installed():
            event.add_status(ops.MaintenanceStatus("Waiting for tinyproxy to be installed"))
        if not tinyproxy.is_running():
            event.add_status(ops.MaintenanceStatus("Waiting for tinyproxy to start"))
        event.add_status(ops.ActiveStatus())
```

Ops runs this method after each Juju event, regardless of whether the charm code handles the event. After running the method, Ops decides which status to report to Juju, choosing the highest priority status that was proposed with `event.add_status`.

For example, if the value of the `slug` configuration option is invalid, `load_config` raises an error and the charm code proposes a "blocked" status. This status means that your charm needs intervention from a human, so Ops gives it the highest priority and reports it to Juju.

### Stop and uninstall tinyproxy

If Juju wants to remove a unit of the application, your charm (on that unit) receives the "stop" event followed by the "remove" event.

To handle these events, add the following lines to the `__init__` method of the charm class:

```python
        framework.observe(self.on.stop, self._on_stop)
        framework.observe(self.on.remove, self._on_remove)
```

Then add the following methods to the charm class:

```python
    def _on_stop(self, event: ops.StopEvent) -> None:
        """Handle stop event."""
        tinyproxy.stop()
        self.wait_for_not_running()

    def _on_remove(self, event: ops.RemoveEvent) -> None:
        """Handle remove event."""
        tinyproxy.uninstall()

    def wait_for_not_running(self) -> None:
        """Wait for tinyproxy to not be running."""
        for _ in range(3):
            if not tinyproxy.is_running():
                return
            time.sleep(1)
        raise RuntimeError("tinyproxy was still running after the expected time")
```

## Try your charm

### Pack your charm

Before you can try your charm, you need to "pack" it. Packing combines the charm code and metadata into a single file that can be deployed to Juju.

In your virtual machine, make sure that the working directory is `~/tinyproxy`. Then run:

```text
charmcraft pack
```

Charmcraft will take about 20 minutes to pack your charm, depending on your computer and network.

When Charmcraft has packed your charm, you'll see a message similar to:

```text
Packed tinyproxy_amd64.charm
```

The name of the `.charm` file depends on your computer's architecture. For example, if your computer has an ARM-based architecture, the file is called `tinyproxy_arm64.charm`.

### Deploy your charm

As you deploy your charm to Juju, it will be helpful to watch Juju status in real time.

Open another terminal, then run:

```text
multipass shell juju-sandbox
```

Next, in the same terminal, run:

```text
juju status --watch 2s
```

You should now have two terminals:

- A terminal with working directory `~/tinyproxy`, from earlier.

- A terminal that shows Juju status in real time:

    ```text
    Model    Controller     Cloud/Region         Version  SLA          Timestamp
    testing  concierge-lxd  localhost/localhost  3.6.8    unsupported  09:00:00+08:00
    ```

You're now ready to deploy your charm.

In the `~/tinyproxy` directory, run `juju deploy ./<charm-file>`, where `<charm-file`> is the name of the file created by `charmcraft pack`. For example:

```text
juju deploy ./tinyproxy_amd64.charm
```

Juju creates an "application" from your charm. For each unit in the application, Juju starts a machine and installs your charm on the machine. We didn't tell Juju how many units we want, so Juju assumes one unit and starts one machine. After Juju has installed your charm on the machine, Juju starts sending events to your charm so that your charm can install and start tinyproxy.

When your charm has started tinyproxy, the application will go into "active" status:

```text
Model    Controller     Cloud/Region         Version  SLA          Timestamp
testing  concierge-lxd  localhost/localhost  3.6.8    unsupported  09:01:38+08:00

App        Version  Status  Scale  Charm      Channel  Rev  Exposed  Message
tinyproxy  1.11.0   active      1  tinyproxy             0  no

Unit          Workload  Agent  Machine  Public address  Ports  Message
tinyproxy/0*  active    idle   0        10.71.67.208

Machine  State    Address       Inst id        Base          AZ  Message
0        started  10.71.67.208  juju-8e7bd9-0  ubuntu@22.04      Running
```

```{tip}
For the rest of the tutorial, we'll assume that you're still watching Juju status. To stop watching, press <kbd>Ctrl</kbd> + <kbd>C</kbd>.
```

### Try the reverse proxy

Now that tinyproxy is running, we can check that it proxies [example.com](http://example.com) on the machine's network.

In your virtual machine, run:

```text
curl <address>:8000/example/
```

Where `<address>` is the IP address of machine 0 from Juju status. In our example of Juju status, the IP address is 10.71.67.208.

The output of curl should be similar to:

```text
<!doctype html><html lang="en"><head><title>Example Domain</title>...
```

Then run `curl http://example.com` and check that you get the same output.

### Change the configuration

Let's see what happens to the reverse proxy if we change the `slug` configuration option. Run:

```text
juju config tinyproxy slug=foo
```

Where `<address>` is the IP address of machine 0 from Juju status.

You might see the message "(config-changed)" briefly appear in Juju status as your charm handles the config-changed event.

Then run:

```text
curl <address>:8000/foo/
```

The output should be the same as when you ran `curl <address>:8000/example/`. Now run:

```text
curl <address>:8000/example/
```

The output should contain "400 Bad Request". These outputs confirm that your charm successfully reconfigured tinyproxy to use `/foo/` instead of `/example/` for the path of the reverse proxy.

Next, let's try an invalid value of `slug`:

```
juju config tinyproxy slug=foo/bar
```

Juju status should now show "blocked" and a message about the invalid value.

To unblock your charm, reset `slug` to `example`:

```
juju config tinyproxy --reset slug
```

## Write unit tests for your charm

### Write tests for the helper module

When writing a charm, it's good practice to write unit tests for the charm code that interacts with the workload (tinyproxy). Typically, you'd mock external calls, such as file operations. To illustrate the approach, we'll write a unit test for the `get_version` function in the helper module.

Create a file `tests/unit/test_tinyproxy.py` containing:

```python
import pytest

from charm import tinyproxy


class MockVersionProcess:
    """Mock object that represents the result of calling 'tinyproxy -v'."""

    def __init__(self, version: str):
        self.stdout = f"tinyproxy {version}"


def test_version(monkeypatch: pytest.MonkeyPatch):
    """Test that the helper module correctly returns the version of tinyproxy."""
    version_process = MockVersionProcess("1.11.0")
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: version_process)
    assert tinyproxy.get_version() == "1.11.0"
```

We'll run all the unit tests later in the tutorial. But if you'd like to see whether this unit test passes, you can run `tox -e unit -- tests/unit/test_tinyproxy.py`.

### Write state-transition tests

We should write unit tests for the charm code that handles events. Each test will be structured as a "state-transition" test, using the testing framework that comes with Ops.

State-transition tests are isolated tests of event handlers. They test how your charm responds to simulated events from Juju. It's helpful to think of each test this way:

1. Ops mocks the input to a particular event handler, based on details that you provide. You mock the interaction between the event handler and the workload. For tinyproxy, we'll define a mock object that represents the state of tinyproxy and we'll patch the helper module to act on this mock object.
2. Ops runs the event handler with the mocked input, which simulates your charm receiving the event.
3. You assert that the event handler acted correctly.

Replace the contents of `tests/unit/test_charm.py` with:

```python
import pytest
from ops import testing

from charm import PORT, TinyproxyCharm


class MockTinyproxy:
    """Mock object that represents tinyproxy."""

    def __init__(
        self,
        config: None | tuple[int, str] = None,
        installed: bool = False,
        reloaded_config: bool = False,
        running: bool = False,
    ):
        self.config = config
        self.installed = installed
        self.reloaded_config = reloaded_config
        self.running = running

    def ensure_config(self, port: int, slug: str) -> bool:
        old_config = self.config
        self.config = (port, slug)
        return self.config != old_config

    def get_version(self) -> str:
        return "1.11.0"

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

    def uninstall(self) -> None:
        self.installed = False


def patch_charm(monkeypatch: pytest.MonkeyPatch, tinyproxy: MockTinyproxy):
    """Patch the helper module to use mock functions for interacting with tinyproxy."""
    monkeypatch.setattr("charm.tinyproxy.ensure_config", tinyproxy.ensure_config)
    monkeypatch.setattr("charm.tinyproxy.get_version", tinyproxy.get_version)
    monkeypatch.setattr("charm.tinyproxy.install", tinyproxy.install)
    monkeypatch.setattr("charm.tinyproxy.is_installed", tinyproxy.is_installed)
    monkeypatch.setattr("charm.tinyproxy.is_running", tinyproxy.is_running)
    monkeypatch.setattr("charm.tinyproxy.start", tinyproxy.start)
    monkeypatch.setattr("charm.tinyproxy.stop", tinyproxy.stop)
    monkeypatch.setattr("charm.tinyproxy.reload_config", tinyproxy.reload_config)
    monkeypatch.setattr("charm.tinyproxy.uninstall", tinyproxy.uninstall)


def test_install(monkeypatch: pytest.MonkeyPatch):
    """Test that the charm correctly handles the install event."""
    # A state-transition test has three broad steps:
    # Step 1. Arrange the input state.
    tinyproxy = MockTinyproxy()
    patch_charm(monkeypatch, tinyproxy)
    ctx = testing.Context(TinyproxyCharm)
    state_in = testing.State()
    # Step 2. Simulate an event, in this case an install event.
    state_out = ctx.run(ctx.on.install(), state_in)
    # Step 3. Check the output state.
    assert state_out.workload_version is not None
    assert state_out.unit_status == testing.MaintenanceStatus("Waiting for tinyproxy to start")
    assert tinyproxy.is_installed()


# For convenience, define a reusable fixture that provides a MockTinyproxy object
# and patches the helper module in the charm.
@pytest.fixture
def tinyproxy_installed(monkeypatch: pytest.MonkeyPatch):
    tinyproxy = MockTinyproxy(installed=True)
    patch_charm(monkeypatch, tinyproxy)
    return tinyproxy


def test_start(tinyproxy_installed: MockTinyproxy):
    """Test that the charm correctly handles the start event."""
    ctx = testing.Context(TinyproxyCharm)
    state_out = ctx.run(ctx.on.start(), testing.State())
    assert state_out.unit_status == testing.ActiveStatus()
    assert tinyproxy_installed.is_running()
    assert tinyproxy_installed.config == (PORT, "example")


# Define another fixture, this time representing an installed, configured, and running tinyproxy.
@pytest.fixture
def tinyproxy_configured(monkeypatch: pytest.MonkeyPatch):
    tinyproxy = MockTinyproxy(config=(PORT, "example"), installed=True, running=True)
    patch_charm(monkeypatch, tinyproxy)
    return tinyproxy


def test_config_changed(tinyproxy_configured: MockTinyproxy):
    """Test that the charm correctly handles the config-changed event."""
    ctx = testing.Context(TinyproxyCharm)
    state_in = testing.State(config={"slug": "foo"})
    state_out = ctx.run(ctx.on.config_changed(), state_in)
    assert state_out.unit_status == testing.ActiveStatus()
    assert tinyproxy_configured.is_running()
    assert tinyproxy_configured.config == (PORT, "foo")
    assert tinyproxy_configured.reloaded_config


# Define a reusable fixture that provides invalid slugs.
@pytest.fixture(params=["", "foo_bar", "foo/bar"])
def invalid_slug(request):
    return request.param


def test_start_invalid_config(tinyproxy_installed: MockTinyproxy, invalid_slug: str):
    """Test that the charm fails to start if the config is invalid."""
    ctx = testing.Context(TinyproxyCharm)
    state_in = testing.State(config={"slug": invalid_slug})
    state_out = ctx.run(ctx.on.start(), state_in)
    assert state_out.unit_status == testing.BlockedStatus(
        f"Invalid slug: '{invalid_slug}'. Slug must match the regex [a-z0-9-]+"
    )
    assert not tinyproxy_installed.is_running()
    assert tinyproxy_installed.config is None


def test_config_changed_invalid_config(tinyproxy_configured: MockTinyproxy, invalid_slug: str):
    """Test that the charm fails to change config if the config is invalid."""
    ctx = testing.Context(TinyproxyCharm)
    state_in = testing.State(config={"slug": invalid_slug})
    state_out = ctx.run(ctx.on.config_changed(), state_in)
    assert state_out.unit_status == testing.BlockedStatus(
        f"Invalid slug: '{invalid_slug}'. Slug must match the regex [a-z0-9-]+"
    )
    assert tinyproxy_configured.is_running()  # tinyproxy should still be running...
    assert tinyproxy_configured.config == (PORT, "example")  # ...with the original config.
    assert not tinyproxy_configured.reloaded_config


def test_stop(tinyproxy_configured: MockTinyproxy):
    """Test that the charm correctly handles the stop event."""
    ctx = testing.Context(TinyproxyCharm)
    state_out = ctx.run(ctx.on.stop(), testing.State())
    assert state_out.unit_status == testing.MaintenanceStatus("Waiting for tinyproxy to start")
    assert not tinyproxy_configured.is_running()


def test_remove(tinyproxy_installed: MockTinyproxy):
    """Test that the charm correctly handles the remove event."""
    ctx = testing.Context(TinyproxyCharm)
    state_out = ctx.run(ctx.on.remove(), testing.State())
    assert state_out.unit_status == testing.MaintenanceStatus(
        "Waiting for tinyproxy to be installed"
    )
    assert not tinyproxy_installed.is_installed()
```

### Run the tests

Run the following command from anywhere in the `~/tinyproxy` directory:

```text
tox -e unit
```

The output should be similar to:

```text
...

============================================ 12 passed in 0.43s =============================================
unit: commands[1]> coverage report
Name               Stmts   Miss Branch BrPart  Cover   Missing
--------------------------------------------------------------
src/charm.py          72      5     20      7    87%   67->exit, 97, 102->exit, 111-112, 121-122
src/tinyproxy.py      47     26      6      0    40%   34-41, 52-53, 60, 65, 70-75, 80, 85-87, 92-95, 100-108
--------------------------------------------------------------
TOTAL                119     31     26      7    70%
  unit: OK (1.21=setup[0.05]+cmd[1.03,0.13] seconds)
  congratulations :) (1.30 seconds)
```

## Write integration tests for your charm

TODO

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
