# Scenario

[**Read the online documentation.**](https://ops.readthedocs.io/en/latest/reference/ops-testing.html)


## Statuses

One of the simplest types of black-box testing available to charmers is to execute the charm and verify that the charm
sets the expected unit/application status. We have seen a simple example above including leadership. But what if the
charm transitions through a sequence of statuses?

```python
# charm code:
def _on_event(self, _event):
    self.unit.status = ops.MaintenanceStatus('determining who the ruler is...')
    try:
        if self._call_that_takes_a_few_seconds_and_only_passes_on_leadership():
            self.unit.status = ops.ActiveStatus('I rule')
        else:
            self.unit.status = ops.WaitingStatus('checking this is right...')
            self._check_that_takes_some_more_time()
            self.unit.status = ops.ActiveStatus('I am ruled')
    except:
        self.unit.status = ops.BlockedStatus('something went wrong')
```

More broadly, often we want to test 'side effects' of executing a charm, such as what events have been emitted, what
statuses it went through, etc... Before we get there, we have to explain what the `Context` represents, and its
relationship with the `State`.

## Networks

Simplifying a bit the Juju "spaces" model, each relation endpoint a charm defines in its metadata is associated with a network. Regardless of whether there is a living relation over that endpoint, that is.  

If your charm has a relation `"foo"` (defined in its metadata), then the charm will be able at runtime to do `self.model.get_binding("foo").network`.
The network you'll get by doing so is heavily defaulted (see `state.Network`) and good for most use-cases because the charm should typically not be concerned about what IP it gets. 

On top of the relation-provided network bindings, a charm can also define some `extra-bindings` in its metadata and access them at runtime. Note that this is a deprecated feature that should not be relied upon. For completeness, we support it in Scenario.

If you want to, you can override any of these relation or extra-binding associated networks with a custom one by passing it to `State.networks`.

```python
state = scenario.State(networks={
  scenario.Network("foo", [scenario.BindAddress([scenario.Address('192.0.2.1')])])
})
```

Where `foo` can either be the name of an `extra-bindings`-defined binding, or a relation endpoint.

## Containers

When testing a Kubernetes charm, you can mock container interactions. When using the null state (`State()`), there will
be no containers. So if the charm were to `self.unit.containers`, it would get back an empty dict.

To give the charm access to some containers, you need to pass them to the input state, like so:
`State(containers={...})`

An example of a state including some containers:

```python
state = scenario.State(containers={
    scenario.Container(name="foo", can_connect=True),
    scenario.Container(name="bar", can_connect=False)
})
```

In this case, `self.unit.get_container('foo').can_connect()` would return `True`, while for 'bar' it would give `False`.

### Container filesystem setup

You can configure a container to have some files in it:

```python
import pathlib

local_file = pathlib.Path('/path/to/local/real/file.txt')

container = scenario.Container(
    name="foo",
    can_connect=True,
    mounts={'local': scenario.Mount(location='/local/share/config.yaml', source=local_file)}
    )
state = scenario.State(containers={container})
```

In this case, if the charm were to:

```python
def _on_start(self, _):
    foo = self.unit.get_container('foo')
    content = foo.pull('/local/share/config.yaml').read()
```

then `content` would be the contents of our locally-supplied `file.txt`. You can use `tempfile` for nicely wrapping
data and passing it to the charm via the container.

`container.push` works similarly, so you can write a test like:

```python
import tempfile


class MyCharm(ops.CharmBase):
    def __init__(self, framework):
        super().__init__(framework)
        framework.observe(self.on.foo_pebble_ready, self._on_pebble_ready)

    def _on_pebble_ready(self, _):
        foo = self.unit.get_container('foo')
        foo.push('/local/share/config.yaml', "TEST", make_dirs=True)


def test_pebble_push():
    with tempfile.NamedTemporaryFile() as local_file:
        container = scenario.Container(
            name='foo',
            can_connect=True,
            mounts={'local': Mount(location='/local/share/config.yaml', source=local_file.name)}
        )
        state_in = State(containers={container})
        ctx = Context(
            MyCharm,
            meta={"name": "foo", "containers": {"foo": {}}}
        )
        ctx.run(
            ctx.on.pebble_ready(container),
            state_in,
        )
        assert local_file.read().decode() == "TEST"
```

`container.pebble_ready_event` is syntactic sugar for: `Event("foo-pebble-ready", container=container)`. The reason we
need to associate the container with the event is that the Framework uses an envvar to determine which container the
pebble-ready event is about (it does not use the event name). Scenario needs that information, similarly, for injecting
that envvar into the charm's runtime.

### Container filesystem post-mortem

If the charm writes files to a container (to a location you didn't Mount as a temporary folder you have access to), you will be able to inspect them using the `get_filesystem` api.

```python
class MyCharm(ops.CharmBase):
    def __init__(self, framework):
        super().__init__(framework)
        framework.observe(self.on.foo_pebble_ready, self._on_pebble_ready)

    def _on_pebble_ready(self, _):
        foo = self.unit.get_container('foo')
        foo.push('/local/share/config.yaml', "TEST", make_dirs=True)


def test_pebble_push():
    container = scenario.Container(name='foo', can_connect=True)
    state_in = scenario.State(containers={container})
    ctx = scenario.Context(
        MyCharm,
        meta={"name": "foo", "containers": {"foo": {}}}
    )
    
    ctx.run(ctx.on.start(), state_in)

    # This is the root of the simulated container filesystem. Any mounts will be symlinks in it.
    container_root_fs = container.get_filesystem(ctx)
    cfg_file = container_root_fs / 'local' / 'share' / 'config.yaml'
    assert cfg_file.read_text() == "TEST"
```

### `Container.exec` mocks

`container.exec` is a tad more complicated, but if you get to this low a level of simulation, you probably will have far
worse issues to deal with. You need to specify, for each possible command the charm might run on the container, what the
result of that would be: its return code, what will be written to stdout/stderr.

```python
LS_LL = """
.rw-rw-r--  228 ubuntu ubuntu 18 jan 12:05 -- charmcraft.yaml
.rw-rw-r--  497 ubuntu ubuntu 18 jan 12:05 -- config.yaml
.rw-rw-r--  900 ubuntu ubuntu 18 jan 12:05 -- CONTRIBUTING.md
drwxrwxr-x    - ubuntu ubuntu 18 jan 12:06 -- lib
"""


class MyCharm(ops.CharmBase):
    def _on_start(self, _):
        foo = self.unit.get_container('foo')
        proc = foo.exec(['ls', '-ll'])
        proc.stdin.write("...")
        stdout, _ = proc.wait_output()
        assert stdout == LS_LL


def test_pebble_exec():
    container = scenario.Container(
        name='foo',
        execs={
            scenario.Exec(
                command_prefix=['ls'],
                return_code=0,
                stdout=LS_LL,
            ),
        }
    )
    state_in = scenario.State(containers={container})
    ctx = scenario.Context(
        MyCharm,
        meta={"name": "foo", "containers": {"foo": {}}},
    )
    state_out = ctx.run(
        ctx.on.pebble_ready(container),
        state_in,
    )
    assert ctx.exec_history[container.name][0].command == ['ls', '-ll']
    assert ctx.exec_history[container.name][0].stdin == "..."
```

Scenario will attempt to find the right `Exec` object by matching the provided
command prefix against the command used in the ops `container.exec()` call. For
example if the command is `['ls', '-ll']` then the searching will be:

 1. an `Exec` with exactly the same as command prefix, `('ls', '-ll')`
 2. an `Exec` with the command prefix `('ls', )`
 3. an `Exec` with the command prefix `()`

If none of these are found Scenario will raise an `ExecError`.

### Pebble Notices

Pebble can generate notices, which Juju will detect, and wake up the charm to
let it know that something has happened in the container. The most common
use-case is Pebble custom notices, which is a mechanism for the workload
application to trigger a charm event.

When the charm is notified, there might be a queue of existing notices, or just
the one that has triggered the event:

```python
class MyCharm(ops.CharmBase):
    def __init__(self, framework):
        super().__init__(framework)
        framework.observe(self.on["my-container"].pebble_custom_notice, self._on_notice)

    def _on_notice(self, event):
        event.notice.key  # == "example.com/c"
        for notice in self.unit.get_container("my-container").get_notices():
            ...

ctx = scenario.Context(MyCharm, meta={"name": "foo", "containers": {"my-container": {}}})
notices = [
    scenario.Notice(key="example.com/a", occurrences=10),
    scenario.Notice(key="example.com/b", last_data={"bar": "baz"}),
    scenario.Notice(key="example.com/c"),
]
container = scenario.Container("my-container", notices=notices)
state = scenario.State(containers={container})
ctx.run(ctx.on.pebble_custom_notice(container=container, notice=notices[-1]), state)
```

### Pebble Checks

A Pebble plan can contain checks, and when those checks exceed the configured
failure threshold, or start succeeding again after, Juju will emit a
pebble-check-failed or pebble-check-recovered event. In order to simulate these
events, you need to add a `CheckInfo` to the container. Note that the status of the
check doesn't have to match the event being generated: by the time that Juju
sends a pebble-check-failed event the check might have started passing again.

```python
from ops import pebble

ctx = scenario.Context(MyCharm, meta={"name": "foo", "containers": {"my_container": {}}})
layer = pebble.Layer({
    "checks": {"http-check": {"override": "replace", "startup": "enabled", "failures": 7}},
})
check_info = scenario.CheckInfo(
    "http-check",
    status=pebble.CheckStatus.UP,
    level=layer.checks["http-check"].level,
    startup=layer.checks["http-check"].startup,
    threshold=layer.checks["http-check"].threshold,
)
container = scenario.Container("my_container", check_infos={check_info}, layers={"layer1": layer})
state = scenario.State(containers={container})
ctx.run(ctx.on.pebble_check_failed(info=check_info, container=container), state=state)
```

# Deferred events

Scenario allows you to accurately simulate the Operator Framework's event queue. The event queue is responsible for
keeping track of the deferred events. On the input side, you can verify that if the charm triggers with this and that
event in its queue (they would be there because they had been deferred in the previous run), then the output state is
valid. You generate the deferred data structure using the event's `deferred()` method:

```python
class MyCharm(ops.CharmBase):
    ...

    def _on_update_status(self, event):
        event.defer()

    def _on_start(self, event):
        event.defer()


def test_start_on_deferred_update_status():
    """Test charm execution if a 'start' is dispatched when in the previous run an update-status had been deferred."""
    ctx = scenario.Context(MyCharm)
    state_in = scenario.State(
        deferred=[
            ctx.on.update_status().deferred(handler=MyCharm._on_update_status)
        ]
    )
    state_out = ctx.run(ctx.on.start(), state_in)
    assert len(state_out.deferred) == 1
    assert state_out.deferred[0].name == 'start'
```

On the output side, you can verify that an event that you expect to have been deferred during this trigger, has indeed
been deferred.

```python
class MyCharm(ops.CharmBase):
    ...

    def _on_start(self, event):
        event.defer()


def test_defer(MyCharm):
    out = scenario.Context(MyCharm).run(ctx.on.start(), scenario.State())
    assert len(out.deferred) == 1
    assert out.deferred[0].name == 'start'
```

# Live charm introspection

Scenario is a black-box, state-transition testing framework. It makes it trivial to assert that a status went from A to
B, but not to assert that, in the context of this charm execution, with this state, a certain charm-internal method was called and returned a
given piece of data, or would return this and that _if_ it had been called.

The Scenario `Context` object can be used as a context manager for this use case specifically:

```python notest
from charms.bar.lib_name.v1.charm_lib import CharmLib


class MyCharm(ops.CharmBase):
    META = {"name": "mycharm"}
    _stored = ops.StoredState()
    
    def __init__(self, framework):
        super().__init__(framework)
        self._stored.set_default(a="a")
        self.my_charm_lib = CharmLib()
        framework.observe(self.on.start, self._on_start)

    def _on_start(self, event):
        self._stored.a = "b"


def test_live_charm_introspection(mycharm):
    ctx = scenario.Context(mycharm, meta=mycharm.META)
    with ctx(ctx.on.start(), scenario.State()) as manager:
        # This is your charm instance, after ops has set it up:
        charm: MyCharm = manager.charm
        
        # We can check attributes on nested Objects or the charm itself:
        assert charm.my_charm_lib.foo == "foo"
        # such as stored state:
        assert charm._stored.a == "a"

        # This will tell ops.main to proceed with normal execution and emit the "start" event on the charm:
        state_out = manager.run()
    
        # After that is done, we are handed back control, and we can again do some introspection:
        assert charm.my_charm_lib.foo == "bar"
        # and check that the charm's internal state is as we expect:
        assert charm._stored.a == "b"

    # state_out is, as in regular scenario tests, a State object you can assert on:
    assert state_out.unit_status == ...
```

Note that you can't call `manager.run()` multiple times: the object is a context that ensures that `ops.main` 'pauses' right
before emitting the event to hand you some introspection hooks, but for the rest this is a regular Scenario test: you
can't emit multiple events in a single charm execution.

# The virtual charm root

Before executing the charm, Scenario copies the charm's `/src`, any libs, the metadata, config, and actions `yaml`s to a temporary directory. The
charm will see that temporary directory as its 'root'. This allows us to keep things simple when dealing with metadata that can be
either inferred from the charm type being passed to `Context` or be passed to it as an argument, thereby overriding
the inferred one. This also allows you to test charms defined on the fly, as in:

```python
class MyCharmType(ops.CharmBase):
    pass


ctx = scenario.Context(charm_type=MyCharmType, meta={'name': 'my-charm-name'})
ctx.run(ctx.on.start(), scenario.State())
```

A consequence of this fact is that you have no direct control over the temporary directory that we are creating to put the metadata
you are passing to `.run()` (because `ops` expects it to be a file...). That is, unless you pass your own:

```python
import tempfile


class MyCharmType(ops.CharmBase):
    pass


td = tempfile.TemporaryDirectory()
ctx = scenario.Context(
    charm_type=MyCharmType,
    meta={'name': 'my-charm-name'},
    charm_root=td.name
)
state = ctx.run(ctx.on.start(), scenario.State())
```

Do this, and you will be able to set up said directory as you like before the charm is run, as well as verify its
contents after the charm has run. Do keep in mind that any metadata files you create in it will be overwritten by Scenario, and therefore
ignored, if you pass any metadata keys to `Context`. Omit `meta` in the call
above, and Scenario will instead attempt to read metadata from the
temporary directory.
