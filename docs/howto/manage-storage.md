(manage-storage)=
# How to manage storage
> See first: {external+juju:ref}`Juju | Storage <storage>`, {external+juju:ref}`Juju | Manage storage <manage-storage>`, {external+charmcraft:ref}`Charmcraft | Manage storage <manage-storage>`

## Manage storage for a machine charm

### Define the storage

Define a `storage` section in `charmcraft.yaml` that lists the storage volumes and information about each storage. For example, for a transient filesystem storage mounted to `/cache/` that is at least 1GB in size:

```yaml
storage:
  cache:
    type: filesystem
    description: Somewhere to cache files locally.
    location: /cache/
    minimum-size: 1G
    properties:
      - transient
```

If you don't specify a location for the storage, Juju mounts the storage at the default location:

```
/var/lib/juju/storage/<storage-name>/0
```

### Access the storage

In your charm's `__init__` method, observe the [storage-attached](ops.StorageAttachedEvent) event:

```python
framework.observe(self.on["cache"].storage_attached, self._update_configuration)
```

In this example, we use a holistic event handler called `_update_configuration`. Alternatively, you could use a dedicated handler for the storage-attached event. To learn more about the different approaches, see [](#holistic-vs-delta-charms).

Next, access the storage in `_update_configuration`. Don't hard-code the location of the storage. Instead, get the location from [`self.model.storages`](ops.Model.storages):

```python
def _update_configuration(self, event: ops.EventBase):
    """Update the workload configuration."""
    cache = self.model.storages["cache"]
    if not cache:
        # The storage-attached event hasn't happened yet.
        logger.info("Storage is not yet ready.")
        return
    # Storage is available. Write some data to the cache.
    cache_root = pathops.LocalPath(cache[0].location)
    (cache_root / "data.json").write_text("...")
```

This example uses {external+charmlibs:ref}`charmlibs-pathops <charmlibs-pathops>` to write data to the storage.

Instead of directly writing data to the storage, your charm could put the storage location in a configuration file. For example:

```python
    ...
    # Storage is available. Pass the storage location to the workload.
    config_path = pathops.LocalPath("/etc/my-app/cache-path.config")
    config_path.write_text(cache[0].location)
    # Ask the workload to reload its configuration.
```

### Request additional storage

While Juju provides an `add-storage` command, this does not 'grow' existing storage instances/mounts like you might expect. Rather, it works by increasing the number of storage instances available/mounted for storages configured with the multiple parameter. Handling storage scaling is done by handling `['<name>'].storage_attached` and `['<name>'].storage_detaching` events. For example, with the following in your `charmcraft.yaml` file:

```yaml
storage:
    my-storage:
        type: filesystem
        multiple:
            range: 1-10
```

Juju will deploy the application with the minimum of the range (1 storage instance). Running `juju add-storage <unit> my-storage=32G,2` will add two additional instances to this storage. Adding storage does not modify existing storage mounts. This would generate two separate storage-attached events that should be handled.

If the *charm* needs additional units of a storage, it can request that with the `storages.request` method. The storage must be defined in the metadata as allowing multiple, for example:

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

## Manage storage for a Kubernetes charm

### Define the storage

Define a `storage` section in `charmcraft.yaml` that lists the storage volumes and information about each storage. Also specify where to mount the storage in the workload container.

For example, for a transient filesystem storage that is at least 1GB in size:

```yaml
storage:
  cache:
    type: filesystem
    description: Somewhere to cache files locally.
    minimum-size: 1G
    properties:
      - transient

containers:
  web-service:
    resource: app-image
    mounts:
      - storage: cache
        location: /var/cache
```

Juju mounts the storage at `/var/cache` in the workload container.

### Access the storage

In your charm's `__init__` method, observe the [storage-attached](ops.StorageAttachedEvent) event:

```python
framework.observe(self.on["cache"].storage_attached, self._update_configuration)
```

In this example, we use a holistic event handler called `_update_configuration`. Alternatively, you could use a dedicated handler for the storage-attached event. To learn more about the different approaches, see [](#holistic-vs-delta-charms).

Next, access the storage in `_update_configuration`. Don't hard-code the location of the storage. Instead, get the location from [`ContainerMeta.mounts`](ops.ContainerMeta.mounts) for the workload container:

```python
def _update_configuration(self, event: ops.EventBase):
    """Update the workload configuration."""
    cache = self.model.storages["cache"]
    if not cache:
        # The storage-attached event hasn't happened yet.
        logger.info("Storage is not yet ready.")
        return
    # Storage is available. Write some data to the cache.
    cache_in_container = self.meta.containers["my-container"].mounts["cache"]
    cache_root = pathops.ContainerPath(
        cache_in_container.location,
        container=self.unit.get_container("my-container"),
    )
    try:
        (cache_root / "data.json").write_text("...")
    except ops.pebble.ConnectionError:
        # Pebble isn't ready yet. Return and wait for the pebble-ready event.
        logger.info("Pebble is not yet ready.")
        return
```

This example uses {external+charmlibs:ref}`charmlibs-pathops <charmlibs-pathops>` to write data to the storage in the workload container.

Instead of directly writing data to the storage, your charm could put the storage location in a configuration file. For example:

```python
    ...
    # Storage is available. Pass the storage location to the workload.
    cache_in_container = self.meta.containers["my-container"].mounts["cache"]
    config_path = pathops.ContainerPath(
        "/etc/my-app/cache-path.config",
        container=self.unit.get_container("my-container"),
    )
    try:
        config_path.write_text(cache_in_container.location)
    except ops.pebble.ConnectionError:
        ...
    # Ask the workload to reload its configuration.
```

## Handle storage detaching

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

## Write unit tests

> See first: {ref}`write-unit-tests-for-a-charm`

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

## Write integration tests

> See first: {ref}`write-integration-tests-for-a-charm`

To verify that adding and removing storage works correctly against a real Juju instance, write an integration test with `jubilant`. For example:

```python
def test_storage_attaching(juju: jubilant.Juju):
    # Add two storage units of 2 gigabyte each to unit 0 of the Kafka app.
    juju.cli("add-storage", "kafka/0", "data=2G,2", include_model=True)
    juju.wait(jubilant.all_active)
    # Assert that the storage is being used appropriately.
```
