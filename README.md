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
- You pick an actor (a Charm) to put on the stage.
- You pick a sketch that the actor will have to play out (a Scene). The sketch is specified as:
  - An initial situation (Context) in which the actor is, e.g. is the actor the main role or an NPC (is_leader), or what other actors are there around it, what is written on those books on the table?
  - Something that happens (an Event) and to which the actor has to react (e.g. one of the NPCs leaves the stage (relation-departed))
- How the actor will react to the event will have an impact on the context: e.g. the actor might knock over a table (a container), or write something to a book (pebble.push).


# Core concepts not as a metaphor
Each scene maps to a single event. 
The Scenario encapsulates the charm and its metadata. A scenario can play scenes, which represent the several events one can fire on a charm and the context in which they occur.

Crucially, this decoupling of charm and context allows us to swap out easily any part of this flow, and even share context data across charms, codebases, teams...

In this spirit, but that I still have to think through how useful it really is, a Scenario exposes a `playbook`: a sequence of scenes it can run sequentially (although given that each Scene's input state is totally disconnected from any other's, the ordering of the sequence is irrelevant) and potentially share with other projects.

# Writing scenario tests

Writing a scenario tests consists of two broad steps:

- define a Scenario
- run the scenario

The most basic scenario is the so-called `null scenario`: one in which all is defaulted and barely any data is
available. The charm has no config, no relations, no networks, and no leadership.

With that, we can write the simplest possible scenario test:

```python
from scenario.scenario import Scenario, Scene
from scenario.structs import CharmSpec, event, Context
from ops.charm import CharmBase


class MyCharm(CharmBase):
    pass


def test_scenario_base():
    scenario = Scenario(CharmSpec(MyCharm, meta={"name": "foo"}))
    out = scenario.play(Scene(event=event('start'), context=Context()))
    assert out.context_out.state.status.unit == ('unknown', '')
```

Now let's start making it more complicated.
Our charm sets a special state if it has leadership on 'start':

```python
from scenario.scenario import Scenario, Scene
from scenario.structs import CharmSpec, event, Context, State
from ops.charm import CharmBase
from ops.model import ActiveStatus


class MyCharm(CharmBase):
    def __init__(self, ...):
        self.framework.observe(self.on.start, self._on_start)

    def _on_start(self, _):
        if self.unit.is_leader():
            self.unit.status = ActiveStatus('I rule')


def test_scenario_base():
    scenario = Scenario(CharmSpec(MyCharm, meta={"name": "foo"}))
    out = scenario.play(Scene(event=event('start'), context=Context()))
    assert out.context_out.state.status.unit == ('unknown', '')


def test_status_leader():
    scenario = Scenario(CharmSpec(MyCharm, meta={"name": "foo"}))
    out = scenario.play(
        Scene(
            event=event('start'),
            context=Context(
                state=State(leader=True)
            )))
    assert out.context_out.state.status.unit == ('active', 'I rule')
```

This is starting to get messy, but fortunately scenarios are easily turned into fixtures. We can rewrite this more
concisely (and parametrically) as:

```python
import pytest
from scenario.scenario import Scenario, Scene
from scenario.structs import CharmSpec, event, Context
from ops.charm import CharmBase
from ops.model import ActiveStatus


class MyCharm(CharmBase):
  def __init__(self, ...):
    self.framework.observe(self.on.start, self._on_start)

  def _on_start(self, _):
    if self.unit.is_leader():
      self.unit.status = ActiveStatus('I rule')
    else:
      self.unit.status = ActiveStatus('I follow')


@pytest.fixture
def scenario():
  return Scenario(CharmSpec(MyCharm, meta={"name": "foo"}))


@pytest.fixture
def start_scene():
  return Scene(event=event('start'), context=Context())


def test_scenario_base(scenario, start_scene):
  out = scenario.play(start_scene)
  assert out.context_out.state.status.unit == ('unknown', '')


@pytest.mark.parametrize('leader', [True, False])
def test_status_leader(scenario, start_scene, leader):
  leader_scene = start_scene.copy()
  leader_scene.context.state.leader = leader

  out = scenario.play(leader_scene)
  if leader:
    assert out.context_out.state.status.unit == ('active', 'I rule')
  else:
    assert out.context_out.state.status.unit == ('active', 'I follow')
```

By defining the right state we can programmatically define what answers will the charm get to all the questions it can ask to the juju model: am I leader? What are my relations? What is the remote unit I'm talking to? etc...

An example involving relations:

```python
from scenario.structs import relation


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
  assert out.context_out.state.relations[0].local_unit_data == {"abc": "baz!"}
  # one could probably even do:
  assert out.context_out.state.relations == [
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


# Playbooks

A playbook encapsulates a sequence of scenes. 

For example:
```python
from scenario.scenario import Playbook
from scenario.structs import State, Scene, Event, Context
playbook = Playbook(
        (
            Scene(Event("update-status"),
                  context=Context(state=State(config={'foo':'bar'}))),
            Scene(Event("config-changed"), 
                  context=Context(state=State(config={'foo':'baz'}))),
        )
    )
```

This allows us to write concisely common event sequences, such as the charm startup/teardown sequences. These are the only ones that are built-into the framework.
This is the new `Harness.begin_with_initial_hooks`:
```python
import pytest
from scenario.scenario import StartupScenario
from scenario.structs import CharmSpec

@pytest.mark.parametrize("leader", (True, False))
def test_setup(leader, mycharm):
    scenario = StartupScenario(CharmSpec(mycharm, meta={"name": "foo"}), leader=leader)
    scenario.play_until_complete()
```

The idea is that users can write down sequences common to their use case 
(or multiple charms in a bundle) and share them between tests.


# Caveats
The way we're injecting memo calls is by rewriting parts of `ops.main`, and `ops.framework` using the python ast module. This means that we're seriously messing with your venv. This is a temporary measure and will be factored out of the code as we move out of the alpha phase.

Options we're considering:
- have a script that generates our own `ops` lib, distribute that along with the scenario source, and in your scenario tests you'll have to import from the patched-ops we provide instead of the 'canonical' ops module.
- trust you to run all of this in ephemeral contexts (e.g. containers, tox env...)  for now, **YOU SHOULD REALLY DO THAT**


# Advanced Mockery
The Harness mocks data by providing a separate backend. When the charm code asks: am I leader? there's a variable
in `harness._backend` that decides whether the return value is True or False.
A Scene exposes two layers of data to the charm: memos and a state.

- Memos are strict, cached input->output mappings. They basically map a function call to a hardcoded return value, or
  multiple return values.
- A State is a static database providing the same mapping, but only a single return value is supported per input.

Scenario tests mock the data by operating at the hook tool call level, not the backend level. Every backend call that
would normally result in a hook tool call is instead redirected to query the available memos, and as a fallback, is
going to query the State we define as part of a Scene. If neither one can provide an answer, the hook tool call is
propagated -- which unless you have taken care of mocking that executable as well, will likely result in an error.

Let's see the difference with an example:

Suppose the charm does:

```python
    ...


def _on_start(self, _):
    assert self.unit.is_leader()

    import time
    time.sleep(31)

    assert not self.unit.is_leader()

    if self.unit.is_leader():
        self.unit.status = ActiveStatus('I rule')
    else:
        self.unit.status = ActiveStatus('I follow')
```

Suppose we want this test to pass. How could we mock this using Scenario?

```python
scene = Scene(
    event=event('start'),
    context=Context(memos=[
        {'name': '_ModelBackend.leader_get',
         'values': ['True', 'False'],
         'caching_mode': 'strict'}
    ])
)
```
What this means in words is: the mocked hook-tool 'leader-get' call will return True at first, but False the second time around.

Since we didn't pass a State to the Context object, when the runtime fails to find a third value for leader-get, it will fall back and use the static value provided by the default State -- False. So if the charm were to call `is_leader` at any point after the first two calls, it would consistently get False.

NOTE: the API is work in progress. We're working on exposing friendlier ways of defining memos.
The good news is that you can generate memos by scraping them off of a live unit using `jhack replay`.


# TODOS:
- Figure out how to distribute this. I'm thinking `pip install ops[scenario]`
- Better syntax for memo generation
- Consider consolidating memo and State (e.g. passing a Sequence object to a State value...)
- Expose instructions or facilities re. how to use this without borking your venv.