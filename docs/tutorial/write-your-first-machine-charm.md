(machine-charm-tutorial)=
# Write your first machine charm

In this tutorial, you'll write a machine charm for Juju using Ops and other charm development tools.

If you're new to charm development, you might find it helpful to read [Charms architecture](https://canonical.com/juju/charms-architecture) and {external+juju:ref}`Machine charm <machine-charm>` before starting the tutorial. Or jump straight in!

It will take about 2 hours for you to complete the tutorial.

What you'll need:

- A workstation. For example, a laptop with an amd64 architecture. To deploy and test your charm in a virtual machine, you'll need sufficient resources to launch a virtual machine with 4 CPUs, 8 GB RAM, and 50 GB disk space.
- Familiarity with Linux.
- Familiarity with the Python programming language, including Object-Oriented Programming and event handlers. It will be helpful if you're familiar with [pytest](https://docs.pytest.org/en/) too.

What you'll do:

- Use {external+charmcraft:doc}`Charmcraft <index>` to create a machine charm from a template.
- Add functionality to your charm, so that it can install and manage a workload on its machine.
- Test your charm, using the Ops testing framework for unit tests and {external+jubilant:doc}`Jubilant <index>` for integration tests.

If you need help, don't hesitate to get in touch at [Charm Development](https://matrix.to/#/#charmhub-charmdev:ubuntu.com) on Matrix.

```{tip}
As you work through the tutorial, you'll write your charm piece by piece. You can [inspect the full code in GitHub](https://github.com/canonical/operator/tree/main/examples/machine-tinyproxy) at any time.
```

## Study your application

You'll write a charm that uses [tinyproxy](https://tinyproxy.github.io/) to run a reverse proxy. When your charm is deployed and tinyproxy is running, you'll be able to fetch [example.com](http://example.com) by running:

```text
curl <address>:8000/example/
```

Where `<address>` is the IP address of the machine that tinyproxy is running on. You'll be able to use the `juju config` command to change `/example/` to a custom path.

This application isn't especially realistic in isolation. But it's a good way to illustrate typical interactions between Juju, a charm, a machine, and a workload.

(machine-charm-tutorial-environment)=
## Set up your environment

### Create a virtual machine

You'll deploy and test your charm inside an Ubuntu virtual machine that's running on your computer. Your virtual machine will provide an isolated environment that's safe for you to experiment in, without affecting your host machine. This is especially helpful for the charm's integration tests, which require a local Juju controller and LXD cloud.

First, install Multipass for managing virtual machines. See the [installation instructions](https://canonical.com/multipass/install).

Next, open a terminal, then run:

```text
multipass launch --cpus 4 --memory 8G --disk 50G --name juju-sandbox
```

This creates a virtual machine called `juju-sandbox`.

Multipass allocates some of your computer's memory and disk space to your virtual machine. The options we've chosen for `multipass launch` ensure that your virtual machine will be powerful enough to run Juju and deploy medium-sized charms.

This step should take less than 10 minutes, but the time depends on your computer and network. When your virtual machine has been created, you'll see the message:

```text
Launched: juju-sandbox
```

Now run:

```text
multipass shell juju-sandbox
```

This switches the terminal so that you're working inside your virtual machine.

You'll see a message with information about your virtual machine. You'll also see a new prompt:

```text
ubuntu@juju-sandbox:~$
```

### Install Juju and charm development tools

Now that you have a virtual machine, you need to install the following tools on your virtual machine:

- **Charmcraft, Juju, and LXD** - You'll use {external+charmcraft:doc}`Charmcraft <index>` to create the initial version of your charm and prepare your charm for deployment. When you deploy your charm, Juju will use LXD to manage the machine where your charm runs.
- **uv** - Your charm will be a Python project. You'll use [uv](https://docs.astral.sh/uv/) to manage your charm's runtime and development dependencies.
- **tox** - You'll use [tox](https://tox.wiki/en/) to run your charm's checks and tests.

Instead of manually installing and configuring each tool, we recommend using [Concierge](https://github.com/canonical/concierge), Canonical's tool for setting up charm development environments.

In your virtual machine, run:

```text
sudo snap install --classic concierge
sudo concierge prepare -p machine --extra-snaps astral-uv
```

This first installs Concierge, then uses Concierge to install and configure the other tools (except tox). The option `-p machine` tells Concierge that we want tools for developing machine charms.

This step should take less than 15 minutes, but the time depends on your computer and network. When the tools have been installed, you'll see a message that ends with:

```text
msg="Bootstrapped Juju" provider=lxd
```

To install tox, run:

```text
uv tool install tox --with tox-uv
```

When tox has been installed, you'll see a confirmation and a warning:

```text
Installed 1 executable: tox
warning: `/home/ubuntu/.local/bin` is not on your PATH. To use installed tools,
run `export PATH="/home/ubuntu/.local/bin:$PATH"` or `uv tool update-shell`.
```

Instead of following the warning, exit your virtual machine:

```text
exit
```

The terminal switches back to your host machine. Your virtual machine is still running.

Next, stop your virtual machine:

```text
multipass stop juju-sandbox
```

Then use the Multipass {external+multipass:ref}`snapshot <reference-command-line-interface-snapshot>` command to take a snapshot of your virtual machine:

```text
multipass snapshot juju-sandbox
```

If you have any problems with your virtual machine during or after completing the tutorial, use the Multipass {external+multipass:ref}`restore <reference-command-line-interface-restore>` command to restore your virtual machine to this point.

### Create a project directory

Although you'll deploy and test your charm inside your virtual machine, you'll probably find it more convenient to write your charm using your usual text editor or IDE.

Outside your virtual machine, create a project directory:

```text
mkdir ~/tinyproxy-tutorial
```

You'll write your charm in this directory.

Next, use the Multipass {external+multipass:ref}`mount <reference-command-line-interface-mount>` command to make the directory available inside your virtual machine:

```text
multipass mount --type native ~/tinyproxy-tutorial juju-sandbox:~/tinyproxy
```

Finally, start your virtual machine and switch to your virtual machine:

```text
multipass shell juju-sandbox
```

## Create a charm project

In your virtual machine, go into your project directory and create the initial version of your charm:

```text
cd ~/tinyproxy
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

Open `~/tinyproxy-tutorial/charmcraft.yaml` in your usual text editor or IDE, then change the values of `title`, `summary`, and `description` to:

```yaml
title: Reverse Proxy Demo
summary: A demo charm that configures tinyproxy as a reverse proxy.
description: |
  This charm demonstrates how to write a machine charm with Ops.
```

### Write a helper module

Your charm will interact with tinyproxy, so it's a good idea to write a helper module that wraps tinyproxy.
Charmcraft created `src/tinyproxy.py` as a placeholder helper module.

The helper module will be independent of the main logic of your charm. This will make it easier to test your charm. However, the helper module won't be a general-purpose wrapper for tinyproxy. The helper module will contain opinionated functions for managing tinyproxy on Ubuntu.

The helper module will depend on some libraries that are useful when writing charms.

To add the libraries to your charm's dependencies, run:

```text
uv add charmlibs-apt charmlibs-pathops
```

This adds the following Python packages to the `dependencies` list in `pyproject.toml`:

- {external+charmlibs:ref}`charmlibs-apt <charmlibs-apt>` - A library for using APT to manage system packages. This is how your charm will install tinyproxy.
- {external+charmlibs:ref}`charmlibs-pathops <charmlibs-pathops>` - A file operations library, similar to `pathlib` from the standard library.

Next, replace the contents of `src/tinyproxy.py` with:

```python
"""Functions for interacting with tinyproxy."""

import logging
import os
import shutil
import signal
import subprocess

from charmlibs import apt, pathops

logger = logging.getLogger(__name__)

CONFIG_FILE = pathops.LocalPath("/etc/tinyproxy/tinyproxy.conf")
PID_FILE = pathops.LocalPath("/var/run/tinyproxy.pid")


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
    # Install a specific package from ubuntu@22.04
    # See https://packages.ubuntu.com/jammy/tinyproxy-bin
    # In general, it's good practice for charms to pin workload versions.
    apt.add_package("tinyproxy-bin", "1.11.0-1")
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
    """Start tinyproxy."""
    subprocess.run(["tinyproxy"], check=True, capture_output=True, text=True)


def stop() -> None:
    """Stop tinyproxy."""
    pid = _get_pid()
    if pid:
        os.kill(pid, signal.SIGTERM)


def uninstall() -> None:
    """Uninstall the tinyproxy executable and remove files."""
    apt.remove_package("tinyproxy-bin")
    PID_FILE.unlink(missing_ok=True)
    CONFIG_FILE.unlink(missing_ok=True)
    CONFIG_FILE.parent.rmdir()


def _get_pid() -> int | None:
    """Return the PID of the tinyproxy process, or None if the process can't be found."""
    if not PID_FILE.exists():
        return None
    pid = int(PID_FILE.read_text())
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
After adding code to your charm, run `tox -e format` to format the code. Then run `tox -e lint` to check the code against coding style standards and run static checks. You can run these commands from anywhere in the `~/tinyproxy` directory in your virtual machine.

You can also run these commands in `~/tinyproxy-tutorial` if uv and tox are available on your host machine. However, be careful when running the same tox command inside and outside your virtual machine. If tox fails with an error related to the `.tox` directory, use `-re` instead of `-e` in the commands. This recreates the tox environment.
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

When your charm receives the "install" event from Juju, Ops runs this method and tells Juju the version of tinyproxy that's installed on the machine. Juju shows the version in its status output.

As you write your charm, keep in mind that the charm code only runs when there's an event to handle.

```{important}
Juju executes `charm.py` on every event, with event data in the environment. Your call to `ops.main` creates a fresh instance of the charm class, then Ops runs the appropriate method on the charm class. You can't persist data between Juju events by storing it in memory.
```

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
        # Raising a runtime error will put the charm into error status.
        # The Juju logs will show the error message, to help you debug the error.
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
            (slug_error,) = e.errors()  # 'slug' is the first and only option validated.
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

That's all the charm code! If you'd like, you can [inspect the full code in GitHub](https://github.com/canonical/operator/tree/main/examples/machine-tinyproxy).

## Try your charm

### Pack your charm

Before you can try your charm, you need to "pack" it. Packing combines the charm code and metadata into a single file that can be deployed to Juju.

In your virtual machine, make sure that the working directory is `~/tinyproxy`. Then run:

```text
charmcraft pack
```

Charmcraft will take up to 20 minutes to pack your charm, depending on your computer and network. If you modify the charm code after completing the tutorial, packing will be faster the second time because Charmcraft has cached the packing environment.

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
    testing  concierge-lxd  localhost/localhost  3.6.11   unsupported  09:00:00+08:00
    ```

You're now ready to deploy your charm.

In the `~/tinyproxy` directory, run `juju deploy ./<charm-file>`, where `<charm-file`> is the name of the file created by `charmcraft pack`. For example:

```text
juju deploy ./tinyproxy_amd64.charm
```

Juju creates an "application" from your charm. For each unit in the application, Juju starts a LXD virtual machine and installs your charm on the machine. We didn't tell Juju how many units we want, so Juju assumes one unit and starts one machine. After Juju has installed your charm on the machine, Juju starts sending events to your charm so that your charm can install and start tinyproxy.

When your charm has started tinyproxy, the application will go into "active" status:

```text
Model    Controller     Cloud/Region         Version  SLA          Timestamp
testing  concierge-lxd  localhost/localhost  3.6.11   unsupported  09:01:38+08:00

App        Version  Status  Scale  Charm      Channel  Rev  Exposed  Message
tinyproxy  1.11.0   active      1  tinyproxy             0  no

Unit          Workload  Agent  Machine  Public address  Ports  Message
tinyproxy/0*  active    idle   0        10.71.67.208

Machine  State    Address       Inst id        Base          AZ            Message
0        started  10.71.67.208  juju-8e7bd9-0  ubuntu@22.04  juju-sandbox  Running
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

## Write unit tests

### Write tests for the helper module

When writing a charm, it's good practice to write unit tests for the charm code that interacts with the workload (tinyproxy). Typically, you'd mock external calls, such as file operations. To illustrate the approach, we'll write a test for the `get_version` function in the helper module.

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
    version_process = MockVersionProcess("1.0.0")
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: version_process)
    assert tinyproxy.get_version() == "1.0.0"
```

We'll run all the tests later in the tutorial. But if you'd like to see whether this test passes, run:

```text
tox -e unit -- tests/unit/test_tinyproxy.py
```

### Write state-transition tests

We should write unit tests for the charm code that handles events. Each test will be structured as a "state-transition" test, using the testing framework that comes with Ops.

State-transition tests are isolated tests of event handlers. They don't require Juju to be available. Instead, they test how your charm responds to simulated events from Juju.

It's helpful to think of each test this way:

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
        return "1.0.0"

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


def test_install(monkeypatch: pytest.MonkeyPatch):
    """Test that the charm correctly handles the install event."""
    # A state-transition test has three broad steps:
    # Step 1. Arrange the input state.
    tinyproxy = MockTinyproxy()
    monkeypatch.setattr("charm.tinyproxy", tinyproxy)
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
    monkeypatch.setattr("charm.tinyproxy", tinyproxy)
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
    monkeypatch.setattr("charm.tinyproxy", tinyproxy)
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


@pytest.mark.parametrize("invalid_slug", ["", "foo_bar", "foo/bar"])
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


@pytest.mark.parametrize("invalid_slug", ["", "foo_bar", "foo/bar"])
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
src/charm.py          71      5     20      7    87%   71->exit, 101, 106->exit, 115-116, 125-126
src/tinyproxy.py      47     26      6      0    40%   34-41, 52-56, 63, 68, 73-78, 83, 88-90, 95-98, 103-111
--------------------------------------------------------------
TOTAL                118     31     26      7    69%
  unit: OK (1.21=setup[0.05]+cmd[1.03,0.13] seconds)
  congratulations :) (1.30 seconds)
```

## Write integration tests

Integration tests are an important way to check that your charm works correctly when deployed. In contrast to unit tests, integration tests require Juju to be available, and events aren't simulated.

When you created the initial version of your charm, Charmcraft included integration tests. The tests use {external+jubilant:doc}`Jubilant <index>` to interact with Juju. We'll expand the tests to cover more of your charm's functionality.

In `tests/integration/test_charm.py`, change `juju.wait(jubilant.all_active)` to:

```python
    juju.wait(jubilant.all_active, timeout=600)
```

This extends the duration that Jubilant waits for your charm to deploy, in case the integration tests run slowly in your virtual machine. The default duration would be sufficient if the integration tests were running in a continuous integration environment.

Next, remove the `@pytest.mark.skip` decorator from `test_workload_version_is_set`. Then change `assert version == ...` to:

```python
    assert version == "1.11.0"  # The version installed by tinyproxy.install.
```

You should now have the following tests:

- `test_deploy` - Deploys your charm and checks that it goes into active status.
- `test_workload_version_is_set` - Checks that your charm reports the correct version of tinyproxy to Juju.

Before running the tests, let's add a test to check that an invalid value of `slug` blocks the charm.

Add the following function at the end of `tests/integration/test_charm.py`:

```python
def test_block_on_invalid_config(charm: pathlib.Path, juju: jubilant.Juju):
    """Check that the charm goes into blocked status if slug is invalid."""
    juju.config("tinyproxy", {"slug": "foo/bar"})
    juju.wait(jubilant.all_blocked)
    juju.config("tinyproxy", reset="slug")
```

Each test depends on two fixtures, which are defined in `tests/integration/conftest.py`:

- `charm` - The `.charm` file to deploy. Only `test_deploy` uses `charm`, but it's helpful for each test to depend on `charm`. This ensures that each test fails immediately if a `.charm` file isn't available.
- `juju` - A Jubilant object for interacting with a temporary Juju model.

The `juju` fixture is module-scoped. In other words, each test in `test_charm.py` affects the state of the same Juju model. This means that the order of the tests is significant. This also explains why we reset `slug` at the end of `test_block_on_invalid_config` - to ensure that any subsequent test could assume an unblocked charm.

If you wanted isolated tests, you could change `juju` to be function-scoped (pytest's default scope) and deploy the `.charm` file at the beginning of each test. However, this would slow down the tests.

Now run the tests:

```text
tox -e integration
```

It will take a few minutes to run the tests. The output should be similar to:

```text
...

======================= 3 passed in 277.23s (0:04:37) =======================
  integration: OK (277.76=setup[0.06]+cmd[277.70] seconds)
  congratulations :) (277.89 seconds)
```

```{tip}
`tox -e integration` doesn't pack your charm. If you modify the charm code and want to run the integration tests again, run `charmcraft pack` before `tox -e integration`.
```

## Tear things down

Congratulations on reaching the end of the tutorial!

You can keep things running, to explore further, or you can remove what you created:

- To remove your charm from Juju, run `juju remove-application tinyproxy`. You don't need to do this if you plan to remove your virtual machine.
- If you're still watching Juju status, press <kbd>Ctrl</kbd> + <kbd>C</kbd> to stop watching.
- To exit your virtual machine, run `exit`. The terminal switches back to your host machine.
- To stop your virtual machine, run `multipass stop juju-sandbox`.
- To remove your virtual machine, run `multipass delete juju-sandbox`.
- To uninstall Multipass, see {external+multipass:ref}`how-to-guides-install-multipass` > Uninstall.

## Next steps

If you'd like, you can [inspect the full code in GitHub](https://github.com/canonical/operator/tree/main/examples/machine-tinyproxy).

For more information about topics covered in the tutorial, see:

- [](#write-and-structure-charm-code)
- [](#manage-configuration)
- [](#testing)

You might also want to inspect a real machine charm: [ubuntu-manpages-operator](https://github.com/canonical/ubuntu-manpages-operator)
