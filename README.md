Ops-Scenario
============

This is a python library that you can use to run scenario-based tests.

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
- Harness exposes an imperative API: the user is expected to call methods on the Harness driving it to the desired , then verify the validity of the state.
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


class MyCharm(CharmBase):
    pass


def test_scenario_base():
    out = State().trigger(
        'start', 
        MyCharm, meta={"name": "foo"})
    assert out.status.unit == ('unknown', '')
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
    assert out.status.unit == ('active', 'I rule' if leader else 'I am ruled')
```

By defining the right state we can programmatically define what answers will the charm get to all the questions it can ask the juju model: am I leader? What are my relations? What is the remote unit I'm talking to? etc...

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


# TODOS:
- State-State consistency checks.
- State-Metadata consistency checks.
- When ops supports namespace packages, allow `pip install ops[scenario]` and nest the whole package under `/ops`.
- Recorder