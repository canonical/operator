(manage-stored-state)=
# How to manage stored state

> See first: {ref}`storedstate-uses-limitations`

Data stored on a charm instance will not persist beyond the current Juju event,
because a new charm instance is created to handle each event. In general, charms
should be stateless, but in some situations storing state is required. There are
two approaches (outside of using a database or Juju storage): storing state in
the charm machine or (for Kubernetes charms) container - for state that should
have the same lifetime as the machine or container, and storing state in a Juju
peer relation - for state that should have the same lifetime as the application.

```{tip}
Write your charm to be stateless, where possible.
```

## Storing state for the lifetime of the charm container or machine

Where some state is required, and the state should share the same lifetime as
the machine or (for Kubernetes charms) container, `ops` provides
[](ops.StoredState), where data is persisted to the `ops` unit database in the
charm machine or container.

```{caution}
Note that for Kubernetes charms, container recreation is expected: even if there
are no errors that require the container to be recreated, the container will be
recreated with every charm update.
```

```{note}
In Kubernetes charms that use the older 'podspec' model, rather than the sidecar
pattern, or when the `use_juju_for_storage` option is set, this data will be
stored in Juju instead, and will persist for the life of the application.
Avoid using `StoredState` objects in these situations.
```

A `StoredState` object is capable of persisting simple data types, such as
integers, strings, or floats, and lists, sets, and dictionaries containing those
types. For more complex data, serialise the data first, for example to JSON.

### Implement the feature

To store data in the unit state database, in your `src/charm.py` file, add a
`StoredState` object to your charm class -- this is typically called `_stored`.
You then need to use `set_default` to set an initial value; for example:

```python
class MyCharm(ops.CharmBase):

    _stored = ops.StoredState()

    def __init__(self, framework):
        super().__init__(framework)
        self._stored.set_default(expensive_value=None)
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
    logger.info("Current value: %s", self._stored.expensive_value)
```

> Examples: [Kubernetes-Dashboard stores core settings](https://github.com/charmed-kubernetes/kubernetes-dashboard-operator/blob/03bf0f64d943e39176c804cd796a7a9838bf13ab/src/charm.py#L42)

### Test the feature

You'll want to add unit tests.

For integration tests: stored state isn't a feature, it's functionality that
enables features, so your integration tests that make use of the stored state
will verify that it works correctly. There are no special constructs to use in
an integration test: just trigger multiple Juju events.

#### Write unit tests

> See first: {ref}`write-unit-tests-for-a-charm`

Add `StoredState` objects to the `State` with any content that you want to mock
having persisted from a previous event. For example, in your
`tests/unit/test_charm.py` file provide a `_stored` attribute that has an
`expensive_value` key:

```python
def test_charm_sets_stored_state():
    ctx = testing.Context(MyCharm)
    state_in = testing.State()
    state_out = ctx.run(ctx.on.start(), state_in)
    ss = state_out.get_stored_state("_stored", owner_path="MyCharm")
    assert ss.content["expensive_value"] == 42

def test_charm_logs_stored_state():
    ctx = testing.Context(MyCharm)
    state_in = testing.State(stored_states={
        testing.StoredState(
            "_stored",
            owner_path="MyCharm",
            content={
                'expensive_value': 42,
            })
    })
    state_out = ctx.run(ctx.on.install(), state_in)
    assert ctx.juju_log[0].message == "Current value: 42"
```

## Storing state for the lifetime of the application

To store state for the lifetime of the application, add a peer relation and
store the data in the relation databag.

### Implement the feature

#### Define a peer relation

Update the {external+charmcraft:ref}`charmcraft.yaml file <charmcraft-yaml-file>` to add a `peers` block, as below:

```yaml
peers:
  charm-peer:
    interface: my_charm_peers
```

#### Set and get data from the peer relation databag

In your `src/charm.py` file, set and get the data from the peer relation
databag. For example, to store an expensive calculation:

```python
def _on_start(self, event: ops.StartEvent):
    peer = self.model.get_relation('charm-peer')
    peer.data[self.app]['expensive-value'] = self._calculate_expensive_value()

def _on_stop(self, event: ops.StopEvent):
    peer = self.model.get_relation('charm-peer')
    logger.info('Value at stop is: %s', peer.data[self.app]['expensive-value'])
```

```{caution}
Peer relations are not available early in the Charm lifecycle, so you'll need
to wait until later events, like `start`, to store and retrieve data.
```

### Test the feature

> See first: {ref}`write-unit-tests-for-a-charm`

You'll want to add unit tests.

For integration tests: stored state isn't a feature, it's functionality that
enables features, so your integration tests that make use of the stored state
will verify that it works correctly. There are no special constructs to use in
an integration test: just trigger multiple Juju events.

#### Write unit tests

> See first: {ref}`write-unit-tests-for-a-charm`

In your `tests/unit/test_charm.py` file, add tests that have an initial state
that includes a [](ops.testing.PeerRelation) object.

```python
def test_charm_sets_stored_state():
    ctx = testing.Context(MyCharm)
    peer = testing.PeerRelation('charm-peer')
    state_in = testing.State(relations={peer})
    state_out = ctx.run(ctx.on.start(), state_in)
    rel = state_out.get_relation(peer.id)
    assert rel.local_app_data["expensive_value"] == "42"
```
