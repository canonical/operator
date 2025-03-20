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

Testing charm code is an essential part of charming. Here we will see how to get started with it. We will look at the templates we have available and the frameworks we can use to write good unit, integration, and functional tests.

**What you'll need:**
- knowledge of testing in general
- knowledge of Juju and charms
- knowledge of the Juju models and events, esp. the data involved in a charm's lifecycle

**What you will learn:**
- What are the starting points for adding tests to a charm?
- What do you typically want to test in a charm?
- How can you do that?
  - What can you unit-test?
     - How to effectively use the Harness.
  - What can you only integration-test?
     - What integration testing frameworks are there?
  - Where can you apply functional testing?
- How to automate this in a CI pipeline.

## Charmcraft profiles

The most popular way to set up a charm project is via `charmcraft init`. For example, to get set up for creating a machine charm, run:

```text
charmcraft init --profile=machine
```

This will provide the following files that you'll use when writing your tests (as well as others for building your charm):

```text
.
├── pyproject.toml
├── spread.yaml
├── tests
│   ├── integration
│   │   └── test_charm.py
│   ├── spread
│   │   ├── general
│   │   │   └── integration
│   │   │       └── task.yaml
│   │   └── lib
│   │       ├── cloud-config.yaml
│   │       └── test-helpers.sh
│   └── unit
│       └── test_charm.py
└── tox.ini
```

Charmcraft has a similar profile called `kubernetes`. There are also profiles for building charms for apps developed with Django, Flask, Go, and more.

> See more: {external+charmcraft:ref}`Charmcraft | Tutorial <tutorial>`

## Unit testing

### A charm as an input -> output function

In production, a charm is an object that comes to life when the Juju agent decides to execute it with a given context (we call that an `event`). 
The "inputs" of a charm run are therefore:

 - the event context
 - charm configuration
 - integration (relation) data
 - stored state

Only the event context is guaranteed to be present. The other input sources are optional, but typically a charm will have at least some config and a few relations adding to its inputs.

The charm code executes and typically produces side-effects aimed at its workload (for example: it writes files to a disk, runs commands on a system, or reconfigures a process) or at other charms it integrates with (for example: it writes relation data). We call this 'operating' a workload, and that is what a charm is meant to do. The ways in which a charm operates can be roughly categorised as:
 
- system operations (e.g. kill a process, restart a service, write a file, emit to a syslog server, make a HTTP request)
- cloud operations (e.g. deploy a Kubernetes service, launch a VM)
- workload operations (e.g. send a request to a local server, write a config file)
- Juju operations (write relation data)

If the charm is a machine charm, workload operation calls can be done directly, while if we're talking about a Kubernetes charm, they will likely be mediated by [Pebble](https://github.com/canonical/pebble).

"Juju operations" are the most 'meta' of them all: they do not affect the workload in and of itself, but they share data which is meant to affect the operation of *other* charms that this charm is integrated with.

### What we are testing when we unit-test

A 'live', deployed Juju application will have access to all the inputs we discussed above, including environment variables, host system access, and more. Unit tests will typically want to mock all that and focus on mapping inputs to expected outputs. Any combination of the input sources we mentioned above can result in any combination of operations. A few examples of increasing complexity of scenarios we may want to unit test:

 - if this event occurs, assert that the charm emits that system call
 - if this event occurs, given this config, assert that the charm writes to the filesystem a config file with this expected content
 - if this event occurs, given this relation data and that config value, assert that that system call is made and this relation data is written (to another relation)
 
You will notice that the starting point is typically always an event. A charm doesn't do anything unless it's being run, and it is only run when an event occurs. So there is *always* an event context to be mocked. This has important consequences for the unit-testing framework, as we will see below.

### The testing framework

In the charming world, unit testing means state-transition testing.

> See more [`ops.testing`](ops_testing)

`State` is the 'mocker' for most inputs and outputs you will need. Where a live charm would gather its input through context variables and calls to the Juju API (by running the hook tools), a charm under unit test will gather data using a mocked backend managed by the testing framework. Where a live charm would produce output by writing files to a filesystem, `Context` and `Container` expose a mock filesystem the charm will be able to interact with without knowing the difference. More specific outputs, however, will need to be mocked individually.

A typical test will look like this:
 
- set things up:
  - set up the charm and its metadata
  - set up the context
  - mock any 'output' callable that you know would misfire or break (for example, a system call -- you don't want a unit test to reboot your laptop)
  - set up the Juju state in which the event will fire, including config and relation data
 - **simulate an event via `Context.run`**
 - get the output
 - run assertions on the output

> Obviously, other flows are possible; for example, where you unit test individual charm methods without going through the whole event context setup, but this is the characteristic one.

### Understanding the testing framework

When you instantiate `Context` and `State` objects, the charm instance does not exist yet. Just like in a live charm, it is possible that when the charm is executed for the first time, the Juju model already has given it storage, relations, some config, or leadership. This delay is meant to give us a chance to simulate this in our test setup. You create a `State` object, then you prepare the 'initial state' of the model mock, then you finally initialise the charm and simulate one or more events.

The `Context` provides methods for all the Juju events. For example:

 - the cloud admin changes the charm config: `ctx.on.config_changed()`
 - the cloud admin integrates this charm with some other: `ctx.on.relation_created(relation)`
 - a remote unit joins in a relation (for example, because the cloud admin has scaled up a remote charm): `ctx.on.relation_joined(relation)`
 - a remote unit touches its relation data: `ctx.on.relation_changed(relation)`
 - a cloud admin removes a relation: `ctx.on.relation_departed(relation)`
 - a storage is attached/detached: `ctx.on.storage_attach(storage)` / `ctx.on.storage_detached(storage)`
 - a container becomes ready: `ctx.on.pebble_ready(container)`

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

Where unit testing focuses on black-box method-by-method verification, integration testing focuses on the big picture. Typically integration tests check that the charm does not break (generally this means: blocks with status `blocked` or `error`) when a (mocked) cloud admin performs certain operations. These operations are scripted by using, in order of abstraction:
 -  shell commands against [the `juju` CLI](inv:juju:std:label#list-of-juju-cli-commands)
 - [`python-libjuju`](https://github.com/juju/python-libjuju), wrapping juju api calls
   - [`pytest-operator`](https://github.com/charmed-kubernetes/pytest-operator), a `pytest` plugin wrapping `python-libjuju`
   - [`zaza`](https://zaza.readthedocs.io/en/latest/index.html), a testing-framework-agnostic wrapper on top of `python-libjuju` 

Things you typically want to test with integration tests:
 - The charm can be packed (i.e. `charmcraft pack` does not error)
 - The charm can be deployed (i.e. `juju deploy ./packed_charm.charm` deploys an application that reaches `active` or `waiting` within a reasonable time frame)

These are 'smoke tests' that should always be present, and are provided for you when using `charmcraft init`. The following are non-smokey, proper integration tests.
- The charm can be integrated with other applications without erroring
  - and the relation has the expected effect on the charm's operation logic
- The charm can be configured
  - and the config has the expected effect on the charm's operation logic
- The actions supported by the charm can be executed
  - and return the expected results
- Given any combination of the above relations, configs, etc, the charm 'works': the workload it operates does whatever it is supposed to do.

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

## Conclusion

We have examined all angles one might take when testing a charm, and given a brief overview of the most popular frameworks for implementing unit and integration tests.
