(write-unit-tests-for-a-charm)=
# How to write unit tests for a charm

## Setting up

First of all, install the Ops testing framework. To do this in a virtual environment while we are developing, use `pip` or other package managers. For example:

```
pip install ops[testing]
```

Normally, we'll include this and pin-point it to the latest minor version in the dependency group for our unit tests, for example in a `test-requirements.txt` file:

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

Declare our new charm type in `charm.py`:

```python
class MyCharm(ops.CharmBase):
    pass        
```

Open a new `test_foo.py` file where we will put the test code and import the [`ops.testing`](ops_testing) framework:

```python
import ops
from ops import testing
```

## Writing a test

To write a test function, use a `Context` object to encapsulate the charm type (`MyCharm`) and any necessary metadata. The test should then define the initial `State` and call `Context.run` with an `event` and initial `State`.

This follows the typical test structure:

- Arrange: arrange inputs, mock necessary functions/system calls, initialize the charm
- Act: act by calling `Context.run`
- Assert: assert expected outputs or function calls.

For example, if `MyCharm` writes a YAML config file via `Container.Push` on the pebble-ready event:

```python
def _on_pebble_ready(self, event: ops.PebbleReadyEvent):        
    container = event.workload
    container.push('/etc/config.yaml', 'message: Hello, world!', make_dirs=True)
    # ...
```

And we want to test this behaviour, the test might look like this:

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
    container_root_fs = container.get_filesystem(ctx)
    cfg_file = container_root_fs / "etc" / "config.yaml"
    config = yaml.safe_load(cfg_file.read_text())
    assert config["message"] == "Hello, world!"

```

```{note}

If you like using unittest, you should rewrite this as a method of some TestCase subclass.

```

> See more: 
>  - [`State`](ops.testing.State)
>  - [`Context`](ops.testing.Context)

## Mocking beyond the State

If you wish to use the framework to test an existing charm type, you will probably need to mock out certain calls that are not covered by the `State` data structure. In that case, you will have to manually mock, patch or otherwise simulate those calls on top of what the framework does for you.

For example, suppose that the charm we're testing uses the `KubernetesServicePatch`. To update the test above to mock that object, modify the test file to contain:

```python
import pytest
from unittest import patch

@pytest.fixture
def my_charm():
    with patch("charm.KubernetesServicePatch"):
        yield MyCharm
```

Then you should rewrite the test to pass the patched charm type to the `Context`, instead of the unpatched one. In code:

```python
def test_charm_runs(my_charm):
    # Arrange: 
    #  Create a Context to specify what code we will be running
    ctx = Context(my_charm)
    # ...
```

```{note}

If you use pytest, you should put the `my_charm` fixture in a top level `conftest.py`, as it will likely be shared between all your unit tests.

```
