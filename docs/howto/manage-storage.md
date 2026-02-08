(manage-storage)=
# How to manage storage
> See first: {external+juju:ref}`Juju | Storage <storage>`, {external+juju:ref}`Juju | Manage storage <manage-storage>`, {external+charmcraft:ref}`Charmcraft | Manage storage <manage-storage>`

## Manage storage for a machine charm

### Define the storage

Each storage can be defined as supporting a single or multiple storage instances. If you define a storage as supporting multiple instances, your charm's users can use `juju add-storage` to increase the number of instances attached to the current unit. (Note that this command doesn't 'grow' existing instances).

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

When your charm is deployed, by default Juju attaches one storage instance to each unit - the minimum of the range 1-10. The instance is at least 1GB in size. Each additional instance that's attached will also be at least 1GB in size.

Juju mounts each storage instance in the unit's filesystem. Your charm should configure the workload with the path of each mounted instance.

You can specify where to mount the storage instances by adding a `location` key to the `cache` definition, but we don't recommend doing this. Even if you specify a mount location, the path of each mounted instance will contain an identifier that Juju determines, so you won't be able to hard-code storage instance paths in the workload configuration.

### Configure the workload or access the storage

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
    # Configure the workload to use the storage instance paths.
    ...
```

The length of `cache_paths` matches the number of storage instances currently attached to the unit.

If we hadn't specified `multiple` in the storage definition, `cache` would either be a singleton list or empty, depending on whether a storage instance is attached.

> See more: [](ops.Model.storages)

To access the storage instances in charm code, use {external+charmlibs:ref}`pathops <charmlibs-pathops>` or standard file operations. For example:

```python
    # Prepare each storage instance for use by the workload.
    for path in cache_paths:
        cache_root = pathops.LocalPath(path)
        (cache_root / "uploaded-data").mkdir(exist_ok=True)
        (cache_root / "processed-data").mkdir(exist_ok=True)
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

```{note}
Each storage in a Kubernetes charm supports a single storage instance. Multiple storage instances aren't supported.
```

Let's define a storage called `cache`. In `charmcraft.yaml`:

```yaml
storage:
  cache:
    description: Somewhere to cache files locally.
    type: filesystem
    properties:
      - transient
    minimum-size: 1G

containers:
  web:
    resource: web-image
    mounts:
      - storage: cache
        location: /var/cache
```

When your charm is deployed, Juju attaches a storage instance to each unit and mounts the instance in the charm container's filesystem. The instance is at least 1GB in size.

Juju also mounts the storage instance in the workload container's filesystem, at `/var/cache`. Depending on the workload, your charm might need to configure the workload to expect storage at this location.

### Configure the workload or access the storage

In your charm's `__init__` method, observe the [storage-attached](ops.StorageAttachedEvent) event:

```python
    framework.observe(self.on["cache"].storage_attached, self._update_configuration)
```

In this example, we use a holistic event handler called `_update_configuration`. Alternatively, you could use a dedicated handler for the storage-attached event. To learn more about the different approaches, see [](#holistic-vs-delta-charms).

Next, in `_update_configuration`, get the storage instance path in the workload container:

```python
def _update_configuration(self, event: ops.EventBase):
    """Update the workload configuration."""
    cache = self.model.storages["cache"]
    if not cache:
        logger.info("No instance available for storage 'cache'.")
        return
    web_cache_path = self.meta.containers["web"].mounts["cache"].location
    # Configure the workload to use the storage instance path (assuming that
    # the workload container image isn't preconfigured to expect storage at
    # the location specified in charmcraft.yaml).
    # For example, provide the storage instance path in the Pebble layer.
    web_container = self.unit.get_container("web")
    try:
        web_container.add_layer(...)
    except ops.pebble.ConnectionError:
        logger.info("Workload container is not available.")
        return
    web_container.replan()
```

> See more: [](ops.Model.storages), [](ops.ContainerMeta.mounts)

To access the storage instance in charm code, use {external+charmlibs:ref}`pathops <charmlibs-pathops>` or standard file operations in the charm container. For example:

```python
    # Prepare the storage instance for use by the workload.
    charm_cache_path = cache[0].location  # Always index 0 in a K8s charm.
    charm_cache_root = pathops.LocalPath(charm_cache_path)
    (charm_cache_root / "uploaded-data").mkdir(exist_ok=True)
    (charm_cache_root / "processed-data").mkdir(exist_ok=True)
```

Alternatively, use {external+charmlibs:class}`pathops.ContainerPath` to access `web_cache_path` in the workload container. This approach is more appropriate if you need to reference additional data in the workload container.

## Handle storage detaching

In the `src/charm.py` file, in the `__init__` function of your charm, set up an observer for the detaching event associated with your storage and pair that with an event handler. For example:

```python
    framework.observe(self.on["cache"].storage_detaching, self._on_storage_detaching)
```

> See more: [](ops.StorageDetachingEvent)

Now, in the body of the charm definition, define the event handler, or adjust an existing holistic one. For example, to warn users that data won't be cached:

```python
def _on_storage_detaching(self, event: ops.StorageDetachingEvent):
    """Handle the storage being detached."""
    self.unit.status = ops.ActiveStatus("Caching disabled; provide storage to boost performance")
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

```python
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
