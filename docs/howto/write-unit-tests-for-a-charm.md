(write-scenario-tests-for-a-charm)=
# How to write unit tests for a charm

```{note}

This page is currently being refactored.

```

First of all, install the Ops testing framework. To do this in a virtual environment
while you are developing, use `pip` or another package
manager. For example:

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
    state_in = testing.State(leader=True)

    # Act:
    #  Ask the context to run an event, e.g. 'start', with the state we have previously created.
    state_out = ctx.run(ctx.on.start(), state_in)

    # Assert:
    #  Verify that the output state looks like you expect it to.
    assert state_out.unit_status == testing.UnknownStatus()
```

> See more: 
>  - [`State`](ops.testing.State)
>  - [`Context`](ops.testing.Context)

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

---

(get-started-with-charm-testing)=
## Get started with charm testing

## Unit testing

### Writing a test

The typical way in which we want to structure a test is:
 - arrange the required inputs
 - mock any function or system call you need to
 - initialise the charm
 - act, by calling `ctx.run`
 - assert some output matches what is expected, or some function is called with the expected parameters, etc...

A simple test might look like this:

```python
from charm import MyCharm
from ops import testing

def test_pebble_ready_writes_config_file():
    """Test that on pebble-ready, a config file is written"""
    ctx = testing.Context(MyCharm)

    relation = testing.Relation(
        'relation-name',
        remote_app_name='remote-app-name',
        remote_units_data={1: {'baz': 'qux'}},
    )
    
    # We are done setting up the inputs:
    state_in = testing.State(
      config={'foo': 'bar'},  # Mock the current charm config.
      leader=True,  # Mock the charm leadership.
      relations={relation},  # Mock relation data.
    )

    # This will fire a `<container-name>-pebble-ready` event.
    state_out = ctx.run(ctx.on.pebble_ready(container), state_in)

    # Suppose that MyCharm has written a YAML config file via Pebble.push():
    container = state_out.get_container(container.name)
    file = "path_to_config_file.yaml"
    config = yaml.safe_load((container.get_filesystem() / file).read())
    assert config[0]['foo']['bar'] == 'baz'  # or whatever
``` 

## Integration testing

### Testing with `pytest-operator`

The integration test template that `charmcraft init` provides includes the starting point for writing integration tests with `pytest-operator` and `python-libjuju`. The `tox.ini` is also configured so that you can run `tox -e integration` to run the tests, provided that you have a cloud (such as LXD or microk8s) and local Juju client.

The entry point for all `pytest-operator` tests is the `ops_test` fixture. The fixture is a module-scoped context which, on entry, adds to Juju a randomly-named new model and destroys it on exit. All tests in that module, and all interactions with the `ops_test` object, will take place against that model.

Once you have used `ops_test` to get a model in which to run your integration tests, most of the remaining integration test code will interact with Juju via the `python-libjuju` package.

> See more: [`python-libjuju`](https://pythonlibjuju.readthedocs.io/en/latest/)

```{note}

*Pro tip*: you can prevent `ops_test` from tearing down the model on exit by passing the `--keep-models` argument. This is useful when the tests fail and the logs don't provide a sufficient post-mortem and a real live autopsy is required.
```

Detailed documentation of how to use `ops_test` and `pytest-operator` is out of scope for this document. However, this is an example of a typical integration test:

```python
async def test_operation(ops_test: OpsTest):
    # Tweak the config:
    app: Application = ops_test.model.applications.get("tester")
    await app.set_config({"my-key": "my-value"})
    
    # Add another charm and integrate them:
    await ops_test.model.deploy('other-app')
    await ops_test.model.relate('tester:endpoint1', 'other-charm:endpoint2')
    
    # Scale it up:
    await app.add_unit(2)
    
    # Remove another app:
    await ops_test.model.remove_application('yet-another-app')
    
    # Run an action on a unit:
    unit: Unit = app.units[1]
    action = await unit.run('my-action')
    assert action.results == <foo>
    
    # What this means depends on the workload:
    assert charm_operates_correctly()  
```

`python-libjuju` has, of course, an API for all inverse operations: remove an app, scale it down, remove a relation...

A good integration testing suite will check that the charm continues to operate as expected whenever possible, by combining these simple elements.
