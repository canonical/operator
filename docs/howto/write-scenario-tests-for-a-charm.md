(write-scenario-tests-for-a-charm)=
# How to write unit tests for a charm

First of all, install the testing framework. To do this in a virtual environment
while you are developing, you can do this with `pip` or any other package
manager; for example:

```
pip install ops[testing]
```

Normally, you'll include this in the dependency group for your unit tests, for
example in a test-requirements.txt file:

```text
ops[testing] ~= 2.17
```

Or in `pyproject.toml`:

```toml
[dependency-groups]
test = [
  "ops[testing] ~= 2.17",
]
```

Then, open a new `test_foo.py` file where you will put the test code.

```python
import ops
from ops import testing
```

Then declare a new charm type:
```python
class MyCharm(ops.CharmBase):
    pass        
```

And finally we can write a test function. The test code should use a `Context` object to encapsulate the charm type being tested (`MyCharm`) and any necessary metadata, then declare the initial `State` the charm will be presented when run, and `run` the context with an `event` and that initial state as parameters. 

In code:

```python
def test_charm_runs():
    # Arrange: 
    #  Create a Context to specify what code we will be running,
    ctx = testing.Context(MyCharm)
    #  and create a State to specify what simulated data the charm being run will access.
    state_in = testing.State()

    # Act:
    #  Ask the context to run an event, e.g. 'start', with the state we have previously created.
    state_out = ctx.run(ctx.on.start(), state_in)

    # Assert:
    #  Verify that the output state looks like you expect it to.
    assert state_out.status.unit.name == 'unknown' 
```

> See more: 
>  - [State](https://ops.readthedocs.io/en/latest/reference/ops-testing.html#ops.testing.State)
>  - [Context](https://ops.readthedocs.io/en/latest/reference/ops-testing.html#ops.testing.Context)

```{note}

If you like using unittest, you should rewrite this as a method of some TestCase subclass.
```

## Mocking beyond the State

If you wish to use the framework to test an existing charm type, you will probably need to mock out certain calls that are not covered by the `State` data structure.
In that case, you will have to manually mock, patch or otherwise simulate those calls on top of what the framework does for you.

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
