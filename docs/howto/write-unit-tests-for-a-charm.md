(write-unit-tests-for-a-charm)=
# How to write legacy unit tests for a charm

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
