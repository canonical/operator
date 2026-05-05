(files-in-containers)=
# How to manage files in the workload container

The [](ops.Container) class provides methods to manage files in the workload container. You can write files ("push"), read files ("pull"), list files in a directory, make directories, and delete files or directories.

This guide demonstrates how to use `ops.Container` methods. For a `pathlib`-like approach to managing files in the workload container, use `ContainerPath` methods from the {external+charmlibs:ref}`pathops <charmlibs-pathops>` library.

## Push

Probably the most useful operation is [`Container.push`](ops.Container.push), which allows you to write a file to the workload container:

```python
config = '...'
container.push('/etc/myapp/config.yaml', config, make_dirs=True)
```

`make_dirs=True` tells `push` to create directories if they don't exist (`/etc/myapp` in this case).

`Container.push` has many additional features, including the ability to send raw bytes and write data from a file-like object. You can also specify permissions and the user and group for the file.

## Pull

To read a file from the workload, use [`Container.pull`](ops.Container.pull), which returns a file-like object:

```python
backup = container.pull('/etc/myapp/backup.yaml').read()
```

If you specify the keyword argument `encoding=None` on the `pull()` call, reads from the returned file-like object will return `bytes`. The default is `encoding='utf-8'`, which will decode the file's bytes from UTF-8 so that reads return a Python `str`.

## Push recursive

To copy several files to the workload container, use [`Container.push_path`](ops.Container.push_path), which copies files recursively into a specified destination directory. The API docs contain detailed examples of source and destination semantics and path handling.

```python
# copy "/source/dir/[files]" into "/destination/dir/[files]"
container.push_path('/source/dir', '/destination')

# copy "/source/dir/[files]" into "/destination/[files]"
container.push_path('/source/dir/*', '/destination')
```

A trailing "/*" on the source directory is the only supported globbing/matching.

## Pull recursive

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

## Create directory

To create a directory, use [`Container.make_dir`](ops.Container.make_dir):

```python
container.make_dir('/etc/myapp/private', user='myapp', group='myapp')
container.make_dir('/etc/myapp/path/to/nested/dir', make_parents=True)
```

## Remove path

To delete a file, use [`Container.remove_path`](ops.Container.remove_path):

```python
container.remove_path('/etc/myapp/access.log')
```

To delete a directory, also use `Container.remove_path`. The directory must be empty unless you specify `recursive=True`:

```python
container.remove_path('/etc/myapp/cachedir', recursive=True)
```

With `recursive=True`, the entire directory tree is deleted recursively (like `rm -r`).

## Check file and directory existence

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

### Mount files in the container

You can configure a container to have some files in it:

```python
import pathlib

local_file = pathlib.Path('/path/to/local/real/file.txt')

container = testing.Container(
    name='foo',
    can_connect=True,
    mounts={'local': testing.Mount(location='/local/share/config.yaml', source=local_file)},
    )
state = testing.State(containers={container})
```

In this case, if the charm were to:

```python
def _on_start(self, _):
    foo = self.unit.get_container('foo')
    content = foo.pull('/local/share/config.yaml').read()
```

then `content` would be the contents of our locally-supplied `file.txt`. You can use `tempfile` for
nicely wrapping data and passing it to the charm via the container.

### Check files written in the container

`container.push` works similarly to `container.pull`. To check that the charm has pushed the expected data to the container, write a test like:

```python
import tempfile

class MyCharm(ops.CharmBase):
    def __init__(self, framework):
        super().__init__(framework)
        framework.observe(self.on.foo_pebble_ready, self._on_pebble_ready)

    def _on_pebble_ready(self, _):
        foo = self.unit.get_container('foo')
        foo.push('/local/share/config.yaml', 'TEST', make_dirs=True)

def test_pebble_push():
    with tempfile.NamedTemporaryFile() as local_file:
        container = testing.Container(
            name='foo',
            can_connect=True,
            mounts={'local': testing.Mount(location='/local/share/config.yaml', source=local_file.name)}
        )
        state_in = testing.State(containers={container})
        ctx = testing.Context(
            MyCharm,
            meta={'name': 'foo', 'containers': {'foo': {}}}
        )
        ctx.run(
            ctx.on.pebble_ready(container),
            state_in,
        )
        assert local_file.read().decode() == 'TEST'
```

If the charm writes files to a container (to a location you didn't mount as a temporary folder you
have access to), you will be able to inspect them using `get_filesystem`.

```python
class MyCharm(ops.CharmBase):
    def __init__(self, framework):
        super().__init__(framework)
        framework.observe(self.on.foo_pebble_ready, self._on_pebble_ready)

    def _on_pebble_ready(self, _):
        foo = self.unit.get_container('foo')
        foo.push('/local/share/config.yaml', 'TEST', make_dirs=True)


def test_pebble_push():
    container = testing.Container(name='foo', can_connect=True)
    state_in = testing.State(containers={container})
    ctx = testing.Context(
        MyCharm,
        meta={'name': 'foo', 'containers': {'foo': {}}}
    )

    state_out = ctx.run(ctx.on.start(), state_in)

    # This is the root of the simulated container filesystem. Any mounts will be symlinks in it.
    container_root_fs = state_out.get_container(container.name).get_filesystem(ctx)
    cfg_file = container_root_fs / 'local' / 'share' / 'config.yaml'
    assert cfg_file.read_text() == 'TEST'
```
