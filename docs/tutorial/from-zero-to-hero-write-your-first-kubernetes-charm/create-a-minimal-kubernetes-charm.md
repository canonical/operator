(create-a-minimal-kubernetes-charm)=
# Create a minimal Kubernetes charm

> <small> {ref}`From Zero to Hero: Write your first Kubernetes charm <from-zero-to-hero-write-your-first-kubernetes-charm>` > Create a minimal Kubernetes charm</small>
>
> **See previous: {ref}`Set up your development environment <set-up-your-development-environment>`**

<!--
Assuming you are familiar with Juju, you will know that to start using a charm you should run `juju deploy thischarm`. When you run this command targeting a Kubernetes cloud, the following things happen:
-->

<!--
If you are familiar with  Juju, as we assume here, you'll know that, to start using a charm, you run `juju deploy`, and also that, when you do that on a Kubernetes-type cloud, this triggers all of the following:
-->

As you already know from your knowledge of Juju, when you deploy a Kubernetes charm, the following things happen:

1. The Juju controller provisions a pod with at least two containers, one for the Juju unit agent and the charm itself and one container for each application workload container that is specified in the `containers` field of a file in the charm that is called `charmcraft.yaml`.
1. The same Juju controller injects Pebble -- a lightweight, API-driven process supervisor -- into each workload container and overrides the container entrypoint so that Pebble starts when the container is ready.
1. When the Kubernetes API reports that a workload container is ready, the Juju controller informs the charm that the instance of Pebble in that container is ready. At that point, the charm knows that it can start communicating with Pebble.
1. Typically, at this point the charm will make calls to Pebble so that Pebble can configure and start the workload and begin operations.

> Note: In the past, the containers were specified in a `metadata.yaml` file, but the modern practice is that all charm specification is in a single `charmcraft.yaml` file.

<!--the container for the unit agent and the charm is named 'charm'-->
<!--PIETRO'S ORIGINAL WORDING:
1. Typically, at this point the charm will configure and start its workload (through pebble calls) and begin operations.
-->

<!--Pebble is a lightweight, API-driven process supervisor designed to give workload containers something akin to an `init` system that will allow the charm container to interact with it. -->
<!--The charm already knows how to contact Pebble (because the information can be predicted from the container name).
<!--
Conceptually, a charm is code that instructs Juju to deploy and manage an application in the cloud. For every Kubernetes charm Juju will deploy a pod with two containers, one for the Juju agent and the charm code and one for the application workload. The communication between these containers, and the orchestration of the local service processes for the workload application, both happen via Pebble, a lightweight API-driven process supervisor. For a visual representation of the deployment see the picture below.
-->

All  subsequent workload management happens in the same way -- the Juju controller sends events to the charm and the charm responds to these events by managing the workload application in various ways via Pebble. The picture below illustrates all of this for a simple case where there is just one workload container.


![Create a minimal Kubernetes charm](../../resources/create_a_minimal_kubernetes_charm.png)


As a charm developer, your first job is to use this knowledge to create the basic structure and content for your charm:

 - descriptive files (e.g., YAML configuration files like the `charmcraft.yaml` file mentioned above) that give Juju, Python, or Charmcraft various bits of information about your charm, and
- executable files (like the `src/charm.py` file that we will see shortly) where you will use Ops-enriched Python to write all the logic of your charm.

## Create a charm project

In your virtual machine, go into your project directory and create the initial version of your charm:

```text
cd ~/fastapi-demo
charmcraft init --profile kubernetes
```

Charmcraft created several files, including:

- `charmcraft.yaml` - Metadata about your charm. Used by Juju and Charmcraft.
- `pyproject.toml` - Python project configuration. Lists the dependencies of your charm.
- `src/charm.py` - The Python file that will contain the main logic of your charm.

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
    upstream-source: ghcr.io/canonical/api_demo_server:1.0.1
```

### Define the charm class

We'll now write the charm code that handles events from Juju. Charmcraft created `src/charm.py` as the location for this logic.

Replace the contents of `src/charm.py` with:

```python
#!/usr/bin/env python3

"""Kubernetes charm for a demo app."""

import ops


class FastAPIDemoCharm(ops.CharmBase):
    """Charm the service."""

    def __init__(self, framework: ops.Framework) -> None:
        super().__init__(framework)


if __name__ == "__main__":  # pragma: nocover
    ops.main(FastAPIDemoCharm)
```

As you can see, a charm is a pure Python class that inherits from the `CharmBase` class of Ops and which we pass to the `main` function defined in the `ops.main` module. We'll refer to `FastAPIDemoCharm` as the "charm class".

### Handle the pebble-ready event

In the `__init__` function of your charm class, use Ops constructs to add an observer for when the Juju controller informs the charm that the Pebble in its workload container is up and running, as below. As you can see, the observer is a function that takes as an argument an event and an event handler. The event name is created automatically by Ops for each container on the template `<container>-pebble-ready`. The event handler is a method in your charm class that will be executed when the event is fired; in this case, you will use it to tell Pebble how to start your application.

```python
framework.observe(self.on.demo_server_pebble_ready, self._on_demo_server_pebble_ready)
```


```{important}

**Generally speaking:** A charm class is a collection of event handling methods. When you want to install, remove, upgrade, configure, etc., an application, Juju sends information to your charm. Ops translates this information into events and your job is to write event handlers

```

```{tip}

**Pro tip:** Use `__init__` to hold references (pointers) to other `Object`s or immutable state only. That is because a charm is reinitialised on every event.

```

<!--
TOO ADVANCED:
Pro tip:** Use `__init__` to hold references (pointers) to other objects (e.g., relation wrappers) or immutable state only. That is because a fresh charm instance is created on every event, so attaching mutable state to it is error-prone. (You should rather think of all data attached to a charm instance as single-use.) See {ref}`Talking to a workload: Control flow from A to Z <talking-to-a-workload-control-flow-from-a-to-z>`.

"relation wrapper" is advanced Pietro jargon:

like, the FooRelationProvider/FooRelationRequirer objects most relation charm libs offer

these are objects that wrap a relation (a relation endpoint, to be more precise) and expose a high-level API to the charm

so that instead of read/writing relation data directly, the charm can call methods on the wrapper that will take care of the low-level work

not sure if it's generally adopted terminology, but I call them relation endpoint wrappers

-->


Next, define the event handler, as follows:

We'll use the `ActiveStatus` class to set the charm status to active. Note that almost everything you need to define your charm is in the `ops` package that you imported earlier - there's no need to add additional imports.

Use `ActiveStatus` as well as further Ops constructs to define the event handler, as below. As you can see, what is happening is that, from the `event` argument, you extract the workload container object in which you add a custom layer. Once the layer is set you replan your service and set the charm status to active.

<!--
In case it helps, the definition of a Pebble layer is very similar to the definition of a Linux service.
-->


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

The custom Pebble layer that you just added is defined in the  `self._get_pebble_layer()` method. Update this method to match your application, as follows:

In the `__init__` method of your charm class, name your service to `fastapi-service` and add it as a class attribute :

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

### Add logger functionality

In the imports section of `src/charm.py`, import the Python `logging` module and define a logger object, as below. This will allow you to read log data in `juju`.

```python
import logging

# Log messages can be retrieved using juju debug-log
logger = logging.getLogger(__name__)
```

## Try your charm

### Pack your charm

First, ensure that you are inside the Multipass Ubuntu VM, in the `~/fastapi-demo` folder:

```
multipass shell juju-sandbox-k8s
cd ~/fastapi-demo
```

Now, pack your charm project directory into a `.charm` file, as below. This will produce a `.charm` file.  In our case it was named `fastapi-demo_ubuntu-22.04-amd64.charm`; yours should be named similarly, though the name might vary slightly depending on your architecture.

```
charmcraft pack
# Packed fastapi-demo_ubuntu-22.04-amd64.charm
```

```{important}

If packing failed - perhaps you forgot to make `charm.py` executable earlier - you may need to run `charmcraft clean` before re-running `charmcraft pack`. `charmcraft` will generally detect when files have changed, but will miss only file attributes changing.

```

```{important}

**Did you know?** A `.charm` file is really just a zip file of your charm files and code dependencies that makes it more convenient to share, publish, and retrieve your charm contents.

```

<!--ubuntu@juju-sandbox-k8s:~/fastapi-demo$ charmcraft pack-->

<!-- `charmcraft pack` just fetches the dependencies, compiles any modules, makes sure you have all the right pieces of metadata, and zips it up for easy distribution.
-->

<!--```{caution}

This name might vary slightly, depending on your architecture. E.g., for an `arm` processor, you will see `arm64` rather than `amd64`. In the commands below make sure to enter the correct charm name.

```
-->

### Deploy your charm

Deploy the `.charm` file, as below. Juju will create a Kubernetes `StatefulSet` named after your application with one replica.

```text
juju deploy ./fastapi-demo_ubuntu-22.04-amd64.charm --resource \
     demo-server-image=ghcr.io/canonical/api_demo_server:1.0.1
```


```{important}

**If you've never deployed a local charm (i.e., a charm from a location on your machine) before:** <br> As you may know, when you deploy a charm from Charmhub it is sufficient to run `juju deploy <charm name>`. However, to deploy a local charm you need to explicitly define a `--resource` parameter with the same resource name and resource upstream source as in the `charmcraft.yaml`.

```


Monitor your deployment:

```text
juju status --watch 1s
```

When all units are settled down, you should see the output below, where `10.152.183.215` is the IP of the K8s Service and `10.1.157.73` is the IP of the pod.

```text
Model    Controller     Cloud/Region  Version  SLA          Timestamp
testing  concierge-k8s  k8s           3.6.12   unsupported  13:38:19+01:00

App           Version  Status  Scale  Charm         Channel  Rev  Address         Exposed  Message
fastapi-demo           active      1  fastapi-demo             0  10.152.183.215  no

Unit             Workload  Agent  Address      Ports  Message
fastapi-demo/0*  active    idle   10.1.157.73
```

### Try the web server

Validate that the app is running and reachable by sending an HTTP  request as below, where `10.1.157.73` is the IP of our pod and `8000` is the default application port.

```
curl 10.1.157.73:8000/version
```

You should see a JSON string with the version of the application:

```
{"version":"1.0.1"}
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
fastapi-demo-0                 2/2     Running   0          10m
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

### Prepare your test environment

Create a file called `tox.ini` in your project root directory and add the following configuration:

```
[tox]
no_package = True
skip_missing_interpreters = True
min_version = 4.0.0
env_list = unit

[vars]
src_path = {tox_root}/src
tests_path = {tox_root}/tests
all_path = {[vars]src_path} {[vars]tests_path}

[testenv]
set_env =
    PYTHONPATH = {tox_root}/lib:{[vars]src_path}
    PYTHONBREAKPOINT=pdb.set_trace
    PY_COLORS=1
pass_env =
    PYTHONPATH
    CHARM_BUILD_DIR
    MODEL_SETTINGS

[testenv:unit]
description = Run unit tests
deps =
    pytest
    cosl
    coverage[toml]
    ops[testing]
    -r {tox_root}/requirements.txt
commands =
    coverage run --source={[vars]src_path} -m pytest \
        -v \
        -s \
        --tb native \
        {[vars]tests_path}/unit \
        {posargs}
    coverage report
```
> Read more: [`tox.ini`](https://tox.wiki/en/latest/config.html#tox-ini)

If you used `charmcraft init --profile kubernetes` at the beginning of your project, you will already have the `tox.ini` file.

### Prepare your test directory

In your project root directory, create directory for the unit test:

```text
mkdir -p tests/unit
```

### Write a test

In your `tests/unit` directory, create a new file called `test_charm.py` and add the test below. This test will check the behaviour of the `_on_demo_server_pebble_ready` function that you set up earlier. The test will first set up a context, then define the input state, run the action, and check whether the results match the expected values.

```python
import ops
from ops import testing

from charm import FastAPIDemoCharm


def test_pebble_layer():
    ctx = testing.Context(FastAPIDemoCharm)
    container = testing.Container(name='demo-server', can_connect=True)
    state_in = testing.State(
        containers={container},
        leader=True,
    )
    state_out = ctx.run(ctx.on.pebble_ready(container), state_in)
    # Expected plan after Pebble ready with default config
    expected_plan = {
        'services': {
            'fastapi-service': {
                'override': 'replace',
                'summary': 'fastapi demo',
                'command': 'uvicorn api_demo_server.app:app --host=0.0.0.0 --port=8000',
                'startup': 'enabled',
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
        state_out.get_container(container.name).service_statuses['fastapi-service']
        == ops.pebble.ServiceStatus.ACTIVE
    )

```

### Run the test

In your Multipass Ubuntu VM shell, run your test:

```text
ubuntu@juju-sandbox-k8s:~/fastapi-demo$ tox -e unit
```

The result should be similar to the following output:

```text
unit: install_deps> python -I -m pip install cosl 'coverage[toml]' 'ops[testing]' pytest -r /home/ubuntu/fastapi-demo/requirements.txt
unit: commands[0]> coverage run --source=/home/ubuntu/fastapi-demo/src -m pytest -v -s --tb native /home/ubuntu/fastapi-demo/tests/unit
==================================================================================== test session starts =====================================================================================
platform linux -- Python 3.12.3, pytest-8.4.1, pluggy-1.6.0 -- /home/ubuntu/fastapi-demo/.tox/unit/bin/python
cachedir: .tox/unit/.pytest_cache
rootdir: /home/ubuntu/fastapi-demo
collected 1 item

tests/unit/test_charm.py::test_pebble_layer PASSED

===================================================================================== 1 passed in 0.19s ======================================================================================
unit: commands[1]> coverage report
Name           Stmts   Miss  Cover
----------------------------------
src/charm.py      17      0   100%
----------------------------------
TOTAL             17      0   100%
  unit: OK (12.33=setup[11.76]+cmd[0.50,0.07] seconds)
  congratulations :) (12.42 seconds)
```

Congratulations, you have written your first unit test!


(write-integration-tests-for-your-charm)=
## Write integration tests for your charm

A charm should function correctly not just in a mocked environment, but also in a real deployment.

For example, it should be able to pack, deploy, and integrate without throwing exceptions or getting stuck in a `waiting` or a `blocked` status -- that is, it should correctly reach a status of `active` or `idle`.

You can ensure this by writing integration tests for your charm. In the charming world, these are usually written with the [`jubilant`](https://documentation.ubuntu.com/jubilant/) library.

In this section we'll write a small integration test to check that the charm packs and deploys correctly.

### Prepare your test environment

In your `tox.ini` file, add the following new environment:

```
[testenv:integration]
description = Run integration tests
deps =
    pytest
    jubilant
    -r {tox_root}/requirements.txt
commands =
    pytest \
        -v \
        -s \
        --tb native \
        --log-cli-level=INFO \
        {[vars]tests_path}/integration \
        {posargs}
```

If you used `charmcraft init --profile kubernetes` at the beginning of your project, the `testenv:integration` section is already in the `tox.ini` file.

### Prepare your test directory

In your project root directory, create a directory for the integration test:

```text
mkdir -p tests/integration
```

### Write and run a pack-and-deploy integration test

Let's begin with the simplest possible integration test, a [smoke test](https://en.wikipedia.org/wiki/Smoke_testing_(software)). This test will build and deploy the charm, then verify that the installation event is handled without errors.

In your `tests/integration` directory, create a file called `conftest.py` and add the following fixtures:

```python
import pathlib
import subprocess

import jubilant
import pytest


@pytest.fixture(scope='module')
def juju(request: pytest.FixtureRequest):
    with jubilant.temp_model() as juju:
        yield juju

        if request.session.testsfailed:
            log = juju.debug_log(limit=1000)
            print(log, end='')


@pytest.fixture(scope='session')
def charm():
    subprocess.check_call(['charmcraft', 'pack'])  # noqa
    return next(pathlib.Path('.').glob('*.charm'))
```

In the same directory, create a file called `test_charm.py` and add the following test:

```python
import logging
import pathlib

import jubilant
import yaml

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(pathlib.Path('./charmcraft.yaml').read_text())
APP_NAME = METADATA['name']


def test_deploy(charm: pathlib.Path, juju: jubilant.Juju):
    """Build the charm-under-test and deploy it together with related charms.

    Assert on the unit status before any relations/configurations take place.
    """
    resources = {
        'demo-server-image': METADATA['resources']['demo-server-image']['upstream-source']
    }

    # Deploy the charm and wait for active/idle status
    juju.deploy(f'./{charm}', app=APP_NAME, resources=resources)
    juju.wait(jubilant.all_active)
```

The test takes some time to run as Jubilant adds a new model to an existing cluster (whose presence it assumes). If successful, it'll verify that your charm can pack and deploy as expected.

The result should be similar to the following output:

```text
integration: commands[0]> pytest -v -s --tb native --log-cli-level=INFO /home/ubuntu/fastapi-demo/tests/integration
============================= test session starts ==============================
platform linux -- Python 3.10.18, pytest-8.4.1, pluggy-1.6.0 -- /home/ubuntu/fastapi-demo/.tox/integration/bin/python3
cachedir: .tox/integration/.pytest_cache
rootdir: /home/ubuntu/fastapi-demo
configfile: pyproject.toml
collected 1 item

tests/integration/test_charm.py::test_deploy

-------------------------------- live log setup --------------------------------
INFO     jubilant:_juju.py:227 cli: juju add-model --no-switch jubilant-823cf1fd
-------------------------------- live log call ---------------------------------
INFO     jubilant:_juju.py:227 cli: juju deploy --model jubilant-823cf1fd ./fastapi-demo_ubuntu-22.04-amd64.charm fastapi-demo --resource demo-server-image=ghcr.io/canonical/api_demo_server:1.0.1
INFO     jubilant.wait:_juju.py:1164 wait: status changed:
+ .model.name = 'jubilant-823cf1fd'
...
INFO     jubilant.wait:_juju.py:1164 wait: status changed:
- .apps['fastapi-demo'].app_status.current = 'waiting'
- .apps['fastapi-demo'].app_status.message = 'installing agent'
+ .apps['fastapi-demo'].app_status.current = 'active'
PASSED
------------------------------ live log teardown -------------------------------
INFO     jubilant:_juju.py:227 cli: juju destroy-model jubilant-823cf1fd --no-prompt --destroy-storage --force


========================= 1 passed in 63.92s (0:01:03) =========================
  integration: OK (64.10=setup[0.01]+cmd[64.10] seconds)
  congratulations :) (64.15 seconds)
```

## Review the final code

For the full code, see [our example charm for this chapter](https://github.com/canonical/operator/tree/main/examples/k8s-1-minimal).

>**See next: {ref}`Make your charm configurable <make-your-charm-configurable>`**
