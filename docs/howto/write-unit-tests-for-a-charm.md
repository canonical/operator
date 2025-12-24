(write-unit-tests-for-a-charm)=
# How to write unit tests for a charm

> See also: [](#testing)

## Set up your environment

First of all, install the Ops testing framework. To do this in a virtual environment while we're developing, use `pip` or a different package manager. For example:

```
pip install ops[testing]
```

When we want to run repeatable unit tests, we'll normally pin `ops[testing]` to the latest minor version in the dependency group for our unit tests. For example, in a `test-requirements.txt` file:

```text
ops[testing] ~= 2.19
```

Or in `pyproject.toml`:

```toml
[dependency-groups]
test = [
  "ops[testing] ~= 2.19",
]
```

## Create the charm and test files

So that we have a charm to test, declare a placeholder charm type in `charm.py`:

```python
class MyCharm(ops.CharmBase):
    pass
```

Then open a new `test_foo.py` file for the test code and import the [`ops.testing`](ops_testing) framework:

```python
import ops
from ops import testing
```

## Write a test

To write a test function, use a `Context` object to encapsulate the charm type (`MyCharm`) and any necessary metadata. The test should then define the initial `State` and call `Context.run` with an `event` and initial `State`.

This follows the typical test structure:

- Arrange inputs, mock necessary functions/system calls, and initialise the charm
- Act by calling `Context.run`
- Assert expected outputs or function calls.

For example, suppose that `MyCharm` uses `Container.Push` to write a YAML config file on the pebble-ready event:

```python
def _on_pebble_ready(self, event: ops.PebbleReadyEvent):
    container = event.workload
    container.push('/etc/config.yaml', 'message: Hello, world!', make_dirs=True)
    # ...
```

A test for this behaviour might look like:

```python
import yaml
from ops import testing

from charm import MyCharm


def test_pebble_ready_writes_config_file():
    """Test that on pebble-ready, a config file is written."""
    # Arrange: setting up the inputs
    ctx = testing.Context(MyCharm)
    container = testing.Container(name="some-container", can_connect=True)
    state_in = testing.State(
        containers=[container],
        leader=True,
    )

    # Act:
    state_out = ctx.run(ctx.on.pebble_ready(container=container), state_in)

    # Assert:
    container_fs = state_out.get_container("some-container").get_filesystem(ctx)
    cfg_file = container_fs / "etc" / "config.yaml"
    config = yaml.safe_load(cfg_file.read_text())
    assert config["message"] == "Hello, world!"

```

```{note}

If you prefer to use unittest, you should rewrite this as a method of a `TestCase` subclass.

```

> See more:
>  - [`State`](ops.testing.State)
>  - [`Context`](ops.testing.Context)

To start with a `State` that has components based on the charm's metadata, use the `State.from_context` method. For example, with this `charmcraft.yaml` file:

```yaml
name: my-charm
containers:
  workload:
    resource: workload-image
peers:
  group-chat:
    interface: gossip
```

Using `State.from_context` will automatically add in a `testing.Container` and `testing.PeerRelation`. For example:

```python
def test_peer_changed():
    ctx = testing.Context(MyCharm)
    # We can pass in all of the arguments for `State()` as well.
    state_in = testing.State.from_context(ctx, leader=True)
    rel_in = state_in.get_relations('group-chat')[0]
    state_out = ctx.run(ctx.on.relation_changed(rel), state_in)
    rel_out = state_out.get_relation(rel.in)
    assert rel_out.peers_data...
```

> See more: [](ops.testing.State.from_context)

## Mock beyond the State

If you wish to use the framework to test an existing charm type, you will probably need to mock out certain calls that are not covered by the `State` data structure. In that case, you will have to manually mock, patch or otherwise simulate those calls.

For example, suppose that the charm we're testing uses the [lightkube client](https://github.com/gtsystem/lightkube) to talk to Kubernetes. To mock that object, modify the test file to contain:

```python
from unittest.mock import MagicMock, patch

import pytest
from ops import testing

from charm import MyCharm


@pytest.fixture
def my_charm():
    with patch("charm.lightkube.Client"):
        yield MyCharm
```

Then you should rewrite the test to pass the patched charm type to the `Context`, instead of the unpatched one. In code:

```python
def test_charm_runs(my_charm):
    # Arrange:
    #  Create a Context to specify what code we will be running
    ctx = testing.Context(my_charm)
    # ...
```

```{note}

If you use pytest, you should put the `my_charm` fixture in a top level `conftest.py`, as it will likely be shared between all your unit tests.
```

## Reuse state

Each test is typically an isolated test of how your charm responds to a single event. However, sometimes it's more convenient to simulate several events in the same test. For example, to check what happens when your charm receives events in a particular order.

After checking a `State` object that `ctx.run` returns, you can provide the same state as input to another simulated event. If you need to modify the state between the events, create a new `State` object instead of modifying the original `State` object. For example:

```python
state_out = ctx.run(...)  # The State we want to reuse.
relation = state_out.get_relation(...)  # A relation we want to modify.

# Copy and modify the relation data.
new_local_app_data = relation.local_app_data.copy()
new_local_app_data["foo"] = "bar"

# Create a new State.
new_relation = dataclasses.replace(relation, local_app_data=new_local_app_data)
new_state = dataclasses.replace(state_out, relations={new_relation})
```

## Access the charm instance

If you need to access the charm instance in a test, use the `testing.Context` instance as a context manager, then access `mgr.charm`. When setting up the context manager, use an event the charm doesn't observe, such as `update_status`. For example:

```python
# Charm code

class Charm(CharmBase):
    def workload_is_ready(self):
        ...  # Some business logic.
        return True


# Testing code

def test_charm_reports_workload_ready():
    ctx = testing.Context(Charm)
    state_in = testing.State(...)  # Some state to represent a ready workload.
    with ctx(ctx.on.update_status(), state_in) as mgr:
        assert mgr.charm.workload_is_ready()
        ...
```

## Run your tests

Run all your tests with:

```text
tox -e unit
```

## Examples

Machine charms:

- Our [machine-tinyproxy](https://github.com/canonical/operator/tree/main/examples/machine-tinyproxy/tests/unit) example charm, from [](machine-charm-tutorial)
- [ubuntu-manpages-operator](https://github.com/canonical/ubuntu-manpages-operator/tree/main/tests/unit)

Kubernetes charms:

- Our [k8s-3-postgresql](https://github.com/canonical/operator/tree/main/examples/k8s-3-postgresql/tests/unit) example charm, from the [](#integrate-your-charm-with-postgresql) chapter in our Kubernetes charm tutorial (the charms from other chapters also have unit tests)
- Our [httpbin-demo](https://github.com/canonical/operator/tree/main/examples/httpbin-demo/tests/unit) example charm
