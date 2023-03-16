Scenario
============

This is a state transition testing framework for Operator Framework charms.

Where the Harness enables you to procedurally mock pieces of the state the charm needs to function, Scenario tests allow
you to declaratively define the state all at once, and use it as a sort of context against which you can fire a single
event on the charm and execute its logic.

This puts scenario tests somewhere in between unit and integration tests.

Scenario tests nudge you into thinking of charms as an input->output function. Input is what we call a `Scene`: the
union of an `event` (why am I being executed) and a `context` (am I leader? what is my relation data? what is my
config?...).
The output is another context instance: the context after the charm has had a chance to interact with the mocked juju
model.

![state transition model depiction](resources/state-transition-model.png)

Scenario-testing a charm, then, means verifying that:

- the charm does not raise uncaught exceptions while handling the scene
- the output state (or the diff with the input state) is as expected.


# Core concepts as a metaphor
I like metaphors, so here we go:
- There is a theatre stage.
- You pick an actor (a Charm) to put on the stage. Not just any actor: an improv one.
- You arrange the stage with content that the actor will have to interact with. This consists of selecting:
    - An initial situation (State) in which the actor is, e.g. is the actor the main role or an NPC (is_leader), or what other actors are there around it, what is written in those pebble-shaped books on the table?
    - Something that has just happened (an Event) and to which the actor has to react (e.g. one of the NPCs leaves the stage (relation-departed), or the content of one of the books changes).
- How the actor will react to the event will have an impact on the context: e.g. the actor might knock over a table (a container), or write something down into one of the books.


# Core concepts not as a metaphor
Scenario tests are about running assertions on atomic state transitions treating the charm being tested like a black box.
An initial state goes in, an event occurs (say, `'start'`) and a new state comes out.
Scenario tests are about validating the transition, that is, consistency-checking the delta between the two states, and verifying the charm author's expectations.

Comparing scenario tests with `Harness` tests:
- Harness exposes an imperative API: the user is expected to call methods on the Harness driving it to the desired state, then verify its validity by calling charm methods or inspecting the raw data.
- Harness instantiates the charm once, then allows you to fire multiple events on the charm, which is breeding ground for subtle bugs. Scenario tests are centered around testing single state transitions, that is, one event at a time. This ensures that the execution environment is as clean as possible (for a unit test).
- Harness maintains a model of the juju Model, which is a maintenance burden and adds complexity. Scenario mocks at the level of hook tools and stores all mocking data in a monolithic data structure (the State), which makes it more lightweight and portable.
- TODO: Scenario can mock at the level of hook tools. Decoupling charm and context allows us to swap out easily any part of this flow, and even share context data across charms, codebases, teams...

# Writing scenario tests
A scenario test consists of three broad steps:

- Arrange:
    - declare the input state
    - select an event to fire
- Act:
    - run the state (i.e. obtain the output state)
- Assert:
    - verify that the output state is how you expect it to be
    - verify that the delta with the input state is what you expect it to be

The most basic scenario is the so-called `null scenario`: one in which all is defaulted and barely any data is
available. The charm has no config, no relations, no networks, and no leadership.

With that, we can write the simplest possible scenario test:

```python
from scenario.state import State
from ops.charm import CharmBase
from ops.model import UnknownStatus

class MyCharm(CharmBase):
    pass


def test_scenario_base():
    out = State().trigger(
        'start', 
        MyCharm, meta={"name": "foo"})
    assert out.status.unit == UnknownStatus()
```

Now let's start making it more complicated.
Our charm sets a special state if it has leadership on 'start':

```python
import pytest
from scenario.state import State
from ops.charm import CharmBase
from ops.model import ActiveStatus


class MyCharm(CharmBase):
    def __init__(self, ...):
        self.framework.observe(self.on.start, self._on_start)

    def _on_start(self, _):
        if self.unit.is_leader():
            self.unit.status = ActiveStatus('I rule')
        else:
            self.unit.status = ActiveStatus('I am ruled')


@pytest.mark.parametrize('leader', (True, False))
def test_status_leader(leader):
    out = State(leader=leader).trigger(
        'start', 
        MyCharm,
        meta={"name": "foo"})
    assert out.status.unit == ActiveStatus('I rule' if leader else 'I am ruled')
```

By defining the right state we can programmatically define what answers will the charm get to all the questions it can ask the juju model: am I leader? What are my relations? What is the remote unit I'm talking to? etc...


## Statuses

One of the simplest types of black-box testing available to charmers is to execute the charm and verify that the charm sets the expected unit/application status.
We have seen a simple example above including leadership.
But what if the charm transitions through a sequence of statuses?

```python
from ops.model import MaintenanceStatus, ActiveStatus, WaitingStatus, BlockedStatus

# charm code:
def _on_event(self, _event):
    self.unit.status = MaintenanceStatus('determining who the ruler is...')
    try:
        if self._call_that_takes_a_few_seconds_and_only_passes_on_leadership:
            self.unit.status = ActiveStatus('I rule')
        else:
            self.unit.status = WaitingStatus('checking this is right...')
            self._check_that_takes_some_more_time()
            self.unit.status = ActiveStatus('I am ruled')
    except:
        self.unit.status = BlockedStatus('something went wrong')
```

You can verify that the charm has followed the expected path by checking the **unit status history** like so:

```python
from ops.model import MaintenanceStatus, ActiveStatus, WaitingStatus, UnknownStatus
from scenario import State

def test_statuses():
    out = State(leader=False).trigger(
        'start', 
        MyCharm,
        meta={"name": "foo"})
    assert out.status.unit_history == [
      UnknownStatus(),
      MaintenanceStatus('determining who the ruler is...'),
      WaitingStatus('checking this is right...'),
      ActiveStatus('I am ruled')
    ]
```

Note that, unless you initialize the State with a preexisting status, the first status in the history will always be `unknown`. That is because, so far as scenario is concerned, each event is "the first event this charm has ever seen".

If you want to simulate a situation in which the charm already has seen some event, and is in a status other than Unknown (the default status every charm is born with), you will have to pass the 'initial status' in State.

```python
from ops.model import ActiveStatus
from scenario import State, Status
State(leader=False, status=Status(unit=ActiveStatus('foo')))
```


## Relations

You can write scenario tests to verify the shape of relation data:

```python
from ops.charm import CharmBase

from scenario.state import Relation, State


# This charm copies over remote app data to local unit data
class MyCharm(CharmBase):
    ...

    def _on_event(self, e):
        rel = e.relation
        assert rel.app.name == 'remote'
        assert rel.data[self.unit]['abc'] == 'foo'
        rel.data[self.unit]['abc'] = rel.data[e.app]['cde']


def test_relation_data():
    out = State(relations=[
        Relation(
            endpoint="foo",
            interface="bar",
            remote_app_name="remote",
            local_unit_data={"abc": "foo"},
            remote_app_data={"cde": "baz!"},
        ),
    ]
    ).trigger("start", MyCharm, meta={"name": "foo"})

    assert out.relations[0].local_unit_data == {"abc": "baz!"}
    # you can do this to check that there are no other differences:
    assert out.relations == [
        Relation(
            endpoint="foo",
            interface="bar",
            remote_app_name="remote",
            local_unit_data={"abc": "baz!"},
            remote_app_data={"cde": "baz!"},
        ),
    ]

# which is very idiomatic and superbly explicit. Noice.
```

## Containers

When testing a kubernetes charm, you can mock container interactions.
When using the null state (`State()`), there will be no containers. So if the charm were to `self.unit.containers`, it would get back an empty dict.

To give the charm access to some containers, you need to pass them to the input state, like so:
`State(containers=[...])`

An example of a scene including some containers:
```python
from scenario.state import Container, State
state = State(containers=[
    Container(name="foo", can_connect=True),
    Container(name="bar", can_connect=False)
])
```

In this case, `self.unit.get_container('foo').can_connect()` would return `True`, while for 'bar' it would give `False`.

You can configure a container to have some files in it:

```python
from pathlib import Path

from scenario.state import Container, State, Mount

local_file = Path('/path/to/local/real/file.txt')

state = State(containers=[
    Container(name="foo",
              can_connect=True,
              mounts={'local': Mount('/local/share/config.yaml', local_file)})
]
)
```

In this case, if the charm were to:
```python
def _on_start(self, _):
    foo = self.unit.get_container('foo')
    content = foo.pull('/local/share/config.yaml').read()
```

then `content` would be the contents of our locally-supplied `file.txt`. You can use `tempdir` for nicely wrapping strings and passing them to the charm via the container.

`container.push` works similarly, so you can write a test like:

```python
import tempfile
from ops.charm import CharmBase
from scenario.state import State, Container, Mount


class MyCharm(CharmBase):
    def _on_start(self, _):
        foo = self.unit.get_container('foo')
        foo.push('/local/share/config.yaml', "TEST", make_dirs=True)


def test_pebble_push():
    local_file = tempfile.TemporaryFile()
    container = Container(name='foo',
                          mounts={'local': Mount('/local/share/config.yaml', local_file.name)})
    out = State(
        containers=[container]
    ).trigger(
        container.pebble_ready_event,
        MyCharm,
        meta={"name": "foo", "containers": {"foo": {}}},
    )
    assert local_file.open().read() == "TEST"
```

`container.pebble_ready_event` is syntactic sugar for: `Event("foo-pebble-ready", container=container)`. The reason we need to associate the container with the event is that the Framework uses an envvar to determine which container the pebble-ready event is about (it does not use the event name). Scenario needs that information, similarly, for injecting that envvar into the charm's runtime.

`container.exec` is a tad more complicated, but if you get to this low a level of simulation, you probably will have far worse issues to deal with.
You need to specify, for each possible command the charm might run on the container, what the result of that would be: its return code, what will be written to stdout/stderr.

```python
from ops.charm import CharmBase

from scenario.state import State, Container, ExecOutput

LS_LL = """
.rw-rw-r--  228 ubuntu ubuntu 18 jan 12:05 -- charmcraft.yaml    
.rw-rw-r--  497 ubuntu ubuntu 18 jan 12:05 -- config.yaml        
.rw-rw-r--  900 ubuntu ubuntu 18 jan 12:05 -- CONTRIBUTING.md    
drwxrwxr-x    - ubuntu ubuntu 18 jan 12:06 -- lib                
"""


class MyCharm(CharmBase):
    def _on_start(self, _):
        foo = self.unit.get_container('foo')
        proc = foo.exec(['ls', '-ll'])
        stdout, _ = proc.wait_output()
        assert stdout == LS_LL


def test_pebble_exec():
    container = Container(
        name='foo',
        exec_mock={
            ('ls', '-ll'):  # this is the command we're mocking
                ExecOutput(return_code=0,  # this data structure contains all we need to mock the call.
                           stdout=LS_LL)
        }
    )
    out = State(
        containers=[container]
    ).trigger(
        container.pebble_ready_event,
        MyCharm,
        meta={"name": "foo", "containers": {"foo": {}}},
    )
```


# Deferred events
Scenario allows you to accurately simulate the Operator Framework's event queue. The event queue is responsible for keeping track of the deferred events.
On the input side, you can verify that if the charm triggers with this and that event in its queue (they would be there because they had been deferred in the previous run), then the output state is valid.

```python
from scenario import State, deferred


class MyCharm(...):
    ...
    def _on_update_status(self, e):
        e.defer()
    def _on_start(self, e):
        e.defer()

        
def test_start_on_deferred_update_status(MyCharm):
    """Test charm execution if a 'start' is dispatched when in the previous run an update-status had been deferred."""
    out = State(
      deferred=[
            deferred('update_status', 
                     handler=MyCharm._on_update_status)
        ]
    ).trigger('start', MyCharm)
    assert len(out.deferred) == 1
    assert out.deferred[0].name == 'start'
```

You can also generate the 'deferred' data structure (called a DeferredEvent) from the corresponding Event (and the handler):

```python
from scenario import Event, Relation

class MyCharm(...):
    ...

deferred_start = Event('start').deferred(MyCharm._on_start)
deferred_install = Event('install').deferred(MyCharm._on_start)
```

## relation events:
```python   
foo_relation = Relation('foo') 
deferred_relation_changed_evt = foo_relation.changed_event.deferred(handler=MyCharm._on_foo_relation_changed)
```
On the output side, you can verify that an event that you expect to have been deferred during this trigger, has indeed been deferred.

```python
from scenario import State


class MyCharm(...):
    ...
    def _on_start(self, e):
        e.defer()

        
def test_defer(MyCharm):
    out = State().trigger('start', MyCharm)
    assert len(out.deferred) == 1
    assert out.deferred[0].name == 'start'
```
    
## Deferring relation events
If you want to test relation event deferrals, some extra care needs to be taken. RelationEvents hold references to the Relation instance they are about. So do they in Scenario. You can use the deferred helper to generate the data structure:

```python
from scenario import State, Relation, deferred


class MyCharm(...):
    ...
    def _on_foo_relation_changed(self, e):
        e.defer()

        
def test_start_on_deferred_update_status(MyCharm):
    foo_relation = Relation('foo') 
    State(
      relations=[foo_relation],
      deferred=[
            deferred('foo_relation_changed', 
                     handler=MyCharm._on_foo_relation_changed,
                     relation=foo_relation)
        ]
    )
```
but you can also use a shortcut from the relation event itself, as mentioned above:

```python

from scenario import Relation

class MyCharm(...):
    ...

foo_relation = Relation('foo') 
foo_relation.changed_event.deferred(handler=MyCharm._on_foo_relation_changed)
```

### Fine-tuning

The deferred helper Scenario provides will not support out of the box all custom event subclasses, or events emitted by charm libraries or objects other than the main charm class.

For general-purpose usage, you will need to instantiate DeferredEvent directly.

```python
from scenario import DeferredEvent

my_deferred_event = DeferredEvent(
   handle_path='MyCharm/MyCharmLib/on/database_ready[1]',
   owner='MyCharmLib',  # the object observing the event. Could also be MyCharm.
   observer='_on_database_ready'
)
```


# StoredState

Scenario can simulate StoredState.
You can define it on the input side as:

```python
from ops.charm import CharmBase
from ops.framework import StoredState as Ops_StoredState, Framework
from scenario import State, StoredState


class MyCharmType(CharmBase):
    my_stored_state = Ops_StoredState()

    def __init__(self, framework: Framework):
        super().__init__(framework)
        assert self.my_stored_state.foo == 'bar'  # this will pass!


state = State(stored_state=[
  StoredState(
    owner_path="MyCharmType",
    name="my_stored_state",
    content={
      'foo': 'bar',
      'baz': {42: 42},
    })
])
```

And the charm's runtime will see `self.stored_State.foo` and `.baz` as expected.
Also, you can run assertions on it on the output side the same as any other bit of state.


# The virtual charm root
Before executing the charm, Scenario writes the metadata, config, and actions `yaml`s to a temporary directory. 
The charm will see that tempdir as its 'root'. This allows us to keep things simple when dealing with metadata that can 
be either inferred from the charm type being passed to `trigger()` or be passed to it as an argument, thereby overriding
the inferred one. This also allows you to test with charms defined on the fly, as in:

```python
from ops.charm import CharmBase
from scenario import State

class MyCharmType(CharmBase):
    pass

state = State().trigger(charm_type=MyCharmType, meta={'name': 'my-charm-name'}, event='start')
```

A consequence of this fact is that you have no direct control over the tempdir that we are
creating to put the metadata you are passing to trigger (because `ops` expects it to be a file...).
That is, unless you pass your own:

```python
from ops.charm import CharmBase
from scenario import State
import tempfile


class MyCharmType(CharmBase):
  pass


td = tempfile.TemporaryDirectory()
state = State().trigger(charm_type=MyCharmType, meta={'name': 'my-charm-name'}, event='start',
                        charm_root=td.name)
```

Do this, and you will be able to set up said directory as you like before the charm is run, as well 
as verify its contents after the charm has run. Do keep in mind that the metadata files will 
be overwritten by Scenario, and therefore ignored.


# Consistency checks

A Scenario, that is, the combination of an event, a state, and a charm, is consistent if it's plausible in JujuLand.
For example, Juju can't emit a `foo-relation-changed` event on your charm unless your charm has declared a `foo` relation
endpoint in its `metadata.yaml`. If that happens, that's a juju bug.
Scenario however assumes that Juju is bug-free, therefore, so far as we're concerned, that can't happen, and therefore we 
help you verify that the scenarios you create are consistent and raise an exception if that isn't so.

That happens automatically behind the scenes whenever you trigger an event; `scenario.consistency_checker.check_consistency`
is called and verifies that the scenario makes sense.

## Caveats:
- False positives: not all checks are implemented yet; more will come.
- False negatives: it is possible that a scenario you know to be consistent is seen as inconsistent. That is probably a bug in the consistency checker itself, please report it.
- Inherent limitations: if you have a custom event whose name conflicts with a builtin one, the consistency constraints of the builtin one will apply. For example: if you decide to name your custom event `bar-pebble-ready`, but you are working on a machine charm or don't have either way a `bar` container in your `metadata.yaml`, Scenario will flag that as inconsistent. 

## Bypassing the checker
If you have a clear false negative, are explicitly testing 'edge', inconsistent situations, or for whatever reason the checker is in your way, you can set the `SCENARIO_SKIP_CONSISTENCY_CHECKS` envvar and skip it altogether. Hopefully you don't need that.


# Snapshot

Scenario comes with a cli tool called `snapshot`. Assuming you've pip-installed `ops-scenario`, you should be able to reach the entry point by typing `scenario snapshot` in a shell.

Snapshot's purpose is to gather the State data structure from a real, live charm running in some cloud your local juju client has access to. This is handy in case:
- you want to write a test about the state the charm you're developing is currently in
- your charm is bork or in some inconsistent state, and you want to write a test to check the charm will handle it correctly the next time around (aka regression testing)
- you are new to Scenario and want to quickly get started with a real-life example.

Suppose you have a Juju model with a `prometheus-k8s` unit deployed as `prometheus-k8s/0`. If you type `scenario snapshot prometheus-k8s/0`, you will get a printout of the State object. Copy-paste that in some file, import all you need from `scenario`, and you have a working `State` that you can `.trigger()` events from.

You can also pass a `--format json | pytest | state (default=state)` flag to obtain
- jsonified `State` data structure, for portability
- a full-fledged pytest test case (with imports and all), where you only have to fill in the charm type and the event that you wish to trigger. 

# TODOS:
- Recorder
