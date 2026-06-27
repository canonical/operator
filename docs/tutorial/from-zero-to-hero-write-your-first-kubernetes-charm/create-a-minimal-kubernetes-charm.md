(create-a-minimal-kubernetes-charm)=
# Create a minimal Kubernetes charm

> <small> {ref}`From Zero to Hero: Write your first Kubernetes charm <from-zero-to-hero-write-your-first-kubernetes-charm>` > Create a minimal Kubernetes charm</small>
>
> **See previous: {ref}`Set up your development environment <set-up-your-development-environment>`**

When you deploy a Kubernetes charm, the following things happen:

1. The Juju controller provisions a pod with at least two containers, one for the Juju unit agent and the charm itself and one container for each application workload container that is specified in the `containers` field of a file in the charm that is called `charmcraft.yaml`.
1. The same Juju controller injects Pebble -- a lightweight, API-driven process supervisor -- into each workload container and overrides the container entrypoint so that Pebble starts when the container is ready.
1. When the Kubernetes API reports that a workload container is ready, the Juju controller informs the charm that the instance of Pebble in that container is ready. At that point, the charm knows that it can start communicating with Pebble.
1. Typically, at this point the charm will make calls to Pebble so that Pebble can configure and start the workload and begin operations.
1. During operations, the charm may need to directly communicate with the workload application. The charm container and workload container can communicate via `localhost` because they share the same pod, and containers in the same pod share the same network namespace.

> Note: In the past, the containers were specified in a `metadata.yaml` file, but the modern practice is that all charm specification is in a single `charmcraft.yaml` file.

All subsequent workload management happens in the same way -- the Juju controller sends events to the charm and the charm responds to these events by managing the workload application in various ways via Pebble. The picture below illustrates all of this for a simple case where there is just one workload container.


![Create a minimal Kubernetes charm](../../resources/create_a_minimal_kubernetes_charm.png)


As a charm developer, your first job is to use this knowledge to create the basic structure and content for your charm:

- descriptive files (e.g., YAML configuration files like the `charmcraft.yaml` file mentioned above) that give Juju, Python, or Charmcraft various bits of information about your charm, and
- executable files (like the `src/charm.py` file that we will see shortly) where you will use Ops-enriched Python to write all the logic of your charm.

## Create a charm project

In your virtual machine, go into your project directory and create the initial version of your charm:

```text
cd ~/fastapi-demo
uvx git+https://github.com/canonical/charmcraft@74d12bc init --profile kubernetes
```

<!--
  When charmcraft stable is up-to-date, remove this info and switch to 'charmcraft init --profile kubernetes' above.
-->
The `uvx ...` command runs Charmcraft directly from GitHub. We recommend doing this because the installed version of Charmcraft may come with an older version of the profile used in the tutorial. You should use the installed version of Charmcraft for everything else (as we'll do later in the tutorial).


Charmcraft created several files, including:

- `charmcraft.yaml` - Metadata about your charm. Used by Juju and Charmcraft.
- `pyproject.toml` - Python project configuration. Lists the dependencies of your charm.
- `src/charm.py` - The Python file that will contain the logic of your charm.
- `src/fastapi_demo.py` - A helper module that will contain functions for interacting with your workload application.

These files currently contain placeholder code and configuration.

## Write your charm

### Edit the metadata

Open `~/k8s-tutorial/charmcraft.yaml` in your usual text editor or IDE, then change the values of `title`, `summary`, and `description` to:

```yaml
title: Web Server Demo
summary: A demo charm that operates a small Python FastAPI server.
description: |
  This charm demonstrates how to write a Kubernetes charm with Ops.
```

Next, describe the workload container and its OCI image.

In `charmcraft.yaml`, replace the `containers` and `resources` blocks with:

```yaml
containers:
  demo-server:
    resource: demo-server-image

resources:
  # An OCI image resource for the container listed above.
  demo-server-image:
    type: oci-image
    description: OCI image from GitHub Container Repository
    # The upstream-source field is ignored by Charmcraft and Juju, but it can be
    # useful to developers in identifying the source of the OCI image.  It is also
    # used by the 'canonical/charming-actions' GitHub action for automated releases.
    # The test_deploy function in tests/integration/test_charm.py reads upstream-source
    # to determine which OCI image to use when running the charm's integration tests.
    upstream-source: ghcr.io/canonical/api_demo_server:1.0.4
```

### Write a helper module

Your charm will interact with our workload application. It's a good idea to write a helper module that wraps the workload application. Charmcraft created `src/fastapi_demo.py` as a placeholder helper module.

The helper module will be independent of the main logic of your charm. This will make it easier to test your charm. In this tutorial, the helper module only contains the logic to get the version of the workload application. The server has an endpoint at `/version` that returns a JSON payload containing the version number. This is called the workload version.

To make things easier for Juju users, your charm should expose the workload version to Juju. It will be visible in Juju's status output. For more information, see {ref}`how-to-set-the-workload-version`.

Replace the content of `src/fastapi_demo.py` with:

```python
import json
import logging
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)


def get_version(port: int) -> str:
    """Get the version of fastapi_demo that is running.

    Args:
        port: The port where fastapi_demo web server is listening.

    Raises:
        RuntimeError: If the server can't be reached, for example because of an invalid port.
    """
    try:
        response = urllib.request.urlopen(f"http://0.0.0.0:{port}/version")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Could not connect to the workload server on port {port}") from e
    data = json.loads(response.read())
    return data["version"]
```

Notice that the helper module is stateless. In fact, your charm as a whole will be stateless. The main logic of your charm will:

1. Receive an event from Juju.
2. Use Pebble calls and the helper module to manage the workload application and check its status.
3. Report the status back to Juju.

```{tip}
After adding code to your charm, run `tox -e format` to format the code. Then run `tox -e lint` to check the code against coding style standards and run static checks. You can run these commands from anywhere in the `~/fastapi-demo` directory in your virtual machine.

You can also run these commands in `~/k8s-tutorial` if uv and tox are available on your host machine. However, be careful when running the same tox command inside and outside your virtual machine. If tox fails with an error related to the `.tox` directory, use `-re` instead of `-e` in the commands. This recreates the tox environment.
```

### Define the charm class

We'll now write the charm code that handles events from Juju. Charmcraft created `src/charm.py` as the location for this logic.

Replace the contents of `src/charm.py` with:

```python
#!/usr/bin/env python3

"""Kubernetes charm for a demo app."""

import ops

import fastapi_demo


class FastAPIDemoCharm(ops.CharmBase):
    """Charm the service."""

    def __init__(self, framework: ops.Framework) -> None:
        super().__init__(framework)


if __name__ == "__main__":  # pragma: nocover
    ops.main(FastAPIDemoCharm)
```

As you can see, a charm is a pure Python class that inherits from the [`CharmBase`](ops.CharmBase) class of Ops and which we pass to [](ops.main). We'll refer to `FastAPIDemoCharm` as the "charm class".

### Handle the pebble-ready event

In the `__init__` function of your charm class, we'll tell Ops which method of your charm class to run for each event. Let's start with when the Juju controller tells us that the workload container's Pebble is up and running.

```python
framework.observe(self.on["demo-server"].pebble_ready, self._on_demo_server_pebble_ready)
```


```{important}

**Generally speaking:** A charm class is a collection of event handling methods. When you want to install, remove, upgrade, configure, etc., an application, Juju sends information to your charm. Ops translates this information into events and your job is to write event handlers

```

```{tip}

**Pro tip:** Use `__init__` to hold references (pointers) to other `Object`s or immutable state only. That is because a charm is reinitialised on every event. You can't persist data between Juju events by storing it in memory.

```

Next, define the event handler, as follows:

We'll use the `ActiveStatus` class to set the charm status to active. Note that almost everything you need to define your charm is in the `ops` package that you imported earlier - there's no need to add additional imports.

Use `ActiveStatus` as well as further Ops constructs to define the event handler, as below. As you can see, what is happening is that, from the `event` argument, you extract the workload container object in which you add a custom layer. Once the layer is set you replan your service and set the charm status to active.


```python
def _on_demo_server_pebble_ready(self, event: ops.PebbleReadyEvent) -> None:
    """Define and start a workload using the Pebble API."""
    # Get a reference the container attribute on the PebbleReadyEvent
    container = event.workload
    # Add initial Pebble config layer using the Pebble API
    container.add_layer("fastapi_demo", self._get_pebble_layer(), combine=True)
    # Make Pebble reevaluate its plan, ensuring any services are started if enabled.
    container.replan()
    # Learn more about statuses at
    # https://documentation.ubuntu.com/juju/3.6/reference/status/
    self.unit.status = ops.ActiveStatus()
```

The custom Pebble layer that you just added is defined in the  `self._get_pebble_layer()` method. We'll now add this method.

In the `__init__` method of your charm class, name your service to `fastapi-service` and add it as a class attribute:

```python
self.pebble_service_name = "fastapi-service"
```

Finally, define  the `_get_pebble_layer` function as below. The `command` variable represents a command line that should be executed in order to start our application.

```python
def _get_pebble_layer(self) -> ops.pebble.Layer:
    """Pebble layer for the FastAPI demo services."""
    command = " ".join(
        [
            "uvicorn",
            "api_demo_server.app:app",
            "--host=0.0.0.0",
            "--port=8000",
        ]
    )
    pebble_layer: ops.pebble.LayerDict = {
        "summary": "FastAPI demo service",
        "description": "pebble config layer for FastAPI demo server",
        "services": {
            self.pebble_service_name: {
                "override": "replace",
                "summary": "fastapi demo",
                "command": command,
                "startup": "enabled",
            }
        },
    }
    return ops.pebble.Layer(pebble_layer)
```

### Set the workload version

The workload version is available after the workload starts, which happens after Pebble reevaluates its plan. We'll use the `src/fastapi_demo.py` helper module for this step.

In `src/charm.py`, append the following lines to the `_on_demo_server_pebble_ready` function:

```python
# Set the workload version of this charm.
version = fastapi_demo.get_version(port=8000)
self.unit.set_workload_version(version)
```

We get the workload version over port 8000 because `_get_pebble_layer` deploys the app on this port. Then `self.unit.set_workload_version` exposes the workload version to Juju.

### Add logger functionality

In the imports section of `src/charm.py`, import the Python `logging` module and define a logger object, as below. This will allow you to read log data in `juju`.

```python
import logging

# Log messages can be retrieved using juju debug-log
logger = logging.getLogger(__name__)
```

## Try your charm

### Pack your charm

Now go back to your virtual machine and make sure that you're in the `~/fastapi-demo` directory.

Then run `charmcraft pack` to create a `.charm` file that can be deployed with Juju. In our case, the file was named `fastapi-demo_amd64.charm`. Yours should be named similarly, though the name might vary slightly depending on your architecture.

```
charmcraft pack
# Packed fastapi-demo_amd64.charm
```

The first time you run `charmcraft pack`, Charmcraft takes several minutes to pack your charm. Packing will be faster the next time because Charmcraft has cached the packing environment.

If you run into inexplicable issues when running `charmcraft pack`, this may be because some of the cached information is out of date. Run `charmcraft clean` to fix this.

```{important}

**Did you know?** A `.charm` file is really just a zip file of your charm files and code dependencies that makes it more convenient to share, publish, and retrieve your charm contents.

```

### Deploy your charm

Deploy the `.charm` file, as below. Juju will create a Kubernetes `StatefulSet` named after your application with one replica.

```text
juju deploy ./fastapi-demo_amd64.charm --resource \
     demo-server-image=ghcr.io/canonical/api_demo_server:1.0.4
```


```{important}

**If you've never deployed a local charm (i.e., a charm from a location on your machine) before:** <br> As you may know, when you deploy a charm from Charmhub it is sufficient to run `juju deploy <charm name>`. However, to deploy a local charm you need to explicitly define a `--resource` parameter with the same resource name and resource upstream source as in the `charmcraft.yaml`.

```


Monitor your deployment:

```text
juju status --watch 1s
```

When all units are settled down, you should see the output below, where `10.152.183.215` is the IP of the K8s Service and `10.1.157.73` is the IP of the pod. The workload version is located in the app's `Version` column.

```text
Model    Controller     Cloud/Region  Version  SLA          Timestamp
testing  concierge-k8s  k8s           3.6.13   unsupported  13:38:19+01:00

App           Version  Status  Scale  Charm         Channel  Rev  Address         Exposed  Message
fastapi-demo  1.0.4    active      1  fastapi-demo             0  10.152.183.215  no

Unit             Workload  Agent  Address      Ports  Message
fastapi-demo/0*  active    idle   10.1.157.73
```

### Try the web server

Validate that the app is running and reachable by sending an HTTP request as below, where `10.1.157.73` is the IP of our pod and `8000` is the default application port.

```
curl 10.1.157.73:8000/version
```

You should see a JSON string with the version of the application:

```
{"version":"1.0.4"}
```

Congratulations, you've successfully created a minimal Kubernetes charm!

### Inspect your deployment further

1. Run:

```text
kubectl get namespaces
```

You should see that Juju has created a namespace called `testing`.

2. Try:

```text
kubectl -n testing get pods
```

You should see that your application has been deployed in a pod that has 2 containers running in it, one for the charm and one for the application. The containers talk to each other via the Pebble API using the UNIX socket.

```text
NAME                             READY   STATUS    RESTARTS   AGE
modeloperator-5df6588d89-ghxtz   1/1     Running   0          10m
fastapi-demo-0                   2/2     Running   0          10m
```

3. Check also:

```text
kubectl -n testing describe pod fastapi-demo-0
```

In the output you should see the definition for both containers. You'll be able to verify that the default command and arguments for our application container (`demo-server`) have been displaced by the Pebble service. You should be able to verify the same for the charm container (`charm`).

(write-unit-tests-for-your-charm)=
## Write unit tests for your charm

When you're writing a charm, you will want to ensure that it will behave as intended.

For example, you'll want to check that the various components -- relation data, Pebble services, or configuration files -- all behave as expected in response to an event.

You can ensure all this by writing a rich battery of unit tests. In the context of a charm, we recommended using [`pytest`](https://pytest.org/) ([`unittest`](https://docs.python.org/3/library/unittest.html) can also be used) with [](ops_testing), the framework for state-transition testing in Ops.

We'll also use the Python testing tool [`tox`](https://tox.wiki/en/4.14.2/index.html) to automate our testing and set up our testing environment.

In this section we'll write a test to check that Pebble is configured as expected.

### Write a test

Replace the contents of `tests/unit/test_charm.py` with:

```python
import ops
import pytest
from ops import testing

from charm import FastAPIDemoCharm


def mock_get_version(port: int):
    """Get a mock version string without executing the workload code."""
    return "0.0.1"


@pytest.fixture
def mock_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("fastapi_demo.get_version", mock_get_version)


def test_pebble_layer(mock_version):
    ctx = testing.Context(FastAPIDemoCharm)
    container = testing.Container(name="demo-server", can_connect=True)
    state_in = testing.State(
        containers={container},
        leader=True,
    )
    state_out = ctx.run(ctx.on.pebble_ready(container), state_in)
    # Expected plan after Pebble ready with default config
    expected_plan = {
        "services": {
            "fastapi-service": {
                "override": "replace",
                "summary": "fastapi demo",
                "command": "uvicorn api_demo_server.app:app --host=0.0.0.0 --port=8000",
                "startup": "enabled",
                # Since the environment is empty, Layer.to_dict() will not
                # include it.
            }
        }
    }

    # Check that we have the plan we expected:
    assert state_out.get_container(container.name).plan == expected_plan
    # Check the unit is active:
    assert state_out.unit_status == testing.ActiveStatus()
    # Check the service was started:
    assert (
        state_out.get_container(container.name).service_statuses["fastapi-service"]
        == ops.pebble.ServiceStatus.ACTIVE
    )
    # Check the workload version is set
    assert state_out.workload_version is not None
```

This test checks the behaviour of the `_on_demo_server_pebble_ready` function that you set up earlier. The test simulates your charm receiving the pebble-ready event, then checks that the unit and workload container have the correct state.

In unit tests, we avoid any interaction with the outside world. The `get_version` method performs an HTTP call, which must be patched. We use the `mock_version` fixture to achieve this.

### Run the test

Run the following command from anywhere in the `~/fastapi-demo` directory:

```text
tox -e unit
```

The result should be similar to the following output:

```text
...
============================================ test session starts =============================================
platform linux -- Python 3.12.3, pytest-8.4.1, pluggy-1.6.0 -- /home/ubuntu/fastapi-demo/.tox/unit/bin/python3
cachedir: .tox/unit/.pytest_cache
rootdir: /home/ubuntu/fastapi-demo
configfile: pyproject.toml
collected 1 item

tests/unit/test_charm.py::test_pebble_layer PASSED

============================================= 1 passed in 0.54s ==============================================
unit: commands[1]> coverage report
Name                  Stmts   Miss Branch BrPart  Cover   Missing
-----------------------------------------------------------------
src/charm.py             20      0      0      0   100%
src/fastapi_demo.py       8      3      0      0    62%   35-37
-----------------------------------------------------------------
TOTAL                    28      3      0      0    89%
  unit: OK (1.91=setup[0.09]+cmd[1.54,0.28] seconds)
  congratulations :) (1.93 seconds)
```

Congratulations, you have written your first unit test!


(write-integration-tests-for-your-charm)=
## Write integration tests for your charm

A charm should function correctly not just in a mocked environment, but also in a real deployment.

For example, it should be able to pack, deploy, and integrate without throwing exceptions or getting stuck in a `waiting` or a `blocked` status -- that is, it should correctly reach a status of `active` or `idle`.

You can ensure this by writing integration tests for your charm. In the charming world, these are usually written with {external+jubilant:doc}`Jubilant <reference/jubilant>` and [`pytest-jubilant`](https://github.com/canonical/pytest-jubilant).

In this section we'll write a small integration test to check that the charm packs and deploys correctly.

### Write a test

Let's write the simplest possible integration test, a [smoke test](https://en.wikipedia.org/wiki/Smoke_testing_(software)). This test will deploy the charm, then verify that the installation event is handled without errors.

Replace the contents of `tests/integration/test_charm.py` with:

```python
import logging
import pathlib

import jubilant
import pytest
import yaml

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(pathlib.Path("charmcraft.yaml").read_text())
APP_NAME = METADATA["name"]


@pytest.mark.juju_setup
def test_deploy(charm: pathlib.Path, juju: jubilant.Juju):
    """Deploy the charm under test."""
    resources = {
        "demo-server-image": METADATA["resources"]["demo-server-image"]["upstream-source"]
    }
    juju.deploy(charm, app=APP_NAME, resources=resources)
    juju.wait(jubilant.all_active)


def test_workload_version_is_set(juju: jubilant.Juju):
    # Verify that the workload version has been set.
    version = juju.status().apps[APP_NAME].version
    # Hardcoded version for simplicity. Ideally we'd get the version directly from the workload.
    assert version == "1.0.4"
```

This test depends on two fixtures:

- `charm` - The `.charm` file to deploy. This fixture is defined in `tests/integration/conftest.py`.
- `juju` - A Jubilant object for interacting with a temporary Juju model. This fixture is provided by the `pytest-jubilant` plugin.

### Run the test

Run the following command from anywhere in the `~/fastapi-demo` directory:

```text
tox -e integration
```

The test takes some time to run as a new Juju model is created and your charm is deployed. If successful, it'll verify that your packed charm can be deployed as expected.

The result should be similar to the following output:

```text
...

============================= 1 passed in 55.43s =============================
  integration: OK (57.79=setup[0.23]+cmd[57.57] seconds)
  congratulations :) (57.84 seconds)
```

```{tip}
`tox -e integration` doesn't pack your charm. If you modify the charm code and want to run the integration tests again, run `charmcraft pack` before `tox -e integration`.
```

The Juju model is destroyed at the end of the test. If you want to run the test and keep the model for further exploration, see the example commands in [](#write-integration-tests-for-a-charm-run-your-tests). The `@pytest.mark.juju_setup` marker on `test_deploy` gives you the option of skipping this test on subsequent runs, for iterative testing on a deployed application.

### Run tests with `charmcraft test`

Charmcraft has an experimental command `charmcraft test` that uses [spread](https://github.com/canonical/spread) to run tests.

If you're interested in trying `charmcraft test`, run the following command in your project directory:

```text
charmcraft init --profile test-kubernetes --force
```

This creates the scaffolding of a spread configuration; the `--force` argument is needed because there are already files in the directory. Our [httpbin-demo charm](https://github.com/canonical/operator/tree/main/examples/httpbin-demo) has a more complete configuration, which you can replicate in your charm. Pay particular attention to:

- `spread.yaml` - Tells spread how to provision a clean environment for each run, using [Concierge](https://github.com/canonical/concierge) to bootstrap Juju and the cloud substrate.
- The `spread` directory - Contains a file `integration/test_charm/task.yaml` that corresponds to `tests/integration/test_charm.py`.

When you run `charmcraft test`, Charmcraft packs the charm, launches an LXD VM (or configures a CI runner), then invokes your pytest integration tests inside the VM.

It's also possible to set up CI so that each `tests/integration/test_*.py` module becomes its own spread job (fanned out as a parallel matrix). Adding a new test module automatically adds a new job. See {ref}`set-up-ci-charmcraft-test`.

## Review the final code

For the full code, see [our example charm for this chapter](https://github.com/canonical/operator/tree/main/examples/k8s-1-minimal).

>**See next: {ref}`Make your charm configurable <make-your-charm-configurable>`**
