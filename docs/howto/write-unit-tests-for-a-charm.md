(write-scenario-tests-for-a-charm)=
# How to write unit tests for a charm

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

TODO

(write-legacy-unit-tests-for-a-charm)=
## How to write legacy unit tests for a charm

`ops` provides a legacy testing harness that was previously used to check your charm does the right thing in different scenarios without having to create a full deployment.

## Testing basics

Here’s a minimal example, taken from the `charmcraft init` template with some additional comments:

```python
# Import Ops library's legacy testing harness
import ops
import ops.testing
import pytest

# Import your charm class
from charm import TestCharmCharm


@pytest.fixture
def harness():
    # Instantiate the Ops library's test harness
    harness = ops.testing.Harness(TestCharmCharm)
    # Set a name for the testing model created by Harness (optional).
    # Cannot be called after harness.begin()
    harness.set_model_name("testing")
    # Instantiate an instance of the charm (harness.charm)
    harness.begin()
    yield harness
    # Run Harness' cleanup method on teardown
    harness.cleanup()


def test_config_changed(harness: ops.testing.Harness[TestCharmCharm]):
    # Test initialisation of shared state in the charm
    assert list(harness.charm._stored.things) == []

    # Simulates the update of config, triggers a config-changed event
    harness.update_config({"things": "foo"})
    # Test the config-changed method stored the update in state
    assert list(harness.charm._stored.things) == ["foo"]

```

We use [`pytest` unit testing framework](https://docs.pytest.org) (Python’s standard [unit testing framework](https://docs.python.org/3/library/unittest.html) is a valid alternative), augmenting it with [](ops_testing_harness). `Harness` provides some convenient mechanisms for mocking charm events and processes.

A common pattern is to specify some minimal `metadata.yaml` content for testing like this:

```python
harness = Harness(TestCharmCharm, meta='''
    name: test-app
    peers:
        cluster:
            interface: cluster
    requires:
      db:
        interface: sql
    ''')
harness.begin()
...
```

When using `Harness.begin()` you are responsible for manually triggering events yourself via other harness calls:

```python
...
# Add a relation and trigger relation-created.
harness.add_relation('db', 'postgresql') # <relation-name>, <remote-app-name>
# Add a peer relation and trigger relation-created 
harness.add_relation('cluster', 'test-app') # <peer-relation-name>, <this-app-name>
```

Notably, specifying relations in `charmcraft.yaml` does not automatically make them created by the
harness.  If you have e.g. code that accesses relation data, you must manually add those relations
(including peer relations) for the harness to provide access to that relation data to your charm.

In some cases it may be useful to start the test harness and fire the same hooks that Juju would fire on deployment. This can be achieved using the `begin_with_initial_hooks()` method , to be used in place of the `begin()` method. This method will trigger the events: `install -> relation-created -> config-changed -> start -> relation-joined` depending on whether any relations have been created prior calling `begin_with_initial_hooks()`. An example of this is shown in [](ops.testing.Harness).

Using the `harness` variable, we can simulate various events in the charm’s lifecycle:

```python
# Update the harness to set the active unit as a "leader" (the default value is False).
# This will trigger a leader-elected event
harness.set_leader(True)
# Update config.
harness.update_config({"foo": "bar", "baz": "qux"})
# Disable hooks if we're about to do something that would otherwise cause a hook
# to fire such as changing configuration or setting a leader, but you don't want
# those hooks to fire.
harness.disable_hooks()
# Update config
harness.update_config({"foo": "quux"})
# Re-enable hooks
harness.enable_hooks()
# Set the status of the active unit. We'd need "from ops.model import BlockedStatus".
harness.charm.unit.status = BlockedStatus("Testing")
```

Any of your charm’s properties and methods (including event callbacks) can be accessed using
`harness.charm`.  You can check out the [harness API
docs](ops_testing_harness) for more ways to use the
harness to trigger other events and to test your charm (e.g. triggering events regarding leadership,
testing pebble events and sidecar container interactions, etc.).


## Testing log output

Charm authors can also test for desired log output. Should a charm author create log messages in the standard form:

```python
# ...
logger = logging.getLogger(__name__)


class SomeCharm(ops.CharmBase):
# ...
    def _some_method(self):
        logger.info("some message")
# ...
```

The above logging output could be tested like so:

```python
# The caplog fixture is available in all pytest's tests
def test_logs(harness, caplog):
    harness.charm._some_method()
    with caplog.at_level(logging.INFO):
        assert [rec.message for rec in caplog.records] == ["some message"]
```

## Simulating container networking

> Added in 1.4, changed in version 2.0

In `ops` 1.4, functionality was added to the Harness to more accurately track connections to workload containers. As of `ops` 2.0, this behaviour is enabled and simulated by default (prior to 2.0, you had to enable it by setting `ops.testing.SIMULATE_CAN_CONNECT` to True before creating Harness instances).

Containers normally start in a disconnected state, and any interaction with the remote container (push, pull, add_layer, and so on) will raise an `ops.pebble.ConnectionError`. 

To mark a container as connected,
you can either call [`harness.set_can_connect(container, True)`](ops.testing.Harness.set_can_connect), or you can call [`harness.container_pebble_ready(container)`](ops.testing.Harness.container_pebble_ready) if you want to mark the container as connected *and* trigger its pebble-ready event.

However, if you're using [`harness.begin_with_initial_hooks()`](ops.testing.Harness.begin_with_initial_hooks) in your tests, that will automatically call `container_pebble_ready()` for all containers in the charm's metadata, so you don't have to do it manually.

If you have a hook that pushes a file to the container, like this:

```python
def _config_changed(event):
    c = self.unit.get_container('foo')
    c.push(...)
    self.config_value = ...
```

Your old testing code won't work:

```python
@fixture
def harness():
    harness = Harness(ops.CharmBase, meta="""
        name: test-app
        containers:
          foo:
            resource: foo-image
        """)
    harness.begin()
    yield harness
    harness.cleanup()

def test_something(harness):
    c = harness.model.unit.get_container('foo')

    # THIS NOW FAILS WITH A ConnectionError:
    harness.update_config(key_values={'the-answer': 42})
```

Which suggests that your `_config_changed` hook should probably use [`Container.can_connect()`](ops.Container.can_connect):

```python
def _config_changed(event):
    c = self.unit.get_container('foo')
    if not c.can_connect():
        # wait until we can connect
        event.defer()
        return
    c.push(...)
    self.config_value = ...
```

Now you can test both connection states:

```
harness.update_config(key_values={'the-answer': 42}) # can_connect is False
harness.container_pebble_ready('foo') # set can_connect to True
assert 42 == harness.charm.config_value
```

---

TODO

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

## Continuous integration

Typically, you want the tests to be run automatically against any PR into your repository's main branch, and sometimes, to trigger a new release whenever that succeeds. CD is out of scope for this article, but we will look at how to set up a basic CI.

Create a file called `.github/workflows/ci.yaml`. For example, to include a `lint` job that runs the `tox` `lint` environment:

```yaml
name: Tests
on:
  workflow_call:

jobs:
  lint:
    name: Lint
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v3
      - name: Install dependencies
        run: python3 -m pip install tox
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
        uses: actions/checkout@v3
      - name: Install dependencies
        run: python -m pip install tox
      - name: Run tests
        run: tox -e unit
```

Integration tests are a bit more complex, because in order to run those tests, a Juju controller and a cloud in which to deploy it, is required. This example uses a `actions-operator` workflow provided by `charmed-kubernetes` in order to set up `microk8s` and Juju:

```
  integration-test-microk8s:
    name: Integration tests (microk8s)
    needs:
      - lint
      - unit-test
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v3
      - name: Setup operator environment
        uses: charmed-kubernetes/actions-operator@main
        with:
          provider: microk8s
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

> You can find more actions, advanced documentation and use cases in [charming-actions](https://github.com/canonical/charming-actions)

## Conclusion

We have examined all angles one might take when testing a charm, and given a brief overview of the most popular frameworks for implementing unit and integration tests, all the way to how one would link them up with a CI system to make sure the repository remains clean and tested.
