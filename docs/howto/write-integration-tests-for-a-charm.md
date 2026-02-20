(write-integration-tests-for-a-charm)=
# How to write integration tests for a charm

> See also: {ref}`testing`

This document shows how to write integration tests for a charm.

```{important}

Integration testing is only one part of a comprehensive testing strategy. Also see {ref}`write-unit-tests-for-a-charm`.

```

The instructions all use the Jubilant library.

> See more: [Jubilant documentation](https://documentation.ubuntu.com/jubilant/)

(write-integration-tests-for-a-charm-prepare-your-environment)=
## Prepare your environment

To run integration tests, you'll need a Juju controller and [tox](https://tox.wiki/en/). We recommend that you set up a Juju controller inside a virtual machine instead of your host machine.

### Create a virtual machine

Use [Multipass](https://canonical.com/multipass/install) to create a virtual machine:

```text
multipass launch --cpus 4 --memory 8G --disk 50G --name juju-sandbox
multipass shell juju-sandbox  # Switch to your virtual machine.
```

Then use [Concierge](https://github.com/canonical/concierge) to set up a Juju controller inside your virtual machine:

```text
sudo snap install --classic concierge
sudo concierge prepare -p <preset> --extra-snaps astral-uv
```

Where `<preset>` is `machine`, `kubernetes`, or another of Concierge's presets. This also installs [uv](https://docs.astral.sh/uv/).

Next, use uv to install tox:

```text
uv tool install tox --python 3.12 --with tox-uv
```

Your virtual machine is now ready. Before using your virtual machine, we recommend that you do a couple more setup steps.

### Take a snapshot

Use {external+multipass:ref}`snapshot <reference-command-line-interface-snapshot>` to take a snapshot of your virtual machine:

```text
exit  # Switch back to your host machine.
multipass stop juju-sandbox
multipass snapshot juju-sandbox
```

If your virtual machine gets into an undesirable state, use {external+multipass:ref}`restore <reference-command-line-interface-restore>` to restore to this point.

### Mount your project directory

With your virtual machine stopped, make your project directory available inside your virtual machine, then start your virtual machine:

```text
multipass mount --type native /path/to/my-charm juju-sandbox:~/my-charm
multipass shell juju-sandbox
```

Then go into your project directory inside the virtual machine:

```text
cd my-charm
```

When it's time to run the integration tests, you'll run them from this directory.

## Prepare the `tox.ini` configuration file

Check that `tox.ini` has an `integration` environment. If you initialised the charm with `charmcraft init` it should already be there. For example:

```ini
[testenv:integration]
description = Run integration tests
runner = uv-venv-lock-runner
dependency_groups =
    integration
pass_env =
    # The integration tests don't pack the charm. If CHARM_PATH is set, the tests deploy the
    # specified .charm file. Otherwise, the tests look for a .charm file in the project dir.
    CHARM_PATH
commands =
    pytest \
        -v \
        -s \
        --tb native \
        --log-cli-level=INFO \
        {[vars]tests_path}/integration \
        {posargs}
```

Also check that `pyproject.toml` has an `integration` dependency group. Again, if you initialised the charm with `charmcraft init` it should already be there. For example:

```toml
[dependency-groups]
...
integration = [
    "jubilant",
    "pytest",
]
```

## Create a test file

By convention, integration tests are kept in the charm’s source tree, in a directory called `tests/integration`.

If you initialised the charm with `charmcraft init`, your charm directory should already contain a  `tests/integration/test_charm.py` file. Otherwise, manually create this directory structure and a test file. You can call the test file anything you like, as long as the name starts with `test_`.

Also create a leaf file called `conftest.py`. We'll edit this file later.

Below is an example of a typical integration test:

```python
def test_operation(charm: pathlib.Path, juju: jubilant.Juju):
    # Deploy this charm:
    juju.deploy(f"./{charm}", config={"foo": ...})

    # Deploy some charm from Charmhub:
    juju.deploy("ubuntu")

    # Integrate the charms:
    juju.integrate("your-app:endpoint1", "ubuntu:endpoint2")

    # Scale your application up:
    juju.add_unit("your-app", num_units=2)

    # Ensure that both applications and all units reach a good state:
    juju.wait(jubilant.all_active)

    # Run an action on a unit:
    result = juju.run("your-app/0", "some-action")
    assert result.results["key"] == "value"

    # What this means depends on the workload:
    assert charm_operates_correctly()
```

A good integration testing suite will check that the charm continues to operate as expected whenever possible, by combining these simple elements.

## Write your tests

### Write fixtures

In `conftest.py` in your integration test directory, add these fixtures:

```python
import logging
import os
import pathlib
import sys
import time

import jubilant
import pytest

logger = logging.getLogger(__name__)


@pytest.fixture(scope="module")
def juju(request: pytest.FixtureRequest):
    """Create a temporary Juju model for running tests."""
    with jubilant.temp_model() as juju:
        yield juju

        if request.session.testsfailed:
            logger.info("Collecting Juju logs...")
            time.sleep(0.5)  # Wait for Juju to process logs.
            log = juju.debug_log(limit=1000)
            print(log, end="", file=sys.stderr)


@pytest.fixture(scope="session")
def charm():
    """Return the path of the charm under test."""
    if "CHARM_PATH" in os.environ:
        charm_path = pathlib.Path(os.environ["CHARM_PATH"])
        if not charm_path.exists():
            raise FileNotFoundError(f"Charm does not exist: {charm_path}")
        return charm_path
    # Modify below if you're building for multiple bases or architectures.
    return next(pathlib.Path(".").glob("*.charm"))
```

The integration tests will depend on these fixtures.

These fixtures don't pack your charm. You'll need to pack your charm before running the tests.

### Deploy your charm

Add this test in your integration test file:

```python
import pathlib

import jubilant


def test_deploy(charm: pathlib.Path, juju: jubilant.Juju):
    """Deploy the charm under test."""
    juju.deploy(f"./{charm}")
    juju.wait(jubilant.all_active)
```

Tests run sequentially in the order they are written in the file. It can be useful to put tests that deploy applications in the top of the file as the applications can be used by other tests. For that reason, adding extra checks or `asserts` in this test is not recommended.

> See more: [](jubilant.temp_model)

#### Example implementations

- [cassandra-operator](https://github.com/canonical/cassandra-operator/blob/e54b482a4b72c45006451cd7436ec9f6e40162d6/tests/integration/test_charm.py#L15-L21)
- [httpbin-demo](https://github.com/canonical/operator/tree/main/examples/httpbin-demo/tests/integration)

### Deploy your charm with resources

> See first: {ref}`manage-resources`

A charm can require `file` or `oci-image` resources to work, which have revision numbers on Charmhub. OCI images can be referenced directly, while file resources are typically built during packing.

```python
    ...
    resources = {"resource_name": "localhost:32000/image_name:latest"}
    juju.deploy(f"./{charm}", resources=resources)
    ...
```

In `charmcraft.yaml`'s `resources` section, the `upstream-source` is, by convention, a usable resource that can be used in testing, allowing your integration test to look like this:

```python
import pathlib

import jubilant
import yaml


METADATA = yaml.safe_load(pathlib.Path("./charmcraft.yaml").read_text())


def test_deploy(charm: pathlib.Path, juju: jubilant.Juju):
    resources = {
        name: res["upstream-source"]
        for name, res in METADATA["resources"].items()
    }

    juju.deploy(f"./{charm}", resources=resources)
    juju.wait(jubilant.all_active)
```

### Test a relation

To test a relation between two applications, integrate them through
the model. Both applications have to be deployed beforehand.

```python
def test_my_integration(charm: pathlib.Path, juju: jubilant.Juju):
    ...
    # Both applications have to be deployed at this point.
    # This could be done above in the current test or in a previous one.
    juju.integrate("your-app:endpoint1", "another:relation_name_2")
    juju.wait(jubilant.all_active)
    # check any assertion here
    ...
```

> See more: [](jubilant.Juju.integrate)

This test (and subsequent tests) don't need to depend on the `charm` fixture. However, it's helpful for each test to depend on `charm`, so that each test fails immediately if a `.charm` file isn't available. If all your tests depend on the same charm being deployed, you could make `charm` an `autouse` fixture.

### Test a configuration

> See first: {ref}`manage-configuration`

You can set a configuration option in your application and check its results.

```python
def test_config_changed(charm: pathlib.Path, juju: jubilant.Juju):
    ...
    juju.config("your-app", {"server_name": "invalid_name"})
    # In this case, when setting server_name to "invalid_name"
    # we could for example expect a blocked status.
    juju.wait(jubilant.all_blocked, timeout=60)
    ...
```

> See also: [](jubilant.Juju.config)

### Test an action

> See also: {external+juju:ref}`Action <action>`

You can execute an action on a unit and get its results.

```python
def test_run_action(charm: pathlib.Path, juju: jubilant.Juju):
    action_register_user = juju.run("your-app/0", "register-user", {"username": "ubuntu"})
    assert action_register_user.status == "completed"
    password = action_register_user.results["user-password"]
    # We could for example check here that we can login with the new user
```

> See also: [](jubilant.Juju.run)

### Interact with the workload

To interact with the workload, you need to have access to it. This is dependent on many aspects of your application, environment and network topology.

You can get information from your application or unit addresses using `juju.status()`. That way, if your application exposes a public address you can reference it. You can also try to connect to a unit address or public address.

```python
def test_workload_connectivity(charm: pathlib.Path, juju: jubilant.Juju):
    status = juju.status()
    app_address = status.applications["my_app"].address
    # Or you can try to connect to a concrete unit
    # address = status.apps["my_app"].units["my_app/0"].public_address
    # address = status.apps["my_app"].units["my_app/0"].address
    r = requests.get(f"http://{address}/")
    assert r.status_code == 200
```

How you can connect to a private or public address is dependent on your configuration, so you may need a different approach.

> See more:
> - [](jubilant.Juju.status)
> - {external+juju:ref}`juju CLI commands > juju expose <command-juju-expose>`

### Run a subprocess command within Juju context

Jubilant provides an escape hatch to invoke the Juju CLI. This can be useful for cases where some feature is not covered. Some commands are global and others only make sense within a model scope:

```python
    ...
    command = ["add-credential", "some-cloud", "-f", "your-creds-file.yaml"]
    stdout = juju.cli(*command)
    ...
    command = ["unexpose", "some-application"]
    stdout = juju.cli(*command, include_model=True)
    ...
```

> See more:
> - [](jubilant.Juju.run)
> - [](jubilant.Juju.cli)

### Use several models

You can use Jubilant with several models, in the same cloud or in
different clouds. This way you can, for example, integrate machine charms
with Kubernetes charms easily.

```python
    model_a = jubilant.Juju("some-model")
    model_b = jubilant.Juju("another-controller:a-model")
    new_model = jubilant.Juju().add_model("a-model", "some-cloud", controller=..., config=..., credential=...)
```

> See more:
> - {external+juju:ref}`Juju offers <manage-offers>`
> - {external+juju:ref}`How to manage clouds <manage-clouds>`

### Deploy a bundle

Here's how an integration can deploy a bundle with the current charm:

```python
def test_deploy_bundle(charm: pathlib.Path, juju: jubilant.Juju):
    # Bundle definition with the charm under test:
    bundle_yaml = f"""

bundle: kubernetes
applications:
  ca:
    charm: self-signed-certificates
    channel: edge
    scale: 1
  my-app:
    charm: ./{charm}
    ...
relations:
- - ca:certificates
  - my-app:certificates

    """.strip()

    # Note that Juju from a snap doesn't have access to /tmp.
    with NamedTemporaryFile(dir=".") as f:
        f.write(bundle_yaml)
        f.flush()
        juju.deploy(f.name)

    juju.wait(jubilant.all_active)
```

(run-your-tests)=
## Run your tests

Make sure that you've packed your charm. Then run all your tests with:

```text
tox -e integration
```

```{note}
If you set up Juju inside a virtual machine, run this tox command in your project directory inside your virtual machine.
```

Your tests will detect a `.charm` file and deploy it. To specify which `.charm` file to deploy:

```text
CHARM_PATH=/path/to/foo.charm tox -e integration
```

Your tests will use the current Juju controller. By default, a new model will be created for each test module. The model will be destroyed when all the tests in the module have finished. This is determined by the scope of the `juju` fixture.

Use the `--cloud`, `--controller`, and `--model` parameters to specify the cloud, controller, and model name. If you specify the model name and include the `--keep-models` parameter, you can reuse a model from a previous test run. For example:

```text
# in the initial execution, the new model will be created
tox -e integration -- --keep-models --model test-example-model
# in the next execution it will reuse the model created previously:
tox -e integration -- --keep-models --model test-example-model --no-deploy
```

There are different ways of specifying a subset of tests to run using `pytest`. With the `-k` option you can specify different expressions. For example, the next command will run all tests in the `test_charm.py` file except `test_one` function.
```text
tox -e integration -- tests/integration/test_charm.py -k "not test_one"
```

> See more:
> - [`pytest | How to invoke pytest`](https://docs.pytest.org/en/7.1.x/how-to/usage.html)
> - [](#validate-your-charm-with-every-change)

## Generate crash dumps

To generate crash dumps, you need the `juju-crashdump` tool .

You can install it with `sudo snap install --classic juju-crashdump`.

> See more:
> - [`juju-crashdump`](https://github.com/juju/juju-crashdump)
