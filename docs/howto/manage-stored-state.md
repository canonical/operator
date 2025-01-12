(manage-stored-state)=
# How to manage stored state

> See first: [](storedstate-uses-limitations)

Data stored on a charm instance will not persist beyond the current Juju event,
because a new charm instance is created to handle each event. In general, charms
should be stateless, but in some situations storing state is required. There are
two approaches (outside of using a database or Juju storage): storing state in
the charm machine or (for Kubernetes charms) container - for state that should
have the same lifetime as the machine or container, and storing state in a Juju
peer relation - for state that should have the same lifetime as the application.

## Storing state for the lifetime of the charm container or machine

Where some state is required, and the state should share the same lifetime as
the machine or (for Kubernetes charms) container, `ops` provides
[](ops.StoredState) where data is persisted to the `ops` unit database in the
charm machine or container.

[caution]
Note that for Kubernetes charms, container recreation is expected: even if there
are no errors that require the container to be recreated, the container will be
recreated with every charm update.
[/caution]

[note]
In Kubernetes charms that use the older 'podspec' model, rather than the sidecar
pattern, or when the `use_juju_for_storage` option is set, this data will be
stored in Juju instead, and will persist for the life of the application.
Avoid using `StoredState` objects in these situations.
[/note]

A `StoredState` object is capable of persisting simple data types, such as
integers, strings, or floats, and lists, sets, and dictionaries containing those
types. For more complex data, you will need to serialise the data first, for
example to JSON.

### Implement the feature

To store data in the unit state database, in your `src/charm.py` file, add a
`StoredState` object to your charm class -- this is typically called `_stored`.
You then need to use `set_default` to set an initial value; for example:

```python
class MyCharm(ops.CharmBase):

    _stored = ops.StoredState()

    def __init__(self, framework):
        super().__init__(framework)
        self._stored.set_default('expensive_value', None)
```

> See more: [](ops.StoredState)

Now, in any event handler, you can read or write data to the object you are
storing, and it will be persisted across Juju events.

```python
def _on_start(self, event: ops.StartEvent):
    if self._stored.expensive_value is None:
        self._stored.expensive_value = self._calculate_expensive_value()

def _on_install(self, event: ops.InstallEvent):
    # We can use self._stored.expensive_value here, and it will have the value
    # set in the start event.
```

> Examples: [Tempo reconfiguring ingress on leadership change](https://github.com/canonical/tempo-k8s-operator/blob/3f94027b6173f436968a4736a1f2d89a1f17b2e1/src/charm.py#L263), [Kubeflow Dashboard using a holistic handler to configure on leadership change and other events](https://github.com/canonical/kubeflow-dashboard-operator/blob/02caa736a6ea8986b8cba23b63c08a12aaedb86c/src/charm.py#L82)

### Test the feature

> See first: {ref}`get-started-with-charm-testing`

You'll want to add two levels of tests:

- [Write unit tests](#heading--write-scenario-tests)
- [Write integration tests](#heading--write-integration-tests)

#### Write unit tests

> See first: {ref}`write-scenario-tests-for-a-charm`

Add `StoredState` objects to the `State` with any content that you want to mock
having persisted from a previous event. For example, to have a `_stored`
attribute that has 'foo' and 'baz' keys:

```python
import ops
from ops import testing

class MyCharm(ops.CharmBase):
    _stored = ops.StoredState()

    def __init__(self, framework):
        super().__init__(framework)
        self._stored.setdefault("foo", {})
        framework.observe(self.on.start, self._on_start)
        framework.observe(self.on.update_status, self._on_update_status)

    def _on_start(self, event):
        self._stored["foo"] = 42

    def _on_update_status(self, event):
        logger.info("Current foo: %s", self._stored["foo"])


def test_setting_stored_state():
    ctx = testing.Context(MyCharm, meta={"name": "mycharm"})
    state_in = testing.State()
    state_out = ctx.run(ctx.on.start(), state_in)
    assert state_out.get_stored_state("_stored", owner_path="mycharm").content["foo"] == 42

def test_logging_stored_state():
    ctx = testing.Context(MyCharm, meta={"name": "mycharm"})
    state_in = testing.State(stored_states={
        testing.StoredState(
            "_stored",
            owner_path="MyCharm",
            content={
                'foo': 'bar',
            })
    })
    state_out = ctx.run(ctx.on.update_status(), state_in)
    assert ctx.juju_log[0].message == "Current foo: bar"
```

#### Write integration tests

> See first: [How to write integration tests for a charm](/t/12734)

Juju is in sole control over which unit is the leader, so leadership changes are
not usually tested with integration tests. If this is required, then the test
needs to remove the leader unit (machine charms) or run `juju_stop_unit` in the
charm container (Kubernetes charms). The test then needs to wait up to 60 seconds
for Juju to elect a new leader.

More commonly, an integration test might want to verify that leader and non-leader behaviour is
as expected. For example:

```python
async def get_leader_unit(ops_test, app, model=None):
    """Utility method to get the current leader unit."""
    leader_unit = None
    if model is None:
        model = ops_test.model
    for unit in model.applications[app].units:
        if await unit.is_leader_from_status():
            leader_unit = unit
            break

    return leader_unit
```

> Examples: [Zookeeper testing upgrades](https://github.com/canonical/zookeeper-operator/blob/106f9c2cd9408a172b0e93f741d8c9f860c4c38e/tests/integration/test_upgrade.py#L22), [postgresql testing password rotation action](https://github.com/canonical/postgresql-k8s-operator/blob/62645caa89fd499c8de9ac3e5e9598b2ed22d619/tests/integration/test_password_rotation.py#L38)

> See more: [`juju.unit.Unit.is_leader_from_status`](https://pythonlibjuju.readthedocs.io/en/latest/api/juju.unit.html#juju.unit.Unit.is_leader_from_status)

## Storing state for the lifetime of the application

In this chapter we will adopt the second strategy, that is, we will store charm data in a peer relation databag. (We will explore the third strategy in a different scenario in the next chapter.)  We will illustrate this strategy with an artificial example where we save the counter of how many times the application pod has been restarted.

### Implement the feature

#### Define a peer relation

The first thing you need to do is define a peer relation. Update the `charmcraft.yaml` file to add a `peers` block before the `requires` block, as below (where `fastapi-peer` is a custom name for the peer relation and `fastapi_demo_peers` is a custom name for the peer relation interface): 

```yaml
peers:
  fastapi-peer:
    interface: fastapi_demo_peers
```

<!-- UPDATE LINKS
> Read more: [File ‘charmcraft.yaml`]()
-->

#### Set and get data from the peer relation databag

Now, you need a way to set and get data from the peer relation databag. For that you need to update the `src/charm.py` file as follows:

First, define some helper methods that will allow you to read and write from the peer relation databag:

```python
@property
def peers(self) -> Optional[ops.Relation]:
    """Fetch the peer relation."""
    return self.model.get_relation(PEER_NAME)

def set_peer_data(self, key: str, data: JSONData) -> None:
    """Put information into the peer data bucket instead of `StoredState`."""
    peers = cast(ops.Relation, self.peers)
    peers.data[self.app][key] = json.dumps(data)

def get_peer_data(self, key: str) -> Dict[str, JSONData]:
    """Retrieve information from the peer data bucket instead of `StoredState`."""
    if not self.peers:
        return {}
    data = self.peers.data[self.app].get(key, '')
    if not data:
        return {}
    return json.loads(data)
```

This block uses the built-in `json` module of Python, so you need to import that as well. You also need to define a global variable called `PEER_NAME = "fastapi-peer"`, to match the name of the peer relation defined in `charmcraft.yaml` file. We'll also need to import some additional types from `typing`, and define a type alias for JSON data. Update your imports to include the following:

```python
import json
from typing import Dict, List, Optional, Union, cast
```
Then define our global and type alias as follows:

```python
PEER_NAME = 'fastapi-peer'

JSONData = Union[
    Dict[str, 'JSONData'],
    List['JSONData'],
    str,
    int,
    float,
    bool,
    None,
]
```

Next, you need to add a method that updates a counter for the number of times a Kubernetes pod has been started. Let's make it retrieve the current count of pod starts from the 'unit_stats' peer relation data, increment the count, and then update the 'unit_stats' data with the new count, as below:

```python
def _count(self, event: ops.StartEvent) -> None:
    """This function updates a counter for the number of times a K8s pod has been started.

    It retrieves the current count of pod starts from the 'unit_stats' peer relation data,
    increments the count, and then updates the 'unit_stats' data with the new count.
    """
    unit_stats = self.get_peer_data('unit_stats')
    counter = cast(str, unit_stats.get('started_counter', '0'))
    self.set_peer_data('unit_stats', {'started_counter': int(counter) + 1})
```

Finally, you need to call this method and update the peer relation data every time the pod is started. For that, define another event observer in the `__init__` method, as below:

```python
framework.observe(self.on.start, self._count)
```

### Test the feature

<br>

> <small>**Contributors:**@tmihoc, @tony-meyer</small>
