
<a href="#heading--storage-model"><h2 id="heading--storage-model">Charm and Container Accessing to Storage</h2></a>

When you use storage mounts with juju, it will be automatically mounted into the charm container
at either:

* the specified `location` based on the storage section of metadata.yaml or

* the default location `/var/lib/juju/storage/<storage-name>/<num>` where `num`
  is zero for "normal"/singular storages or integer id for storages that support `multiple`
  attachments.

The operator framework provides the `Model.storages` dict-like member that maps storage names to a
list of storages mounted under that name.  It is a list in order to handle the case of storage
configured for multiple instances.  For the basic singular case, you will simply access the
first/only element of this list.

Charm developers should *not* directly assume a location/path for mounted storage.  To access
mounted storage resources, retrieve the desired storage's mount location from within your charm
code - e.g.:

```python
def _my_hook_function(self, event):
    ...
    storage = self.model.storages['my-storage'][0]
    root = storage.location

    fname = 'foo.txt'
    fpath = os.path.join(root, fname)
    with open(fpath, 'w') as f:
        f.write('super important config info')
    ...
```

This example utilizes the framework's representation of juju storage - i.e. `self.model.storages`
which returns a [`mapping`](https://ops.readthedocs.io/en/latest/index.html#ops.model.StorageMapping) of
`<storage_name>` to [`Storage`](https://ops.readthedocs.io/en/latest/index.html#ops.model.Storage)
objects, which exposes the `name`, `id` and `location` of each storage to the charm developer,
where `id` is the underlying storage provider ID.

If you have also mounted storage in a container, that storage will be located directly at the
specified mount location.  For example with the following content in your metadata.yaml:

```
containers:
  foo:
    resource: foo-image
    mounts:
      - storage: data
        location: /foo-data
```

storage for the "foo" container will be mounted directly at `/foo-data`.  There are no storage name
or integer-indexed subdirectories. Juju does not currently support multiple storage instances for
charms using "containers" functionality.  If you are writing a container-based charm (e.g. for
kubernetes clouds) it is best to have your charm code communicate the storage location to the
workload rather than hard-coding the storage path in the container itself.  This can be
accomplished by various means. One method is passing the mount path via a file using the
`Container` API:

```python
def _on_mystorage_storage_attached(self, event):
    container_meta = self.framework.meta.containers['my-container']
    storage_path = container_meta.mounts['my-storage'].location

    c = self.model.unit.get_container('my-container')
    c.push('/my-app-config/storage-path.cfg', storage_path)

    ... # tell workload service to reload config/restart, etc.
```

<a href="#heading--storage-model"><h2 id="heading--scaling-storage">Scaling Storage</h2></a>
# Scaling Storage

While juju provides an `add-storage` command, this does not "grow" existing storage
instances/mounts like you might expect.  Rather it works by increasing the number of storage
instances available/mounted for storages configured with the `multiple` parameter.  For charm
development, handling storage scaling (add/detach) amounts to handling `<name>_storage_attached`
and `<name_storage_detaching` events. For example, with the following in your metadata.yaml file:

```yaml
storage:
    my-storage:
        type: filesystem
        multiple:
            range: 1-10
```

juju will deploy the application with the minimum of the range (1 storage instance in the example
above).  Storage with this type of `multiple:...` configuration will have each instance residing
under an indexed subdirectory of that storage's main directory - e.g.
`/var/lib/juju/storage/my-storage/1` by default in charm container.  Running `juju add-storage
<unit> my-storage=32G,2` will add two additional instances to this storage - e.g.:
`/var/lib/juju/storage/my-storage/2` and `/var/lib/juju/storage/my-storage/3`.  "Adding" storage
does not modify or affect existing storage mounts.  This would generate two separate
storage-attached events that should be handled.

In addition to juju client requests for adding storage, the [`StorageMapping`](https://ops.readthedocs.io/en/latest/index.html#ops.model.StorageMapping)
returned by `self.model.storages` also exposes a
[`request`](https://ops.readthedocs.io/en/latest/index.html#ops.model.StorageMapping.request)
method (e.g. `self.model.storages.request()`) which provides an expedient method for the developer
to invoke the underlying
[`storage-add`](https://discourse.charmhub.io/t/hook-tools/1163#heading--storage-add) hook tool in
the charm to request additional storage. On success, this will fire a
`<storage_name>-storage-attached` event.


# Testing a Charm's Use of Storage
