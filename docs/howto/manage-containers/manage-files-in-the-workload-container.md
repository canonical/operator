(files-in-containers)=
# How to manage files in the workload container

Pebble's files API allows charm authors to read and write files on the workload container. You can write files ("push"), read files ("pull"), list files in a directory, make directories, and delete files or directories.

## Push

Probably the most useful operation is [`Container.push`](ops.Container.push), which allows you to write a file to the workload, for example, a PostgreSQL configuration file. You can use `push` as follows (note that this code would be inside a charm event handler):

```python
config = """
port = 7777
max_connections = 1000
"""
container.push('/etc/pg/postgresql.conf', config, make_dirs=True)
```

The `make_dirs=True` flag tells `push` to create the intermediate directories if they don't already exist (`/etc/pg` in this case).

There are many additional features, including the ability to send raw bytes (by providing a Python `bytes` object as the second argument) and write data from a file-like object. You can also specify permissions and the user and group for the file. See the [API documentation](ops.Container.push) for details.

## Pull

To read a file from the workload, use [`Container.pull`](ops.Container.pull), which returns a file-like object that you can `read()`.

The files API doesn't currently support update, so to update a file you can use `pull` to perform a read-modify-write operation, for example:

```python
# Update port to 8888 and restart service
config = container.pull('/etc/pg/postgresql.conf').read()
if 'port =' not in config:
    config += '\nport = 8888\n'
container.push('/etc/pg/postgresql.conf', config)
container.restart('postgresql')
```

If you specify the keyword argument `encoding=None` on the `pull()` call, reads from the returned file-like object will return `bytes`. The default is `encoding='utf-8'`, which will decode the file's bytes from UTF-8 so that reads return a Python `str`.

## Push recursive

To copy several files to the workload, use [`Container.push_path`](ops.Container.push_path), which copies files recursively into a specified destination directory.  The API docs contain detailed examples of source and destination semantics and path handling.

```python
# copy "/source/dir/[files]" into "/destination/dir/[files]"
container.push_path('/source/dir', '/destination')

# copy "/source/dir/[files]" into "/destination/[files]"
container.push_path('/source/dir/*', '/destination')
```

A trailing "/*" on the source directory is the only supported globbing/matching.

## Pull recursive

To copy several files to the workload, use [`Container.pull_path`](ops.Container.pull_path), which copies files recursively into a specified destination directory.  The API docs contain detailed examples of source and destination semantics and path handling.

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

To create a directory, use [`Container.make_dir`](ops.Container.make_dir). It takes an optional `make_parents=True` argument (like `mkdir -p`), as well as optional permissions and user/group arguments. Some examples:

```python
container.make_dir('/etc/pg', user='postgres', group='postgres')
container.make_dir('/some/other/nested/dir', make_parents=True)
```

## Remove path

To delete a file or directory, use [`Container.remove_path`](ops.Container.remove_path). If a directory is specified, it must be empty unless `recursive=True` is specified, in which case the entire directory tree is deleted, recursively (like `rm -r`). For example:

```python
# Delete Apache access log
container.remove_path('/var/log/apache/access.log')
# Blow away /tmp/mysubdir and all files under it
container.remove_path('/tmp/mysubdir', recursive=True)
```

## Check file and directory existence

To check if a path exists you can use [`Container.exists`](ops.Container.exists) for directories or files and [`Container.isdir`](ops.Container.isdir) for directories.  These functions are analogous to python's `os.path.isdir` and `os.path.exists` functions.  For example:

```python
# if /tmp/myfile exists
container.exists('/tmp/myfile') # True
container.isdir('/tmp/myfile') # False

# if /tmp/mydir exists
container.exists('/tmp/mydir') # True
container.isdir('/tmp/mydir') # True
```

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
