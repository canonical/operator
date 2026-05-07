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

Probably the most useful operation is [`Container.push`](ops.Container.push), which allows you to write a file to the workload container:

```python
config = '...'
container.push('/etc/myapp/config.yaml', config, make_dirs=True)
```

`make_dirs=True` tells `push` to create directories if they don't exist (`/etc/myapp` in this case).

`Container.push` has many additional features, including the ability to send raw bytes and write data from a file-like object. You can also specify permissions and the user and group for the file.

## Read a file

To read a file from the workload, use [`Container.pull`](ops.Container.pull), which returns a file-like object:

```python
backup = container.pull('/etc/myapp/backup.yaml').read()
```

If you specify the keyword argument `encoding=None` on the `pull()` call, reads from the returned file-like object will return `bytes`. The default is `encoding='utf-8'`, which will decode the file's bytes from UTF-8 so that reads return a Python `str`.

## Copy a directory tree

### To the container

To copy several files to the workload container, use [`Container.push_path`](ops.Container.push_path), which copies files recursively into a specified destination directory. The API docs contain detailed examples of source and destination semantics and path handling.

```python
# copy "/source/dir/[files]" into "/destination/dir/[files]"
container.push_path('/source/dir', '/destination')

# copy "/source/dir/[files]" into "/destination/[files]"
container.push_path('/source/dir/*', '/destination')
```

A trailing "/*" on the source directory is the only supported globbing/matching.

### From the container

To copy several files from the workload container, use [`Container.pull_path`](ops.Container.pull_path), which copies files recursively into a specified destination directory. The API docs contain detailed examples of source and destination semantics and path handling.

```python
# copy "/source/dir/[files]" into "/destination/dir/[files]"
container.pull_path('/source/dir', '/destination')

# copy "/source/dir/[files]" into "/destination/[files]"
container.pull_path('/source/dir/*', '/destination')
```

A trailing "/*" on the source directory is the only supported globbing/matching.

## List files

To list the contents of a directory or return stat-like information about one or more files, use [`Container.list_files`](ops.Container.list_files). It returns a list of [`pebble.FileInfo`](ops.pebble.FileInfo) objects for each entry (file or directory) in the given path, optionally filtered by a glob pattern. For example:

```python
infos = container.list_files('/etc', pattern='*.conf')
total_size = sum(f.size for f in infos)
logger.info('total size of config files: %d', total_size)
names = set(f.name for f in infos)
if 'host.conf' not in names:
    raise Exception('This charm requires /etc/host.conf!')
```

If you want information about the directory itself (instead of its contents), call `list_files(path, itself=True)`.

## Remove a file or directory

To delete a file, use [`Container.remove_path`](ops.Container.remove_path):

```python
container.remove_path('/etc/myapp/access.log')
```

To delete a directory, also use `Container.remove_path`. The directory must be empty unless you specify `recursive=True`:

```python
container.remove_path('/etc/myapp/cachedir', recursive=True)
```

With `recursive=True`, the entire directory tree is deleted recursively (like `rm -r`).

## Check existence

To check whether a file exists, use [`Container.exists`](ops.Container.exists):

```python
container.exists('/etc/myapp/backup.yaml')
```

To check whether a directory exists, use `Container.exists` or [`Container.isdir`](ops.Container.isdir):

```python
container.isdir('/etc/myapp/cachedir')
container.exists('/etc/myapp/cachedir')
```

`Container.exists` and `Container.isdir` are analogous to Python's `os.path.exists` and `os.path.isdir` functions.

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
import tempfile


def test_get_backup_action():
    # Create a temporary file with placeholder data, then mount the file
    # in the workload container so that our charm can see it.
    with tempfile.NamedTemporaryFile() as backup_file:
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
