(write-and-structure-charm-code)=
# How to write and structure charm code

(create-a-repository-and-initialise-it)=
## Create a repository and initialise it

Create a repository with your source control of choice. Commit the code you have
added and changed after every significant change, so that you have a record of
your work and can revert to an earlier version if required.

```{admonition} Best practice
:class: hint

Name the repository using the pattern ``<charm name>-operator`` for a single
charm, or ``<base charm name>-operators`` when the repository will hold
multiple related charms. For the charm name, see
{external+charmcraft:ref}`Charmcraft | Specify a name <specify-a-name>`.
```

In your new repository, run `charmcraft init` to generate the recommended
structure for building a charm.

```{note}
In most cases, you'll want to use `--profile=machine` or `--profile=kubernetes`.
If you are charming an application built with a popular framework, check if
charmcraft has a {external+charmcraft:ref}`specific profile <tutorial>` for it.
```

If your repository will hold multiple charms, or a charm and source for other
artifacts, such as a Rock, create a `charms` folder at the top level, then a folder
for each charm inside of that one, and run `charmcraft init` in each charm
folder. You'll end up with a structure similar to:

```
my-charm-set-operators/
├── charms
│   ├── my-charm-core
│   │   ├── charmcraft.yaml
│   │   ├── pyproject.toml
│   │   ├── README.md
│   │   ├── src
│   │   │   ├── charm.py
│   │   │   └── core.py
│   │   ├── tests
|   |   |   └── ...
│   │   ├── tox.ini
│   │   └── uv.lock
│   ├── my-charm-dashboard
|   |   └── ...
│   └── my-charm-helper
|   |   └── ...
├── CONTRIBUTING.md
├── LICENSE
├── README.md
└── rock
    └── ...
```

(define-the-required-dependencies)=
## Define the required dependencies

### Use the Python provided by the base

Charms run using the Python version provided by the base Ubuntu version. Write
charm code that will run with the Python version of the oldest base you support.

> See also: {external+juju:ref}`Juju | Roadmap and releases <releasenotes>`

```{admonition} Best practice
:class: hint

Set the [`requires-python`](https://packaging.python.org/en/latest/specifications/pyproject-toml/#requires-python)
version in your `pyproject.toml` so that tooling will detect any use of Python
features not available in the versions you support.
```

### Add Python dependencies to pyproject.toml and update the lock file

Specify all the direct dependencies of your charm in your `pyproject.toml`
file in the top-level charm folder. For example:

```toml
# All dependencies required to run the charm
dependencies = [
    "ops>=3,<4",
]

[dependency-groups]
# Dependencies of linting and static type checks
lint = [
    "ruff",
    "codespell",
    "pyright",
]
# Dependencies of unit tests
unit = [
    "coverage[toml]",
    "ops[testing]",
    "pytest",
]
# Dependencies of integration tests
integration = [
    "jubilant",
    "pytest",
]
# Additional groups
docs = [
    "Sphinx",
]
```

```{tip}
Including an external dependency is a significant choice. It can help with
reducing the complexity and development cost. However, it also increases the
complexity of understanding the entire system, and adds a maintenance burden of
keeping track of upstream versions, particularly around security issues. See [Our Software Dependency Problem](https://research.swtch.com/deps).
```

If you initialised your charm using the `machine` or `kubernetes` profile of `charmcraft init`, your charm uses Charmcraft's {external+charmcraft:ref}`uv plugin <craft_parts_uv_plugin>` and has a lock file called `uv.lock`. After specifying dependencies in `pyproject.toml`, run `uv lock` to update `uv.lock`.

We recommend that you use `uv add` and `uv remove` instead of editing dependencies in `pyproject.toml`. These commands automatically update `pyproject.toml` and `uv.lock`. For more information, see [Managing dependencies](https://docs.astral.sh/uv/concepts/projects/dependencies/) in the uv documentation.

```{admonition} Best practice
:class: hint

Ensure that tooling is configured to automatically detect new versions,
particularly security releases, for all your dependencies.
```

```{admonition} Best practice
:class: hint

Ensure that the `pyproject.toml` *and* the lock file are committed to version
control, so that exact versions of charms can be reproduced.
```

```{admonition} Best practice
:class: hint

Avoid using Charmcraft's `charm` plugin if possible. Instead, {external+charmcraft:ref}`migrate to the uv plugin <howto-migrate-to-uv>` or the {external+charmcraft:ref}`poetry plugin <howto-migrate-to-poetry>`.
```

(design-your-python-modules)=
## Design your Python modules

In your `src/charm.py` file, define a class for managing how the charm interacts with Juju.

You'll have a single class that inherits from [](ops.CharmBase).
Arrange the methods of this class in the following order:

1. An `__init__` method that observes all relevant events and instantiates any objects that
   the charm needs.
   For example, in a Kubernetes charm:
   ```python
   def __init__(self, framework: ops.Framework):
       super().__init__(framework)
       framework.observe(self.on["workload_container"].pebble_ready, self._on_pebble_ready)
       self.container = self.unit.get_container("workload-container")
   ```
2. Event handlers, in the order that they're observed in `__init__`.
   Make the event handlers private.
   For example, `def _on_pebble_ready(...)` instead of `def on_pebble_ready(...)`.
3. Other helper methods, which may be private or public.

```{tip}

If an event handler needs to pass event data to a helper method, extract the relevant data
from the event object and pass that data to the helper method. Don't pass the event object itself.
This approach will make it easier to write unit tests for the charm.
```

For each workload that the charm manages, create a file called `src/<workload>.py` that contains
functions for interacting with the workload. If there's an existing Python library for managing a
workload, use the existing library instead of creating your own file.

### Example

Suppose that you're writing a machine charm to manage a workload called Demo Server.
Your charm code is in `src/charm.py`:

```python
#!/usr/bin/env python3
# Copyright 2025 User
# See LICENSE file for licensing details.

"""A machine charm that manages the server."""

import logging

import ops

import demo_server  # Provided by src/demo_server.py

logger = logging.getLogger(__name__)


class DemoServerCharm(ops.CharmBase):
    """Manage the server."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on.install, self._on_install)
        framework.observe(self.on.start, self._on_start)

    def _on_install(self, event: ops.InstallEvent):
        """Install the server."""
        demo_server.install()

    def _on_start(self, event: ops.StartEvent):
        """Handle start event."""
        self.unit.status = ops.MaintenanceStatus("starting server")
        demo_server.start()
        version = demo_server.get_version()
        self.unit.set_workload_version(version)
        self.unit.status = ops.ActiveStatus()

    # Put helper methods here.
    # If a method doesn't depend on Ops, put it in src/demo_server.py instead.


if __name__ == "__main__":  # pragma: nocover
    ops.main(DemoServerCharm)
```

Workload-specific logic is in `src/demo_server.py`:

```python
# Copyright 2025 User
# See LICENSE file for licensing details.

"""Functions for managing and interacting with the server."""

import logging
import subprocess

import requests

logger = logging.getLogger(__name__)


def install() -> None:
    """Install the server from a snap."""
    subprocess.run(["snap", "install", "demo-server"], capture_output=True, check=True)


def start() -> None:
    """Start the server."""
    subprocess.run(["demo-server", "start"], capture_output=True, check=True)


def get_version() -> str:
    """Get the running version of the server."""
    response = requests.get("http://localhost:5000/version", timeout=5)
    return response.text
```

(handle-status)=
## Handle status

> See first: {external+juju:ref}`Juju | Status <status>`

### Unit status

Your charm should report the status of each unit to Juju.

To report the unit status, observe the `collect_unit_status` event. This event is triggered by Ops at the end of each hook and provides a callback method for reporting the unit status. For example:

```python
class DemoServerCharm(ops.CharmBase):
    """Manage the server."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on.collect_unit_status, self._on_collect_status)
        # Observe other events...

    def _on_collect_status(self, event: ops.CollectStatusEvent):
        if "port" not in self.config:
            event.add_status(ops.BlockedStatus("no port specified"))
            return
        event.add_status(ops.ActiveStatus())
```

In your handler for `collect_unit_status`, you can call `add_status()` multiple times. Ops will send the highest priority status to Juju. This reduces the amount of logic you need to write to decide which status to report. For more information, see [`CollectStatusEvent`](ops.CollectStatusEvent).

Your handler for `collect_unit_status` won't have access to data about the main Juju event (hook) being handled.

To report the unit status while handling an event, set [`self.unit.status`](ops.Unit.status). When your charm code sets `self.unit.status`, Ops immediately sends the unit status to Juju. For example:

```python
    def _on_start(self, event: ops.StartEvent):
        """Handle start event."""
        self.unit.status = ops.MaintenanceStatus("starting server")
        demo_server.start()
        # At the end of the handler, Ops triggers collect_unit_status.
```

### Application status

If you expect to have more than one unit, you should also report the application status to Juju.

To report the application status, observe the `collect_app_status` event. This event is triggered by Ops at the end of each hook, for the leader unit only. For example:

```python
class DemoServerCharm(ops.CharmBase):
    """Manage the server."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on.collect_app_status, self._on_collect_app_status)
        framework.observe(self.on.collect_unit_status, self._on_collect_unit_status)
        # Observe other events...

    def _on_collect_app_status(self, event: ops.CollectStatusEvent):
        # This is triggered for the leader unit only.
        num_degraded = ...  # Inspect peer unit databags to find degraded units.
        if num_degraded:
            event.add_status(ops.ActiveStatus(f"degraded units: {num_degraded}"))
            return
        event.add_status(ops.ActiveStatus())

    def _on_collect_unit_status(self, event: ops.CollectStatusEvent):
        # This is triggered for each unit.
        if self.is_degraded():  # Use a custom helper method to determine status.
            event.add_status(ops.ActiveStatus("degraded"))
            return
        event.add_status(ops.ActiveStatus())
```

As with `collect_unit_status`, you can call `add_status()` multiple times and Ops will send the highest priority status to Juju.

If you need to report the application status while handling an event, you can use [`self.app.status`](ops.Application.status). However, your charm code will first need to use [`self.unit.is_leader()`](ops.Unit.is_leader) to check that it's running as the leader unit.

(handle-errors)=
## Handle errors

Throughout your charm code, try to anticipate and handle errors rather than
letting the charm crash and go into an error state.

* **Automatically recoverable error**: the charm should go into `maintenance`
  status until the error is resolved and then back to `active` status. Examples
  of automatically recoverable errors are those where the operation that
  resulted in the error can be retried. Retry a small number of times, with
  short delays between attempts, rather than having the charm error out and
  relying on Juju or the user for the retry. If the error is not resolved
  after retrying, then use one of the following techniques.
* **Operator recoverable error**: the charm should go into the `blocked` state
  until the user resolves the error. An example is that a configuration
  option is invalid.
* **Unexpected/unrecoverable error**: the charm should enter the error state. Do
  this by raising an appropriate exception in the charm code. Note that the unit
  status will only show an `error` status, and the user will need to use
  the Juju log to get details of the problem. Ensure that the logging and
  exception raised makes it clear what is happening, and -- when possible -- how
  the user can solve it. The user may need to file a bug and potentially
  downgrade to a previous version of the charm.

```{tip}
By default, Juju will retry hooks that fail, but users can disable this
behaviour, so charms should not rely on it.
```

(follow-best-practices)=
## Follow best practices

Notes on best practices for charm development and maintenance can be found across the charming ecosystem documentation. While we usually encourage you to read them in their original context, we collect them here as well, for your convenience.

```{include} ../reuse/best-practices.txt
```

(validate-your-charm-with-every-change)=
## Validate your charm with every change

Configure your continuous integration tooling so that whenever changes are
proposed for or accepted into your main branch the `lint`, `unit`, and
`integration` commands are run, and will block merging when failing.

```{admonition} Best practice
:class: hint

The quality assurance pipeline of a charm should be automated using a
continuous integration (CI) system.
```

If you are using GitHub, create a file called `.github/workflows/ci.yaml`. For
example, to include a `lint` job that runs the `tox` `lint` environment:

```yaml
name: Tests
on:
  workflow_call:
  workflow_dispatch:

jobs:
  lint:
    name: Lint
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v6
      - name: Set up uv
        uses: astral-sh/setup-uv@7
      - name: Set up tox and tox-uv
        run: uv tool install tox --with tox-uv
      - name: Run linters
        run: tox -e lint
```

Other `tox` environments can be run similarly; for example unit tests:

```yaml
  unit-test:
    name: Unit tests
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v6
      - name: Set up uv
        uses: astral-sh/setup-uv@7
      - name: Set up tox and tox-uv
        run: uv tool install tox --with tox-uv
      - name: Run tests
        run: tox -e unit
```

Integration tests are a bit more complex, because in order to run those tests, a Juju controller and
a cloud in which to deploy it, is required. This example uses [Concierge](https://github.com/canonical/concierge) to set up
`k8s` and Juju:

```
  integration-test-k8s:
    name: Integration tests (k8s)
    needs:
      - lint
      - unit-test
    runs-on: ubuntu-latest
    steps:
      - name: Install concierge
        run: sudo snap install --classic concierge
      - name: Install Juju and tools
        run: sudo concierge prepare -p k8s
      - name: Checkout
        uses: actions/checkout@v6
      - name: Set up uv
        uses: astral-sh/setup-uv@7
      - name: Set up tox and tox-uv
        run: uv tool install tox --with tox-uv
      - name: Run integration tests
        # Set a predictable model name so it can be consumed by charm-logdump-action
        run: tox -e integration -- --model testing
      - name: Dump logs
        uses: canonical/charm-logdump-action@main
        if: failure()
        with:
          app: my-app-name
          model: testing
```

```{tip}

The [charming-actions](https://github.com/canonical/charming-actions)
repository includes actions to ensure that libraries are up-to-date, publish
charms and libraries, and more.
```
