NOTE: [we're trying](https://github.com/canonical/operator/pull/887) to merge this in ops main. Stay tuned! 

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

Scenario-testing a charm, then, means verifying that:

- the charm does not raise uncaught exceptions while handling the scene
- the output state (or the diff with the input state) is as expected.


# Core concepts as a metaphor
I like metaphors, so here we go:
- There is a theatre stage (Scenario).
- You pick an actor (a Charm) to put on the stage. Not just any actor: an improv one.
- You arrange the stage with content that the the actor will have to interact with (a Scene). Setting up the scene consists of selecting:
  - An initial situation (Context) in which the actor is, e.g. is the actor the main role or an NPC (is_leader), or what other actors are there around it, what is written in those books on the table?
  - Something that has just happened (an Event) and to which the actor has to react (e.g. one of the NPCs leaves the stage (relation-departed), or the content of one of the books changes).
- How the actor will react to the event will have an impact on the context: e.g. the actor might knock over a table (a container), or write something down into one of the books.


# Core concepts not as a metaphor
Each scene maps to a single event. 
The Scenario encapsulates the charm and its metadata. A scenario can play scenes, which represent the several events one can fire on a charm and the c
Crucially, this decoupling of charm and context aontext in which they occur.
llows us to swap out easily any part of this flow, and even share context data across charms, codebases, teams...

In this spirit, but that I still have to think through how useful it really is, a Scenario exposes a `playbook`: a sequence of scenes it can run sequentially (although given that each Scene's input state is totally disconnected from any other's, the ordering of the sequence is irrelevant) and potentially share with other projects. More on this later.


![image](https://user-images.githubusercontent.com/6230162/214538871-a44e29c6-3fd5-46a3-82c8-d7fa34452dcf.png)


# Writing scenario tests
Writing a scenario test consists of two broad steps:

- define a scene
  - an event 
  - an input state
- play the scene (obtain the output state)
- assert that the output state is how you expect it to be

The most basic scenario is the so-called `null scenario`: one in which all is defaulted and barely any data is
available. The charm has no config, no relations, no networks, and no leadership.

With that, we can write the simplest possible scenario test:

```python
from scenario.scenario import Scenario, Scene, State
from scenario.structs import CharmSpec, event
from ops.charm import CharmBase


class MyCharm(CharmBase):
    pass


def test_scenario_base():
    scenario = Scenario(CharmSpec(MyCharm, meta={"name": "foo"}))
    out = scenario.play(Scene(event=event("start"), state=State()))
    assert out.status.unit == ('unknown', '')
```

Now let's start making it more complicated.
Our charm sets a special state if it has leadership on 'start':

```python
from scenario.scenario import Scenario, Scene, State
from scenario.structs import CharmSpec, event
from ops.charm import CharmBase
from ops.model import ActiveStatus


class MyCharm(CharmBase):
    def __init__(self, *args):
        super().__init__(*args)
        self.framework.observe(self.on.start, self._on_start)

    def _on_start(self, _):
        if self.unit.is_leader():
            self.unit.status = ActiveStatus('I rule')


def test_scenario_base():
    scenario = Scenario(CharmSpec(MyCharm, meta={"name": "foo"}))
    out = scenario.play(Scene(event=event("start"), state=State()))
    assert out.status.unit == ('unknown', '')


def test_status_leader():
    scenario = Scenario(CharmSpec(MyCharm, meta={"name": "foo"}))
    out = scenario.play(Scene(event=event("start"), state=State(leader=True)))
    assert out.status.unit == ('active', 'I rule')
```

This is starting to get messy, but fortunately scenarios are easily turned into fixtures. We can rewrite this more
concisely (and parametrically) as:

```python
import pytest

from ops.charm import CharmBase
from ops.model import ActiveStatus
from scenario.scenario import Scenario, Scene, State
from scenario.structs import CharmSpec, event


class MyCharm(CharmBase):
    def __init__(self, *args):
        super().__init__(*args)
        self.framework.observe(self.on.start, self._on_start)

    def _on_start(self, _):
        if self.unit.is_leader():
            self.unit.status = ActiveStatus("I rule")
        else:
            self.unit.status = ActiveStatus("I follow")


@pytest.fixture
def scenario():
    return Scenario(CharmSpec(MyCharm, meta={"name": "foo"}))


@pytest.fixture
def start_scene():
    return Scene(event=event("start"), state=State())


def test_scenario_base(scenario, start_scene):
    out = scenario.play(start_scene)
    assert out.status.unit == ("active", "I follow")


@pytest.mark.parametrize("leader", [True, False])
def test_status_leader(scenario, start_scene, leader):
    leader_scene = start_scene.copy()
    leader_scene.state.leader = leader

    out = scenario.play(leader_scene)
    expected_status = ("active", "I rule") if leader else ("active", "I follow")
    assert out.status.unit == expected_status
```

By defining the right state we can programmatically define what answers will the charm get to all the questions it can ask the juju model: am I leader? What are my relations? What is the remote unit I'm talking to? etc...

## Relations

You can write scenario tests to verify the shape of relation data:

```python
from scenario.structs import relation
from ops.charm import CharmBase


# This charm copies over remote app data to local unit data
class MyCharm(CharmBase):
  ...

  def _on_event(self, e):
    relation = self.model.relations['foo'][0]
    assert relation.app.name == 'remote'
    assert e.relation.data[self.unit]['abc'] == 'foo'
    e.relation.data[self.unit]['abc'] = e.relation.data[e.app]['cde']


def test_relation_data(scenario, start_scene):
  scene = start_scene.copy()
  scene.context.state.relations = [
    relation(
      endpoint="foo",
      interface="bar",
      remote_app_name="remote",
      local_unit_data={"abc": "foo"},
      remote_app_data={"cde": "baz!"},
    ),
  ]
  out = scenario.play(scene)
  assert out.relations[0].local_unit_data == {"abc": "baz!"}
  # one could probably even do:
  assert out.relations == [
    relation(
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
from scenario.structs import Scene, event, container, State
scene = Scene(
    event("start"),
    state=State(containers=[
      container(name="foo", can_connect=True),
      container(name="bar", can_connect=False)
    ]),
)
```

In this case, `self.unit.get_container('foo').can_connect()` would return `True`, while for 'bar' it would give `False`.

You can also configure a container to have some files in it:

```python
from scenario.structs import Scene, event, container, State
from pathlib import Path

local_file = Path('/path/to/local/real/file.txt')

scene = Scene(
    event("start"),
    state=State(containers=[
      container(name="foo", 
                can_connect=True,
                filesystem={'local': {'share': {'config.yaml': local_file}}})
    ]),
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
from ops.charm import CharmBase
from scenario.structs import Scene, event, State, container

class MyCharm(CharmBase):
    def _on_start(self, _):
        foo = self.unit.get_container('foo')
        foo.push('/local/share/config.yaml', "TEST", make_dirs=True)

def test_pebble_push(scenario, start_scene):
  out = scenario.play(Scene(
    event=event('start'), 
    state=State(
      containers=[container(name='foo')]
    )))
  assert out.get_container('foo').filesystem['local']['share']['config.yaml'].read_text() == "TEST"
```

`container.exec` is a little bit more complicated. 
You need to specify, for each possible command the charm might run on the container, what the result of that would be: its return code, what will be written to stdout/stderr.

```python
from ops.charm import CharmBase
from scenario.structs import Scene, event, State, container, ExecOutput

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


def test_pebble_exec(scenario, start_scene):
    scenario.play(Scene(
        event=event('start'),
        state=State(
            containers=[container(
                name='foo',
                exec_mock={
                    ('ls', '-ll'):  # this is the command we're mocking
                        ExecOutput(return_code=0,  # this data structure contains all we need to mock the call.
                                   stdout=LS_LL)
                }
            )]
        )))
```


# TODOS:
- Figure out how to distribute this. I'm thinking `pip install ops[scenario]`
- Better syntax for memo generation
<<<<<<< HEAD
=======
- Consider consolidating memo and State (e.g. passing a Sequence object to a State value...)
- Expose instructions or facilities re. how to use this without borking your venv.
>>>>>>> f9b8896 (now, the first 3 examples are valid and green)
