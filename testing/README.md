# Scenario

[![Build](https://github.com/canonical/ops-scenario/actions/workflows/build_wheels.yaml/badge.svg)](https://github.com/canonical/ops-scenario/actions/workflows/build_wheels.yaml)
[![QC](https://github.com/canonical/ops-scenario/actions/workflows/quality_checks.yaml/badge.svg?event=pull_request)](https://github.com/canonical/ops-scenario/actions/workflows/quality_checks.yaml?event=pull_request)
[![Discourse Status](https://img.shields.io/discourse/status?server=https%3A%2F%2Fdiscourse.charmhub.io&style=flat&label=CharmHub%20Discourse)](https://discourse.charmhub.io)
[![foo](https://img.shields.io/badge/everything-charming-blueviolet)](https://github.com/PietroPasotti/jhack)
[![Awesome](https://cdn.rawgit.com/sindresorhus/awesome/d7305f38d29fed78fa85652e3a63e154dd8e8829/media/badge.svg)](https://discourse.charmhub.io/t/rethinking-charm-testing-with-ops-scenario/8649)
[![Python >= 3.8](https://img.shields.io/badge/python-3.8-blue.svg)](https://www.python.org/downloads/release/python-380/)

Scenario is a state-transition testing SDK for Operator Framework charms.

Where the Harness enables you to procedurally mock pieces of the state the charm needs to function, Scenario tests allow
you to declaratively define the state all at once, and use it as a sort of context against which you can fire a single
event on the charm and execute its logic.

This puts scenario tests somewhere in between unit and integration tests: some say 'functional', some say 'contract', I prefer 'state-transition'.

Scenario tests nudge you into thinking of a charm as an input->output function. The input is the
union of an `Event` (why am I, charm, being executed), a `State` (am I leader? what is my relation data? what is my
config?...) and the charm's execution `Context` (what relations can I have? what containers can I have?...). The output is another `State`: the state after the charm has had a chance to interact with the
mocked Juju model and affect the initial state back.

![state transition model depiction](https://raw.githubusercontent.com/canonical/ops-scenario/main/resources/state-transition-model.png)

For example: a charm currently in `unknown` status is executed with a `start` event, and based on whether it has leadership or not (according to its input state), it will decide to set `active` or `blocked` status (which will be reflected in the output state).

Scenario-testing a charm, then, means verifying that:

- the charm does not raise uncaught exceptions while handling the event
- the output state (or the diff with the input state) is as expected.

## Core concepts as a metaphor

I like metaphors, so here we go:

- There is a theatre stage.
- You pick an actor (a Charm) to put on the stage. Not just any actor: an improv one.
- You arrange the stage with content that the actor will have to interact with. This consists of selecting:
    - An initial situation (`State`) in which the actor is, e.g. is the actor the main role or an NPC (`is_leader`), or what
      other actors are there around it, what is written in those pebble-shaped books on the table?
    - Something that has just happened (an `Event`) and to which the actor has to react (e.g. one of the NPCs leaves the
      stage (`relation-departed`), or the content of one of the books changes).
- How the actor will react to the event will have an impact on the context: e.g. the actor might knock over a table (a
  container), or write something down into one of the books.

## Core concepts not as a metaphor

Scenario tests are about running assertions on atomic state transitions treating the charm being tested like a black
box. An initial state goes in, an event occurs (say, `'start'`) and a new state comes out. Scenario tests are about
validating the transition, that is, consistency-checking the delta between the two states, and verifying the charm
author's expectations.

Comparing scenario tests with `Harness` tests:

- Harness exposes an imperative API: the user is expected to call methods on the Harness driving it to the desired
  state, then verify its validity by calling charm methods or inspecting the raw data. In contrast, Scenario is declarative. You fully specify an initial state, an execution context and an event, then you run the charm and inspect the results.
- Harness instantiates the charm once, then allows you to fire multiple events on the charm, which is breeding ground
  for subtle bugs. Scenario tests are centered around testing single state transitions, that is, one event at a time.
  This ensures that the execution environment is as clean as possible (for a unit test).
- Harness maintains a model of the Juju Model, which is a maintenance burden and adds complexity. Scenario mocks at the
  level of hook tools and stores all mocking data in a monolithic data structure (the State), which makes it more
  lightweight and portable.

# Writing scenario tests

A scenario test consists of three broad steps:

- **Arrange**:
    - declare the context 
    - declare the input state
    - select an event to fire
- **Act**:
    - run the context (i.e. obtain the output state, given the input state and the event)
- **Assert**:
    - verify that the output state (or the delta with the input state) is how you expect it to be
    - verify that the charm has seen a certain sequence of statuses, events, and `juju-log` calls
    - optionally, you can use a context manager to get a hold of the charm instance and run assertions on internal APIs and the internal state of the charm and operator framework.

The most basic scenario is one in which all is defaulted and barely any data is
available. The charm has no config, no relations, no leadership, and its status is `unknown`.

With that, we can write the simplest possible scenario test:

```python
def test_scenario_base():
    ctx = scenario.Context(MyCharm, meta={"name": "foo"})
    out = ctx.run(ctx.on.start(), scenario.State())
    assert out.unit_status == scenario.UnknownStatus()
```

Note that you should always compare the app and unit status using `==`, not `is`. You can compare
them to either the `scenario` objects, or the `ops` ones.

Now let's start making it more complicated. Our charm sets a special state if it has leadership on 'start':

```python
import pytest


class MyCharm(ops.CharmBase):
    def __init__(self, framework):
        super().__init__(framework)
        framework.observe(self.on.start, self._on_start)

    def _on_start(self, _):
        if self.unit.is_leader():
            self.unit.status = ops.ActiveStatus('I rule')
        else:
            self.unit.status = ops.ActiveStatus('I am ruled')


@pytest.mark.parametrize('leader', (True, False))
def test_status_leader(leader):
    ctx = scenario.Context(MyCharm, meta={"name": "foo"})
    out = ctx.run(ctx.on.start(), scenario.State(leader=leader))
    assert out.unit_status == scenario.ActiveStatus('I rule' if leader else 'I am ruled')
```

By defining the right state we can programmatically define what answers will the charm get to all the questions it can
ask the Juju model: am I leader? What are my relations? What is the remote unit I'm talking to? etc...

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

## Context and State

Consider the following tests. Suppose we want to verify that while handling a given top-level Juju event:

- a specific chain of (custom) events was emitted on the charm
- the charm `juju-log`ged these specific strings
- the charm went through this sequence of app/unit statuses (e.g. `maintenance`, then `waiting`, then `active`)

These types of test have a place in Scenario, but that is not State: the contents of the Juju log or the status history
are side effects of executing a charm, but are not persisted in a charm-accessible "state" in any meaningful way.
In other words: those data streams are, from the charm's perspective, write-only.

As such, they do not belong in `scenario.State` but in `scenario.Context`: the object representing the charm's execution
context.

## Status history

You can verify that the charm has followed the expected path by checking the unit/app status history like so:

```python
def test_statuses():
    ctx = scenario.Context(MyCharm, meta={"name": "foo"})
    out = ctx.run(ctx.on.start(), scenario.State(leader=False))
    assert ctx.unit_status_history == [
        scenario.UnknownStatus(),
        scenario.MaintenanceStatus('determining who the ruler is...'),
        scenario.WaitingStatus('checking this is right...'),
    ]
    assert out.unit_status == scenario.ActiveStatus("I am ruled")
    
    # similarly you can check the app status history:
    assert ctx.app_status_history == [
        scenario.UnknownStatus(),
        ...
    ]
```

Note that the *current* status is **not** in the unit status history.

Also note that, unless you initialize the State with a preexisting status, the first status in the history will always
be `unknown`. That is because, so far as Scenario is concerned, each event is "the first event this charm has ever
seen".

If you want to simulate a situation in which the charm already has seen some event, and is in a status other than
Unknown (the default status every charm is born with), you will have to pass the 'initial status' to State.

```python
class MyCharm(ops.CharmBase):
    def __init__(self, framework):
        super().__init__(framework)
        framework.observe(self.on.start, self._on_start)

    def _on_start(self, event):
        self.model.unit.status = ops.ActiveStatus("foo")

# ...
ctx = scenario.Context(MyCharm, meta={"name": "foo"})
ctx.run(ctx.on.start(), scenario.State(unit_status=scenario.ActiveStatus('foo')))
assert ctx.unit_status_history == [
    scenario.ActiveStatus('foo'),  # now the first status is active: 'foo'!
    # ...
]
```

## Workload version history

Using a similar api to `*_status_history`, you can assert that the charm has set one or more workload versions during a
hook execution:

```python
# ...
ctx = scenario.Context(HistoryCharm, meta={"name": "foo"})
ctx.run(ctx.on.start(), scenario.State())
assert ctx.workload_version_history == ['1', '1.2', '1.5']
# ...
```

Note that the *current* version is not in the version history, as with the status history.

## Emitted events

If your charm deals with deferred events, custom events, and charm libs that in turn emit their own custom events, it
can be hard to examine the resulting control flow. In these situations it can be useful to verify that, as a result of a
given Juju event triggering (say, 'start'), a specific chain of events is emitted on the charm. The
resulting state, black-box as it is, gives little insight into how exactly it was obtained.

```python
def test_foo():
    ctx = scenario.Context(...)
    ctx.run(ctx.on.start(), ...)

    assert len(ctx.emitted_events) == 1
    assert isinstance(ctx.emitted_events[0], ops.StartEvent)
```

You can configure what events will be captured by passing the following arguments to `Context`:
-  `capture_deferred_events`: If you want to include re-emitted deferred events.
-  `capture_framework_events`: If you want to include framework events (`pre-commit`, `commit`, and `collect-status`). 

For example:
```python
def test_emitted_full():
    ctx = scenario.Context(
        MyCharm,
        capture_deferred_events=True,
        capture_framework_events=True,
    )
    ctx.run(ctx.on.start(), scenario.State(deferred=[ctx.on.update_status().deferred(MyCharm._foo)]))

    assert len(ctx.emitted_events) == 5
    assert [e.handle.kind for e in ctx.emitted_events] == [
        "update_status",
        "start",
        "collect_unit_status",
        "pre_commit",
        "commit",
    ]
```

## Relations

You can write scenario tests to verify the shape of relation data:

```python
# This charm copies over remote app data to local unit data
class MyCharm(ops.CharmBase):
    ...

    def _on_event(self, event):
        rel = event.relation
        assert rel.app.name == 'remote'
        assert rel.data[self.unit]['abc'] == 'foo'
        rel.data[self.unit]['abc'] = rel.data[event.app]['cde']


def test_relation_data():
    rel = scenario.Relation(
        endpoint="foo",
        interface="bar",
        remote_app_name="remote",
        local_unit_data={"abc": "foo"},
        remote_app_data={"cde": "baz!"},
    )
    state_in = scenario.State(relations={rel})
    ctx = scenario.Context(MyCharm, meta={"name": "foo"})

    state_out = ctx.run(ctx.on.start(), state_in)

    assert state_out.get_relation(rel.id).local_unit_data == {"abc": "baz!"}
    # You can do this to check that there are no other differences:
    assert state_out.relations == {
        scenario.Relation(
            endpoint="foo",
            interface="bar",
            remote_app_name="remote",
            local_unit_data={"abc": "baz!"},
            remote_app_data={"cde": "baz!"},
        ),
    }

# which is very idiomatic and superbly explicit.
```

The only mandatory argument to `Relation` (and other relation types, see below) is `endpoint`. The `interface` will be
derived from the charm's metadata. When fully defaulted, a relation is 'empty'. There are no remote units, the
remote application is called `'remote'` and only has a single unit `remote/0`, and nobody has written any data to the
databags yet.

That is typically the state of a relation when the first unit joins it.

When you use `Relation`, you are specifying a regular (conventional) relation. But that is not the only type of
relation. There are also peer relations and subordinate relations. While in the background the data model is the same,
the data access rules and the consistency constraints on them are very different. For example, it does not make sense
for a peer relation to have a different 'remote app' than its 'local app', because it's the same application.

### PeerRelation

To declare a peer relation, you should use `scenario.PeerRelation`. The core difference with regular relations is
that peer relations do not have a "remote app" (it's this app, in fact). So unlike `Relation`, a `PeerRelation` does not
have `remote_app_name` or `remote_app_data` arguments. Also, it talks in terms of `peers`:

- `Relation.remote_units_data` maps to `PeerRelation.peers_data`

```python
relation = scenario.PeerRelation(
    endpoint="peers",
    peers_data={1: {}, 2: {}, 42: {'foo': 'bar'}},
)
```

be mindful when using `PeerRelation` not to include **"this unit"**'s ID in `peers_data` or `peers_ids`, as that would
be flagged by the Consistency Checker:

```python
state_in = scenario.State(relations={
    scenario.PeerRelation(
        endpoint="peers",
        peers_data={1: {}, 2: {}, 42: {'foo': 'bar'}},
    )})

meta = {
    "name": "invalid",
    "peers": {
        "peers": {
            "interface": "foo",
        }
    }
}
ctx = scenario.Context(ops.CharmBase, meta=meta, unit_id=1)
ctx.run(ctx.on.start(), state_in)  # invalid: this unit's id cannot be the ID of a peer.
```

### SubordinateRelation

To declare a subordinate relation, you should use `scenario.SubordinateRelation`. The core difference with regular
relations is that subordinate relations always have exactly one remote unit (there is always exactly one remote unit
that this unit can see). 
Because of that, `SubordinateRelation`, compared to `Relation`, always talks in terms of `remote`:

- `Relation.remote_units_data` becomes `SubordinateRelation.remote_unit_data` taking a single `Dict[str:str]`. The remote unit ID can be provided as a separate argument. 
- `Relation.remote_unit_ids` becomes `SubordinateRelation.remote_unit_id` (a single ID instead of a list of IDs)
- `Relation.remote_units_data` becomes `SubordinateRelation.remote_unit_data` (a single databag instead of a mapping from unit IDs to databags)

```python
relation = scenario.SubordinateRelation(
    endpoint="peers",
    remote_unit_data={"foo": "bar"},
    remote_app_name="zookeeper",
    remote_unit_id=42
)
relation.remote_unit_name  # "zookeeper/42"
```

### Triggering Relation Events

If you want to trigger relation events, use `ctx.on.relation_changed` (and so
on for the other relation events) and pass the relation object:

```python
ctx = scenario.Context(MyCharm, meta=MyCharm.META)

relation = scenario.Relation(endpoint="foo", interface="bar")
changed_event = ctx.on.relation_changed(relation=relation)
joined_event = ctx.on.relation_joined(relation=relation)
# ...
```

The reason for this construction is that the event is associated with some relation-specific metadata, that Scenario
needs to set up the process that will run `ops.main` with the right environment variables.

### Additional event parameters

All relation events have some additional metadata that does not belong in the Relation object, such as, for a
relation-joined event, the name of the (remote) unit that is joining the relation. That is what determines what
`ops.model.Unit` you get when you get `RelationJoinedEvent().unit` in an event handler.

In order to supply this parameter, as well as the relation object, pass as `remote_unit` the id of the
remote unit that the event is about. The reason that this parameter is not supplied to `Relation` but to relation
events, is that the relation already ties 'this app' to some 'remote app' (cfr. the `Relation.remote_app_name` attr),
but not to a specific unit. What remote unit this event is about is not a `State` concern but an `Event` one.

```python
ctx = scenario.Context(MyCharm, meta=MyCharm.META)

relation = scenario.Relation(endpoint="foo", interface="bar")
remote_unit_2_is_joining_event = ctx.on.relation_joined(relation, remote_unit=2)
```

## Networks

Simplifying a bit the Juju "spaces" model, each integration endpoint a charm defines in its metadata is associated with a network. Regardless of whether there is a living relation over that endpoint, that is.  

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
ctx = scenario.Context(MyCharm, meta={"name": "foo", "containers": {"my_container": {}}})
check_info = scenario.CheckInfo("http-check", failures=7, status=ops.pebble.CheckStatus.DOWN)
container = scenario.Container("my_container", check_infos={check_info})
state = scenario.State(containers={container})
ctx.run(ctx.on.pebble_check_failed(info=check_info, container=container), state=state)
```

## Storage

If your charm defines `storage` in its metadata, you can use `scenario.Storage` to instruct Scenario to make (mocked) filesystem storage available to the charm at runtime.

Using the same `get_filesystem` API as `Container`, you can access the temporary directory used by Scenario to mock the filesystem root before and after the scenario runs.

```python
# Some charm with a 'foo' filesystem-type storage defined in its metadata:
ctx = scenario.Context(MyCharm, meta=MyCharm.META)
storage = scenario.Storage("foo")

# Setup storage with some content:
(storage.get_filesystem(ctx) / "myfile.txt").write_text("helloworld")

with ctx(ctx.on.update_status(), scenario.State(storages={storage})) as manager:
    foo = manager.charm.model.storages["foo"][0]
    loc = foo.location
    path = loc / "myfile.txt"
    assert path.exists()
    assert path.read_text() == "helloworld"

    myfile = loc / "path.py"
    myfile.write_text("helloworlds")

# post-mortem: inspect fs contents.
assert (
    storage.get_filesystem(ctx) / "path.py"
).read_text() == "helloworlds"
```

Note that State only wants to know about **attached** storages. A storage which is not attached to the charm can simply be omitted from State and the charm will be none the wiser.

### Storage-add

If a charm requests adding more storage instances while handling some event, you can inspect that from the `Context.requested_storage` API.

```python notest
# In MyCharm._on_foo:
# The charm requests two new "foo" storage instances to be provisioned:
self.model.storages.request("foo", 2)
```

From test code, you can inspect that:

```python notest
ctx = scenario.Context(MyCharm, meta=MyCharm.META)
ctx.run(ctx.on.some_event_that_will_cause_on_foo_to_be_called(), scenario.State())

# the charm has requested two 'foo' storages to be provisioned:
assert ctx.requested_storages['foo'] == 2
```

Requesting storages has no other consequence in Scenario. In real life, this request will trigger Juju to provision the storage and execute the charm again with `foo-storage-attached`.
So a natural follow-up Scenario test suite for this case would be:

```python
ctx = scenario.Context(MyCharm, meta=MyCharm.META)
foo_0 = scenario.Storage('foo')
# The charm is notified that one of the storages it has requested is ready:
ctx.run(ctx.on.storage_attached(foo_0), scenario.State(storages={foo_0}))

foo_1 = scenario.Storage('foo')
# The charm is notified that the other storage is also ready:
ctx.run(ctx.on.storage_attached(foo_1), scenario.State(storages={foo_0, foo_1}))
```

## Ports

Since `ops 2.6.0`, charms can invoke the `open-port`, `close-port`, and `opened-ports` hook tools to manage the ports opened on the host VM/container. Using the `State.opened_ports` API, you can: 

- simulate a charm run with a port opened by some previous execution
ctx = scenario.Context(MyCharm, meta=MyCharm.META)
ctx.run(ctx.on.start(), scenario.State(opened_ports={scenario.TCPPort(42)}))
```
- assert that a charm has called `open-port` or `close-port`:
```python
ctx = scenario.Context(PortCharm, meta=MyCharm.META)
state1 = ctx.run(ctx.on.start(), scenario.State())
assert state1.opened_ports == [scenario.TCPPort(42)]

state2 = ctx.run(ctx.on.stop(), state1)
assert state2.opened_ports == {}
```

## Secrets

Scenario has secrets. Here's how you use them.

```python
state = scenario.State(
    secrets={
        scenario.Secret(
            tracked_content={'key': 'public'},
            latest_content={'key': 'public', 'cert': 'private'},
        )
    }
)
```

The only mandatory arguments to Secret is the `tracked_content` dict: a `str:str`
mapping representing the content of the revision. If there is a newer revision
of the content than the one the unit that's handling the event is tracking, then
`latest_content` should also be provided - if it's not, then Scenario assumes
that `latest_content` is the `tracked_content`. If there are other revisions of
the content, simply don't include them: the unit has no way of knowing about
these.

There are three cases:
- the secret is owned by this app but not this unit, in which case this charm can only manage it if we are the leader
- the secret is owned by this unit, in which case this charm can always manage it (leader or not)
- (default) the secret is not owned by this app nor unit, which means we can't manage it but only view it (this includes user secrets)

Thus by default, the secret is not owned by **this charm**, but, implicitly, by some unknown 'other charm' (or a user), and that other has granted us view rights.

The presence of the secret in `State.secrets` entails that we have access to it, either as owners or as grantees. Therefore, if we're not owners, we must be grantees. Absence of a Secret from the known secrets list means we are not entitled to obtaining it in any way. The charm, indeed, shouldn't even know it exists.

[note]
If this charm does not own the secret, but also it was not granted view rights by the (remote) owner, you model this in Scenario by _not adding it to State.secrets_! The presence of a `Secret` in `State.secrets` means, in other words, that the charm has view rights (otherwise, why would we put it there?). If the charm owns the secret, or is leader, it will _also_ have manage rights on top of view ones.
[/note]

To specify a secret owned by this unit (or app):

```python
rel = scenario.Relation("web")
state = scenario.State(
    secrets={
        scenario.Secret(
            {'key': 'private'},
            owner='unit',  # or 'app'
            # The secret owner has granted access to the "remote" app over some relation:
            remote_grants={rel.id: {"remote"}}
        )
    }
)
```

To specify a secret owned by some other application, or a user secret, and give this unit (or app) access to it:

```python
state = scenario.State(
    secrets={
        scenario.Secret(
            {'key': 'public'},
            # owner=None, which is the default
        )
    }
)
```

When handling the `secret-expired` and `secret-remove` events, the charm must remove the specified revision of the secret. For `secret-remove`, the revision will no longer be in the `State`, because it's no longer in use (which is why the `secret-remove` event was triggered). To ensure that the charm is removing the secret, check the context for the history of secret removal:

```python
class SecretCharm(ops.CharmBase):
    def __init__(self, framework):
        super().__init__(framework)
        self.framework.observe(self.on.secret_remove, self._on_secret_remove)

    def _on_secret_remove(self, event):
        event.secret.remove_revision(event.revision)


ctx = scenario.Context(SecretCharm, meta={"name": "foo"})
secret = scenario.Secret({"password": "xxxxxxxx"}, owner="app")
old_revision = 42
state = ctx.run(
    ctx.on.secret_remove(secret, revision=old_revision),
    scenario.State(leader=True, secrets={secret})
)
assert ctx.removed_secret_revisions == [old_revision]
```

## StoredState

Scenario can simulate StoredState. You can define it on the input side as:

```python
class MyCharmType(ops.CharmBase):
    my_stored_state = ops.StoredState()

    def __init__(self, framework):
        super().__init__(framework)
        assert self.my_stored_state.foo == 'bar'  # this will pass!


state = scenario.State(stored_states={
    scenario.StoredState(
        owner_path="MyCharmType",
        name="my_stored_state",
        content={
            'foo': 'bar',
            'baz': {42: 42},
        }),
    },
)
```

And the charm's runtime will see `self.my_stored_state.foo` and `.baz` as expected. Also, you can run assertions on it on
the output side the same as any other bit of state.

## Resources

If your charm requires access to resources, you can make them available to it through `State.resources`.
From the perspective of a 'real' deployed charm, if your charm _has_ resources defined in its metadata, they _must_ be made available to the charm. That is a Juju-enforced constraint: you can't deploy a charm without attaching all resources it needs to it.
However, when testing, this constraint is unnecessarily strict (and it would also mean the great majority of all existing tests would break) since a charm will only notice that a resource is not available when it explicitly asks for it, which not many charms do.

So, the only consistency-level check we enforce in Scenario when it comes to resource is that if a resource is provided in State, it needs to have been declared in the metadata.

```python
import pathlib

ctx = scenario.Context(MyCharm, meta={'name': 'juliette', "resources": {"foo": {"type": "oci-image"}}})
resource = scenario.Resource(name='foo', path='/path/to/resource.tar')
with ctx(ctx.on.start(), scenario.State(resources={resource})) as manager:
    # If the charm, at runtime, were to call self.model.resources.fetch("foo"), it would get '/path/to/resource.tar' back.
    path = manager.charm.model.resources.fetch('foo')
    assert path == pathlib.Path('/path/to/resource.tar')
```

## Model

Charms don't usually need to be aware of the model in which they are deployed,
but if you need to set the model name or UUID, you can provide a `scenario.Model`
to the state:

```python
ctx = scenario.Context(MyCharm, meta={"name": "foo"})
state_in = scenario.State(model=scenario.Model(name="my-model"))
out = ctx.run(ctx.on.start(), state_in)
assert out.model.name == "my-model"
assert out.model.uuid == state_in.model.uuid
```

### CloudSpec

You can set CloudSpec information in the model (only `type` and `name` are required).

Example:

```python
import scenario

cloud_spec=scenario.CloudSpec(
    type="lxd",
    endpoint="https://127.0.0.1:8443",
    credential=scenario.CloudCredential(
        auth_type="clientcertificate",
        attributes={
            "client-cert": "foo",
            "client-key": "bar",
            "server-cert": "baz",
        },
    ),
)
state = scenario.State(
    model=scenario.Model(name="my-vm-model", type="lxd", cloud_spec=cloud_spec),
)
```

Then you can access it by `Model.get_cloud_spec()`:

```python
# charm.py
class MyVMCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on.start, self._on_start)

    def _on_start(self, event: ops.StartEvent):
        self.cloud_spec = self.model.get_cloud_spec()
```

# Actions

An action is a special sort of event, even though `ops` handles them almost identically.
In most cases, you'll want to inspect the 'results' of an action, or whether it has failed or
logged something while executing. Many actions don't have a direct effect on the output state.

How to test actions with scenario:

## Actions without parameters

```python
def test_backup_action():
    ctx = scenario.Context(MyCharm)

    # If you didn't declare do_backup in the charm's metadata, 
    # the `ConsistencyChecker` will slap you on the wrist and refuse to proceed.
    state = ctx.run(ctx.on.action("do_backup"), scenario.State())

    # You can assert on action results and logs using the context:
    assert ctx.action_logs == ['baz', 'qux']
    assert ctx.action_results == {'foo': 'bar'}
```

## Failing Actions

If the charm code calls `event.fail()` to indicate that the action has failed,
an `ActionFailed` exception will be raised. This avoids having to include
success checks in every test where the action is successful.

```python
def test_backup_action_failed():
    ctx = scenario.Context(MyCharm)

    with pytest.raises(ActionFailed) as exc_info:
        ctx.run(ctx.on.action("do_backup"), scenario.State())
    assert exc_info.value.message == "sorry, couldn't do the backup"
    # The state is also available if that's required:
    assert exc_info.value.state.get_container(...)

    # You can still assert action results and logs that occurred as well as the failure:
    assert ctx.action_logs == ['baz', 'qux']
    assert ctx.action_results == {'foo': 'bar'}
```

## Parametrized Actions

If the action takes parameters, you can pass those in the call.

```python
def test_backup_action():
    ctx = scenario.Context(MyCharm)

    # If the parameters (or their type) don't match what is declared in the metadata, 
    # the `ConsistencyChecker` will slap you on the other wrist.
    state = ctx.run(
        ctx.on.action("do_backup", params={'a': 'b'}),
        scenario.State()
    )

    # ...
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

# Immutability

All of the data structures in `state`, e.g. `State, Relation, Container`, etc... are implemented as frozen dataclasses.

This means that all components of the state that goes into a `context.run()` call are not mutated by the call, and the
state that you obtain in return is a different instance, and all parts of it have been (deep)copied.
This ensures that you can do delta-based comparison of states without worrying about them being mutated by Scenario.

If you want to modify any of these data structures, you will need to either reinstantiate it from scratch, or use
the dataclasses `replace` api.

```python
import dataclasses

relation = scenario.Relation('foo', remote_app_data={"1": "2"})
# make a copy of relation, but with remote_app_data set to {"3": "4"}
relation2 = dataclasses.replace(relation, remote_app_data={"3": "4"})
```

# Consistency checks

A Scenario, that is, the combination of an event, a state, and a charm, is consistent if it's plausible in JujuLand. For
example, Juju can't emit a `foo-relation-changed` event on your charm unless your charm has declared a `foo` relation
endpoint in its metadata. If that happens, that's a Juju bug. Scenario however assumes that Juju is bug-free,
therefore, so far as we're concerned, that can't happen, and therefore we help you verify that the scenarios you create
are consistent and raise an exception if that isn't so.

That happens automatically behind the scenes whenever you trigger an event;
`scenario._consistency_checker.check_consistency` is called and verifies that the scenario makes sense.

## Caveats:

- False positives: not all checks are implemented yet; more will come.
- False negatives: it is possible that a scenario you know to be consistent is seen as inconsistent. That is probably a
  bug in the consistency checker itself; please report it.
- Inherent limitations: if you have a custom event whose name conflicts with a builtin one, the consistency constraints
  of the builtin one will apply. For example: if you decide to name your custom event `bar-pebble-ready`, but you are
  working on a machine charm or don't have either way a `bar` container in your `metadata.yaml`, Scenario will flag that
  as inconsistent.

## Bypassing the checker

If you have a clear false negative, are explicitly testing 'edge', inconsistent situations, or for whatever reason the
checker is in your way, you can set the `SCENARIO_SKIP_CONSISTENCY_CHECKS` envvar and skip it altogether. Hopefully you
don't need that.

# Jhack integrations

Up until `v5.6.0`, Scenario shipped with a cli tool called `snapshot`, used to interact with a live charm's state.
The functionality [has been moved over to `jhack`](https://github.com/PietroPasotti/jhack/pull/111), 
to allow us to keep working on it independently, and to streamline 
the profile of Scenario itself as it becomes more broadly adopted and ready for widespread usage.
