(write-unit-tests-for-a-charm)=
# How to write unit tests for a charm

## Setting up your environment

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

## Creating the charm and test files

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

## Writing a test

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
    ctx.run(ctx.on.pebble_ready(container=container), state_in)

    # Assert:
    container_root_fs = state_out.get_container("some-container").get_filesystem(ctx)
    cfg_file = container_root_fs / "etc" / "config.yaml"
    config = yaml.safe_load(cfg_file.read_text())
    assert config["message"] == "Hello, world!"

```

```{note}

If you prefer to use unittest, you should rewrite this as a method of a `TestCase` subclass.

```

> See more: 
>  - [`State`](ops.testing.State)
>  - [`Context`](ops.testing.Context)

## Mocking beyond the State

If you wish to use the framework to test an existing charm type, you will probably need to mock out certain calls that are not covered by the `State` data structure. In that case, you will have to manually mock, patch or otherwise simulate those calls.

For example, suppose that the charm we're testing uses the [lightkube client](https://github.com/gtsystem/lightkube) to talk to Kubernetes, to mock that object, modify the test file to contain:

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
