(manage-storage)=
# How to manage storage
> See first: {external+juju:ref}`Juju | Storage <storage>`, {external+juju:ref}`Juju | Manage storage <manage-storage>`, {external+charmcraft:ref}`Charmcraft | Manage storage <manage-storage>`

## Implement the feature

### Declare the storage

To define the storage that can be provided to the charm, define a `storage` section in `charmcraft.yaml` that lists the storage volumes and information about each storage. For example, for a transient filesystem storage mounted to `/cache/` that is at least 1GB in size:

```yaml
storage:
  local-cache:
      type: filesystem
      description: Somewhere to cache files locally.
      location: /cache/
      minimum-size: 1G
      properties:
          - transient
```

For Kubernetes charms, you also need to define where on the workload container the volume will be mounted. For example, to mount a similar cache filesystem in `/var/cache/`:

```yaml
storage:
  local-cache:
      type: filesystem
      description: Somewhere to cache files locally.
      # The location is not required here, because it defines the location on
      # the charm container, not the workload container.
      minimum-size: 1G
      properties:
          - transient

containers:
  web-service:
    resource: app-image
    mounts:
      - storage: local-cache
        location: /var/cache
```

### Observe the `storage-attached` event and define an event handler

In the `src/charm.py` file, in the `__init__` function of your charm, set up an observer for the `storage-attached` event associated with your storage and pair that with an event handler, typically a holistic one. For example:

```
self.framework.observe(self.on.cache_storage_attached, self._update_configuration)
```

> See more: [](ops.StorageAttachedEvent), [](/explanation/holistic-vs-delta-charms)

Storage volumes will be automatically mounted into the charm container at either the path specified in the `location` field in the metadata, or the default location `/var/lib/juju/storage/<storage-name>`. However, your charm code should not hard-code the location, and should instead use the `.location` property of the storage object.

Now, in the body of the charm definition, define the event handler, or adjust an existing holistic one. For example, to provide the location of the attached storage to the workload configuration:

```
def _update_configuration(self, event: ops.EventBase):
    """Update the workload configuration."""
    cache = self.model.storages["cache"]
    if cache.location is None:
        # This must be one of the other events. Return and wait for the storage-attached event.
        logger.info("Storage is not yet ready.")
        return
    try:
        self.push_configuration(cache_dir=cache.location)
    except ops.pebble.ConnectionError:
        # Pebble isn't ready yet. Return and wait for the pebble-ready event.
        logger.info("Pebble is not yet ready.")
        return
```

> Examples: [ZooKeeper ensuring that permission and ownership is correct](https://github.com/canonical/zookeeper-operator/blob/106f9c2cd9408a172b0e93f741d8c9f860c4c38e/src/charm.py#L247), [Kafka configuring additional storage](https://github.com/canonical/kafka-k8s-operator/blob/25cc5dd87bc2246c38fc511ac9c52f35f75f6513/src/charm.py#L298)

### Observe the detaching event and define an event handler

In the `src/charm.py` file, in the `__init__` function of your charm, set up an observer for the detaching event associated with your storage and pair that with an event handler. For example:

```
self.framework.observe(self.on.cache_storage_detaching, self._on_storage_detaching)
```

> See more: [](ops.StorageDetachingEvent)

Now, in the body of the charm definition, define the event handler, or adjust an existing holistic one. For example, to warn users that data won't be cached:

```
def _on_storage_detaching(self, event: ops.StorageDetachingEvent):
    """Handle the storage being detached."""
    self.unit.status = ops.ActiveStatus("Caching disabled; provide storage to boost performance)
```

> Examples: [MySQL handling cluster management](https://github.com/canonical/mysql-k8s-operator/blob/4c575b478b7ae2a28b09dde9cade2d3370dd4db6/src/charm.py#L823), [MongoDB updating the set before storage is removed](https://github.com/canonical/mongodb-operator/blob/b33d036173f47c68823e08a9f03189dc534d38dc/src/charm.py#L596)

### Request additional storage

```{note}

Juju only supports adding multiple instances of the same storage volume on machine charms. Kubernetes charms may only have a single instance of each volume.
```

If the charm needs additional units of a storage, it can request that with the `storages.request`
method. The storage must be defined in the metadata as allowing multiple, for
example:

```yaml
storage:
    scratch:
        type: filesystem
        location: /scratch
        multiple: 1-10
```

For example, if the charm needs to request two additional units of this storage:

```python
self.model.storages.request("scratch", 2)
```

The storage will not be available immediately after that call - the charm should
observe the `storage-attached` event and handle any remaining setup once Juju
has attached the new storage.

## Test the feature

> See first: {ref}`get-started-with-charm-testing`

You'll want to add unit and integration tests:

### Write unit tests

> See first: {ref}`write-scenario-tests-for-a-charm`

To verify that the charm state is as expected after storage changes, use the `run` method of the `Context` object. For example, to provide the charm with mock storage:

```python
from ops import testing

# Some charm with a 'foo' filesystem-type storage defined in its metadata:
ctx = testing.Context(MyCharm)
storage = testing.Storage("foo")

# Set up storage with some content:
(storage.get_filesystem(ctx) / "myfile.txt").write_text("helloworld")

with ctx(ctx.on.update_status(), testing.State(storages={storage})) as mgr:
    foo = mgr.charm.model.storages["foo"][0]
    loc = foo.location
    path = loc / "myfile.txt"
    assert path.exists()
    assert path.read_text() == "helloworld"

    myfile = loc / "path.py"
    myfile.write_text("helloworlds")

    state_out = mgr.run()

# Verify that the contents are as expected afterwards.
assert (
    state_out.get_storage(storage.name).get_filesystem(ctx) / "path.py"
).read_text() == "helloworlds"
```

If a charm requests adding more storage instances while handling some event, you
can inspect that from the `Context.requested_storage` API.

```python
ctx = testing.Context(MyCharm)
ctx.run(ctx.on.some_event_that_will_request_more_storage(), testing.State())

# The charm has requested two 'foo' storage volumes to be provisioned:
assert ctx.requested_storages['foo'] == 2
```

Requesting storage volumes has no other consequence in the unit test. In real life,
this request will trigger Juju to provision the storage and execute the charm
again with foo-storage-attached. So a natural follow-up test suite for
this case would be:

```
ctx = testing.Context(MyCharm)
foo_0 = testing.Storage('foo')
# The charm is notified that one of the storage volumes it has requested is ready:
ctx.run(ctx.on.storage_attached(foo_0), testing.State(storages={foo_0}))

foo_1 = testing.Storage('foo')
# The charm is notified that the other storage is also ready:
ctx.run(ctx.on.storage_attached(foo_1), testing.State(storages={foo_0, foo_1}))
```

> See more: [](ops.testing.Storage)

### Write integration tests

> See first: {ref}`write-integration-tests-for-a-charm`

To verify that adding and removing storage works correctly against a real Juju instance, write an integration test with `pytest_operator`. For example:

```python
# This assumes there is a previous test that handles building and deploying.
async def test_storage_attaching(ops_test):
    # Add a 1GB "cache" storage:
    await ops_test.model.applications[APP_NAME].units[0].add_storage("cache", size=1024*1024)

    await ops_test.model.wait_for_idle(
        apps=[APP_NAME], status="active", timeout=600
    )

    # Assert that the storage is being used appropriately.
```
