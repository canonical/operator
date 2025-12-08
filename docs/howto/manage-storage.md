(manage-storage)=
# How to manage storage
> See first: {external+juju:ref}`Juju | Storage <storage>`, {external+juju:ref}`Juju | Manage storage <manage-storage>`, {external+charmcraft:ref}`Charmcraft | Manage storage <manage-storage>`

## Manage storage for a machine charm

### Define the storage

Each named storage can be defined as supporting a single or multiple storage instances. If you define a storage as supporting multiple instances, your charm's users can use `juju add-storage` to increase the number of instances attached to your charm. (This command doesn't 'grow' existing instances, as you might have expected.)

Let's define a storage called `cache` that supports multiple instances. In `charmcraft.yaml`:

```yaml
storage:
  cache:
    description: Somewhere to cache files locally.
    type: filesystem
    properties:
      - transient
    minimum-size: 1G
    multiple:
      range: 1-10
```

When your charm is deployed, Juju attaches one storage instance to each unit - the minimum of the range 1-10. The instance is at least 1GB in size. Each additional instance that's attached will also be at least 1GB in size.

TODO: Confirm that this ^ is true!

Juju mounts each storage instance in the unit's filesystem. Your charm should configure the workload with the path of each mounted instance.

You can specify where to mount the instances by adding a `location` key to the `cache` definition, but we don't recommend doing this. Even if you specify a mount location, the path of each mounted instance will contain an identifier that Juju determines, so you won't be able to hard-code storage instance paths in the workload configuration.

### Configure the workload

In your charm's `__init__` method, observe the [storage-attached](ops.StorageAttachedEvent) event:

```python
    framework.observe(self.on["cache"].storage_attached, self._update_configuration)
```

In this example, we use a holistic event handler called `_update_configuration`. Alternatively, you could use a dedicated handler for the storage-attached event. To learn more about the different approaches, see [](#holistic-vs-delta-charms).

Next, in `_update_configuration`, get the storage instance paths that Juju creates:

```python
def _update_configuration(self, event: ops.EventBase):
    """Update the workload configuration."""
    cache = self.model.storages["cache"]
    if not cache:
        logger.info("No instances available for storage 'cache'.")
        return
    cache_paths = [instance.location for instance in cache]
    # Configure the workload to use the available storage instance paths.
    ...
```

The length of `cache_paths` matches the number of storage instances attached to the unit.

If we hadn't specified `multiple` in the storage definition, `cache` would either be a singleton list or empty, depending on whether a storage instance is attached.

> See more: [](ops.Model.storages)

To access the storage instances in charm code, use {external+charmlibs:ref}`pathops <charmlibs-pathops>` or standard file operations. For example:

```python
    # Prepare each storage instance for use by the workload.
    for path in cache_paths:
        root = pathops.LocalPath(path)
        (root / "uploaded-data").mkdir(exist_ok=True)
        (root / "processed-data").mkdir(exist_ok=True)
```

### Request more storage instances

If `multiple` is specified in the storage definition in `charmcraft.yaml`, your charm's users can use `juju add-storage` to increase the number of instances attached to your charm. For example:

```text
juju add-storage <unit> cache=2  # Request two more instances.
```

Your charm will receive a storage-attached event as each additional instance becomes available.

To request more instances in charm code, use [](ops.StorageMapping.request). For example:

```python
    self.model.storages.request("cache", 2)  # Request two more instances.
```

The additional instances won't be available immediately after the call. As with `juju add-storage`, your charm will receive a storage-attached event as each additional instance becomes available.

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
    cache_in_container = self.meta.containers["web-service"].mounts["cache"]
    cache_root = pathops.ContainerPath(
        cache_in_container.location,
        container=self.unit.get_container("web-service"),
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
    cache_in_container = self.meta.containers["web-service"].mounts["cache"]
    config_path = pathops.ContainerPath(
        "/etc/my-app/cache-path.config",
        container=self.unit.get_container("web-service"),
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
