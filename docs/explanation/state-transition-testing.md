# State-transition testing

The framework for state-transition testing in Ops was originally developed under the name "Scenario" and released as a Python package called `ops-scenario`. Scenario solved so many issues with the older "Harness" framework that it was adopted as the recommended framework for writing charm unit tests.

This page compares Scenario to Harness and explains how state-transition tests work. For a summary of how to write unit tests, see [](/howto/write-unit-tests-for-a-charm).

```{note}
In your testing dependencies, add `ops[testing]` rather than `ops-scenario`, and
this will ensure that an appropriate version of the framework is installed.

Similarly, to get access to the various framework classes, use the `ops.testing`
namespace, rather than `scenario`. "from ops import testing ... ctx =
testing.Context" rather than "import scenario ... ctx = scenario.Context".
```

Where the deprecated Harness framework enables you to procedurally mock pieces of the state the
charm needs to function, state-transition tests allow you to declaratively
define the state all at once, and use it as a sort of context against which you
can fire a single event on the charm and execute its logic.

This puts the tests somewhere in between unit and integration tests: some say
'functional', some say 'contract', we prefer 'state-transition'.

The tests nudge you into thinking of a charm as an input->output function. The
input is the union of an event (why am I, charm, being executed), a `State`
(am I leader? what is my relation data? what is my config?...) and the charm's
execution `Context` (what relations can I have? what containers can I have?...).
The output is another `State`: the state after the charm has had a chance to
interact with the mocked Juju model and affect the initial state back.

![state transition model depiction](https://raw.githubusercontent.com/canonical/ops-scenario/main/resources/state-transition-model.png)

For example: a charm currently in `unknown` status is executed with a `start`
event, and based on whether it has leadership or not (according to its input
state), it will decide to set `active` or `blocked` status (which will be
reflected in the output state).

Using the state-transition framework for charm unit tests, then, means verifying
that:

- the charm does not raise uncaught exceptions while handling the event
- the output state (or the diff with the input state) is as expected.

When the testing framework runs the event, the input state isn't modified. Instead, the output state is a new `State` object. `State` objects are generally immutable - but be careful when working with `dict` attributes, as they don't enforce immutability.

## Core concepts

The tests are about running assertions on atomic state transitions, treating the
charm being tested like a black box. An initial state goes in, an event occurs
(say, `'start'`) and a new state comes out. The tests are about validating the
transition, that is, consistency-checking the delta between the two states, and
verifying the charm author's expectations.

Comparing these tests with `Harness` tests:

- Harness exposes an imperative API: the user is expected to call methods on the
  harness driving it to the desired state, then verify its validity by calling
  charm methods or inspecting the raw data. In contrast, these tests are
  declarative. You fully specify an initial state, an execution context and an
  event, then you run the charm and inspect the results.
- Harness instantiates the charm once, then allows you to fire multiple events
  on the charm, which is breeding ground for subtle bugs. These tests are
  centered around testing single state transitions, that is, one event at a
  time. This ensures that the execution environment is as clean as possible
  (for a unit test).
- Harness maintains a model of the Juju Model, which is a maintenance burden and
  adds complexity. These tests mock at the level of hook commands and store all
  mocking data in a monolithic data structure (the `State`), which makes it more
  lightweight and portable.

## Writing tests

A test consists of three broad steps:

- **Arrange**:
    - declare the context
    - declare the input state
    - select an event to fire
- **Act**:
    - "run" the context - obtain the output state from the given input state
      and the event
- **Assert**:
    - verify that the output state (or the delta with the input state) is how
      you expect it to be
    - verify that the charm has seen a certain sequence of statuses, events,
      and `juju-log` calls
    - optionally, you can use a context manager to get a hold of the charm
      instance and run assertions on internal APIs and the internal state of the
      charm and `ops`.

The most basic scenario is one in which all defaults apply and barely any data is
available. The charm has no config, no relations, no leadership, and its status
is `unknown`.

With that, we can write the simplest possible test:

```python
from ops import testing


def test_basic_scenario():
    ctx = testing.Context(MyCharm)
    state_out = ctx.run(ctx.on.start(), testing.State())
    assert state_out.unit_status == testing.UnknownStatus()
```

```{tip}
You should always compare the app and unit status using `==`, not `is`. You can
compare them to either the `ops.testing` objects, or the `ops` ones.
```

Now let's start making it more complicated. Our charm sets a special state if it
has leadership on 'start':

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
    ctx = testing.Context(MyCharm, meta={'name': 'foo'})
    state_out = ctx.run(ctx.on.start(), testing.State(leader=leader))
    assert state_out.unit_status == testing.ActiveStatus('I rule' if leader else 'I am ruled')
```

By defining the right state we can programmatically define what answers will the
charm get to all the questions it can ask the Juju model: am I leader? What are
my relations? What is the remote unit I'm talking to? And so on ...

## Statuses

One of the simplest types of black-box testing available to charmers is to execute the charm and
verify that the charm sets the expected unit/application status. We have seen a simple example above including leadership. But what if the charm transitions through a sequence of statuses?

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

More broadly, often we want to test 'side effects' of executing a charm, such as what events have
been emitted, what statuses it went through, etc... Before we get there, we have to explain what the `Context` represents, and its relationship with the `State`.

## Context and State

Consider the following tests. Suppose we want to verify that while handling a given top-level Juju event:

- a specific chain of (custom) events was emitted on the charm
- the charm logged these specific strings
- the charm went through this sequence of app/unit statuses (e.g. `maintenance`, then `waiting`, then `active`)

These types of test have a place in Scenario, but that is not State: the contents of the Juju log or
the status history are side effects of executing a charm, but are not persisted in a
charm-accessible "state" in any meaningful way. In other words: those data streams are, from the
charm's perspective, write-only.

As such, they do not belong in `State` but in `Context`: the object representing the charm's
execution context.

## Live charm introspection

The testing framework is a black-box, state-transition testing framework. It
makes it trivial to assert that a status went from A to B, but not to assert
that, in the context of this charm execution, with this state, a certain
charm-internal method was called and returned a given piece of data, or would
return this and that _if_ it had been called.

The `Context` object can be used as a context manager for this use case. Note
that you can't call `manager.run()` multiple times: the object is a context
that ensures that `ops.main` 'pauses' right before emitting the event to hand
you some introspection hooks, but for the rest this is a regular test: you can't
emit multiple events in a single charm execution.

## The virtual charm root

Before executing the charm, the framework writes the metadata, config, and actions
YAML files to a temporary directory. The charm will see that temporary directory as its
'root'. This allows us to keep things simple when dealing with metadata that can be
either inferred from the charm type being passed to `Context` or be passed to it
as an argument, thereby overriding the inferred one. This also allows you to test
charms defined on the fly, as in:

```python
class MyCharmType(ops.CharmBase):
    pass


ctx = testing.Context(charm_type=MyCharmType, meta={'name': 'my-charm-name'})
ctx.run(ctx.on.start(), testing.State())
```

A consequence of this fact is that you have no direct control over the temporary
directory that we are creating to put the metadata you are passing to `.run()`.
That is, unless you pass your own:

```python
import tempfile


class MyCharmType(ops.CharmBase):
    pass


td = tempfile.TemporaryDirectory()
ctx = testing.Context(
    charm_type=MyCharmType,
    meta={'name': 'my-charm-name'},
    charm_root=td.name
)
state = ctx.run(ctx.on.start(), testing.State())
```

## Immutability

All of the data structures in the state, (`State`, `Relation`, `Container`, and
so on) are implemented as frozen dataclasses.

This means that all components of the state that goes into a `context.run()`
call are not mutated by the call, the state that you obtain in return is a
different instance, and all parts of it have been (deep) copied. This ensures
that you can do delta-based comparison of states without worrying about them
being mutated by the test framework.

If you want to modify any of these data structures, you will need to either
reinstantiate it from scratch, or use the dataclasses `replace` API.

```python
import dataclasses

relation = testing.Relation('foo', remote_app_data={'1': '2'})
# make a copy of relation, but with remote_app_data set to {'3': '4'}
relation2 = dataclasses.replace(relation, remote_app_data={'3': '4'})
```

Note that this also means that it's important to assert on the objects in the
*output* state. The input and output state will often have the same objects
(such as containers or relations), but the content of those objects is likely to
have changed during the event run. The `State` has `get_` methods to simplify
this, for example: `container_out = state_out.get_container(container_in.name)`.

## Consistency checks

A scenario, that is, the combination of an event, a state, and a charm, is
consistent if it's plausible in Juju. For example, Juju can't emit a
`foo-relation-changed` event on your charm unless your charm has declared a
`foo` relation endpoint in its metadata. If that happens, that's a Juju bug.
The framework, however, assumes that Juju is bug-free, so far as we're
concerned, that can't happen, and therefore we help you verify that the
scenarios you create are consistent and raise an exception if that isn't so.

That happens automatically behind the scenes whenever you trigger an event;
a consistency check is executed and verifies that the scenario makes sense.
