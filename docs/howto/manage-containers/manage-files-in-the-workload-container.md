(files-in-containers)=
# How to manage files in the workload container

The [](ops.Container) class provides methods for managing files in a container.

Instead of using `ops.Container` directly, we recommend using the {external+charmlibs:ref}`pathops <charmlibs-pathops>` library. `pathops` provides a `ContainerPath` class that uses a `pathlib`-like approach for managing files in a container.

This guide demonstrates how to use `ContainerPath` methods where possible, and `ops.Container` methods for operations that `ContainerPath` doesn't support.

## Prepare your charm code

Add {external+charmlibs:ref}`pathops <charmlibs-pathops>` to `pyproject.toml`:

```toml
dependencies = [
    "charmlibs-pathops>=1,<2",
    # ...
]
```

Then import the library in your charm code:

```python
from charmlibs import pathops
```

It's common to define an attribute on the charm class for the workload container. We recommend that you also define an attribute for the root directory that your charm will operate in. For example:

```python
class MyCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self.container = self.unit.get_container('myapp')
        self.myapp_root = pathops.ContainerPath(
            '/etc/myapp',
            container=self.container,
        )
        # ...
```

## Create a directory

To create a directory in the workload container, use {external+charmlibs:meth}`ContainerPath.mkdir <pathops.ContainerPath.mkdir>`:

```python
self.myapp_root.mkdir(parents=True)  # Creates parent directories if needed.
(self.myapp_root / 'private').mkdir(user='myapp', group='myapp')
```

## Write a file

To write a file to the workload container, use {external+charmlibs:meth}`ContainerPath.write_text <pathops.ContainerPath.write_text>` or {external+charmlibs:meth}`ContainerPath.write_bytes <pathops.ContainerPath.write_bytes>`:

```python
config = '...'
(self.myapp_root / 'config.yaml').write_text(config)
```

`pathops` also has a function {external+charmlibs:func}`ensure_contents <pathops.ensure_contents>` that ensures a file exists with the given contents:

```python
changed = pathops.ensure_contents(self.myapp_root / 'config.yaml', config)
```

## Read a file

To read a file from the workload container, use {external+charmlibs:meth}`ContainerPath.read_text <pathops.ContainerPath.read_text>` or {external+charmlibs:meth}`ContainerPath.read_bytes <pathops.ContainerPath.read_bytes>`:

```python
backup = (self.myapp_root / 'backup.yaml').read_text()
```

## Copy a directory tree

`pathops` doesn't currently have a way to copy a directory tree. Instead, use `ops.Container` methods that are similar to {external+python:func}`shutil.copytree`.

### To the container

To copy several files to the workload container, use [`Container.push_path`](ops.Container.push_path), which copies files recursively into a specified destination directory. The API docs contain detailed examples of source and destination semantics and path handling.

```python
# copy "/source/dir/[files]" into "/destination/dir/[files]"
self.container.push_path('/source/dir', '/destination')

# copy "/source/dir/[files]" into "/destination/[files]"
self.container.push_path('/source/dir/*', '/destination')
```

A trailing "/*" on the source directory is the only supported globbing/matching.

### From the container

To copy several files from the workload container, use [`Container.pull_path`](ops.Container.pull_path), which copies files recursively into a specified destination directory. The API docs contain detailed examples of source and destination semantics and path handling.

```python
# copy "/source/dir/[files]" into "/destination/dir/[files]"
self.container.pull_path('/source/dir', '/destination')

# copy "/source/dir/[files]" into "/destination/[files]"
self.container.pull_path('/source/dir/*', '/destination')
```

A trailing "/*" on the source directory is the only supported globbing/matching.

## List files

To iterate over a directory, use {external+charmlibs:meth}`ContainerPath.glob <pathops.ContainerPath.glob>`:

```python
paths = self.myapp_root.glob('*.yaml')
```

Alternatively, to list the contents of a directory or return stat-like information about one or more files, use [`Container.list_files`](ops.Container.list_files). This method returns a list of [`pebble.FileInfo`](ops.pebble.FileInfo) objects for each entry (file or directory) in the given path, optionally filtered by a glob pattern. For example:

```python
infos = self.container.list_files('/etc/myapp', pattern='*.yaml')
total_size = sum(f.size for f in infos)
logger.info('total size of files: %d', total_size)
names = set(f.name for f in infos)
```

If you want information about the directory itself (instead of its contents), call `list_files(path, itself=True)`.

## Delete a file or directory

To delete a file, use {external+charmlibs:meth}`ContainerPath.unlink <pathops.ContainerPath.unlink>`:

```python
(self.myapp_root / 'access.log').unlink()
```

To delete an empty directory, use {external+charmlibs:meth}`ContainerPath.rmdir <pathops.ContainerPath.rmdir>`:

```python
(self.myapp_root / 'cachedir').rmdir()
```

To delete a directory tree, use [`Container.remove_path`](ops.Container.remove_path):

```python
self.container.remove_path('/etc/myapp/cachedir', recursive=True)
```

## Check existence

To check whether a file exists, use {external+charmlibs:meth}`ContainerPath.exists <pathops.ContainerPath.exists>` or {external+charmlibs:meth}`ContainerPath.is_file <pathops.ContainerPath.is_file>`:

```python
(self.myapp_root / 'backup.yaml').exists()
(self.myapp_root / 'backup.yaml').is_file()
```

To check whether a directory exists, use {external+charmlibs:meth}`ContainerPath.exists <pathops.ContainerPath.exists>` or {external+charmlibs:meth}`ContainerPath.is_dir <pathops.ContainerPath.is_dir>`:

```python
(self.myapp_root / 'cachedir').exists()
(self.myapp_root / 'cachedir').is_dir()
```

## Write unit tests

To inspect the workload container's filesystem in a unit test, use [`Container.get_filesystem`](ops.testing.Container.get_filesystem):

```python
def test_pebble_ready():
    ctx = testing.Context(MyCharm)
    container = testing.Container('myapp', can_connect=True)
    state_in = testing.State(containers={container})
    state_out = ctx.run(ctx.on.pebble_ready(container), state_in)

    # Check that the workload container has the expected config file
    # after our charm handles the pebble-ready event.
    container_root = state_out.get_container('myapp').get_filesystem(ctx)
    config_file = container_root / 'etc' / 'myapp' / 'config.yaml'
    assert config_file.exists()
    assert my_custom_checks(config_file)
```

`get_filesystem` returns a temporary directory that simulates the container's filesystem.

Don't write to the filesystem that `get_filesystem` returns. If a unit test needs to ensure that particular data exists in the container, use [`Container.mounts`](ops.testing.Container.mounts):

```python
def test_get_backup_action(tmp_path):
    # Create a temporary file with placeholder data, then mount the file
    # in the workload container so that our charm can see it.
    backup_file = tmp_path / 'backup.yaml'
    backup_file.write_text(my_custom_data())
    ctx = testing.Context(MyCharm)
    container = testing.Container(
        'myapp',
        can_connect=True,
        mounts={
            'backup': testing.Mount(
                location='/etc/myapp/backup.yaml', source=backup_file
            )
        },
    )
    state_in = testing.State(containers={container})
    state_out = ctx.run(ctx.on.action('get-backup'), state_in)

    # Check that the action returned the contents of backup_file.
    assert ctx.action_results == {'data': my_custom_data()}
```

If the charm writes to `/etc/myapp/backup.yaml` in the container while handling the event, `backup_file.read_text()` will return the data that the charm wrote.
