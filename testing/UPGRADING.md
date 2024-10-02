# Upgrading

## Scenario 6.x to Scenario 7.x

Scenario 7.0 has substantial API incompatibility with earlier versions, but
comes with an intention to reduce the frequency of breaking changes in the
future, aligning with the `ops` library.

The changes listed below are not the only features introduced in Scenario 7.0
(for that, see the release notes), but cover the breaking changes where you will
need to update your existing Scenario tests.

### Specify events via context.on

In previous versions of Scenario, an event would be passed to `Context.run`
as a string name, via a convenient shorthand property of a state component
(e.g. `Relation`, `Container`), or by explicitly constructing an `Event` object.
These have been unified into a single `Context.on.{event name}()` approach,
which is more consistent, resembles the structure you're familiar with from
charm `observe` calls, and should provide more context to IDE and linting tools.

```python
# Older Scenario code.
ctx.run('start', state)
ctx.run(container.pebble_ready_event, state)
ctx.run(Event('relation-joined', relation=relation), state)

# Scenario 7.x
ctx.run(ctx.on.start(), state)
ctx.run(ctx.on.pebble_ready(container=container), state)
ctx.run(ctx.on.relation_joined(relation=relation), state)
```

The same applies to action events:

```python
# Older Scenario code.
action = Action("backup", params={...})
ctx.run_action(action, state)

# Scenario 7.x
ctx.run(ctx.on.action("backup", params={...}), state)
```

### Provide State components as (frozen) sets

The state components were previously lists, but containers, relations, networks,
and other state components do not have any inherent ordering. This led to
'magic' numbers creeping into test code. These are now all sets, and have 'get'
methods to retrieve the object you want to assert on. In addition, they are
actually `frozenset`s (Scenario will automatically freeze them if you pass a
`set`), which increases the immutability of the state and prevents accidentally
modifying the input state.

```python
# Older Scenario code.
state_in = State(containers=[c1, c2], relations=[r1, r2])
...
assert state_out.containers[1]...
assert state_out.relations[0]...
state_out.relations.append(r3)  # Not recommended!

# Scenario 7.x
state_in = State(containers={c1, c2}, relations={r1, r2})
...
assert state_out.get_container(c2.name)...
assert state_out.get_relation(id=r1.id)...
new_state = dataclasses.replace(state_out, relations=state_out.relations + {r3})
```

### Run action events in the same way as other events

Previously, to run an action event Scenario offered a `run_action` method that
returned an object containing the result of the action. The `run_action()`
method (top-level and on the context manager) has been unified with the `run()`
method. All events, including action events, are run with `run()` and return a
`State` object. The action logs and history are available via the `Context`
object, and if the charm calls `event.fail()`, an exception will be raised.

```python
# Older Scenario Code
action = Action("backup", params={...})
out = ctx.run_action(action, state)
assert out.logs == ["baz", "qux"]
assert not out.success
assert out.results == {"foo": "bar"}
assert out.failure == "boo-hoo"

# Scenario 7.x
with pytest.raises(ActionFailure) as exc_info:
    ctx.run(ctx.on.action("backup", params={...}), State())
assert ctx.action_logs == ['baz', 'qux']
assert ctx.action_results == {"foo": "bar"}
assert exc_info.value.message == "boo-hoo"
```

### Use the Context object as a context manager

The deprecated `pre_event` and `post_event` arguments to `run`
(and `run_action`) have been removed: use the context handler instead. In
addition, the `Context` object itself is now used for a context manager, rather
than having `.manager()` and `action_manager()` methods.

In addition, the `.output` attribute of the context manager has been removed.
The state should be accessed explicitly by using the return value of the
`run()` method.

```python
# Older Scenario code.
ctx = Context(MyCharm)
state = ctx.run("start", pre_event=lambda charm: charm.prepare(), state=State())

ctx = Context(MyCharm)
with ctx.manager("start", State()) as mgr:
    mgr.charm.prepare()
assert mgr.output....

# Scenario 7.x
ctx = Context(MyCharm)
with ctx(ctx.on.start(), State()) as manager:
    manager.charm.prepare()
    out = manager.run()
    assert out...
```

### Pass State components are by keyword

Previously, it was possible (but inadvisable) to use positional arguments for
the `State` and its components. Most state components, and the `State` object
itself, now request at least some arguments to be passed by keyword. In most
cases, it's likely that you were already doing this, but the API is now
enforced.

```python
# Older Scenario code.
container1 = Container('foo', True)
state = State({'key': 'value'}, [relation1, relation2], [network], [container1, container2])

# Scenario 7.x
container1 = Container('foo', can_connect=True)
state = State(
    config={'key': 'value'},
    relations={relation1, relation2},
    networks={network},
    containers={container1, container2},
)
```

### Pass only the tracked and latest content to Secrets

In the past, any number of revision contents were provided when creating a
`Secret. Now, rather than having a dictionary of many revisions as part of `Secret`
objects, only the tracked and latest revision content needs to be included.
These are the only revisions that the charm has access to, so any other
revisions are not required. In addition, there's no longer a requirement to
pass in an ID.

```python
# Older Scenario code.
state = State(
    secrets=[
        scenario.Secret(
            id='foo',
            contents={0: {'certificate': 'xxxx'}}
        ),
        scenario.Secret(
            id='foo',
            contents={
                0: {'password': '1234'},
                1: {'password': 'abcd'},
                2: {'password': 'admin'},
            }
        ),
    ]
)

# Scenario 7.x
state = State(
    secrets={
        scenario.Secret({'certificate': 'xxxx'}),
        scenario.Secret(
            tracked_content={'password': '1234'},
            latest_content={'password': 'admin'},
        ),
    }
)
```

### Trigger custom events by triggering the underlying Juju event

Scenario no longer supports explicitly running custom events. Instead, you
should run the Juju event(s) that will trigger the custom event. For example,
if you have a charm lib that will emit a `database-created` event on
`relation-created`:

```python
# Older Scenario code.
ctx.run("my_charm_lib.on.database_created", state)

# Scenario 7.x
ctx.run(ctx.on.relation_created(relation=relation), state)
```

Scenario will still capture custom events in `Context.emitted_events`.

### Copy objects with dataclasses.replace and copy.deepcopy

The `copy()` and `replace()` methods of `State` and the various state components
have been removed. You should use the `dataclasses.replace` and `copy.deepcopy`
methods instead.

```python
# Older Scenario code.
new_container = container.replace(can_connect=True)
duplicate_relation = relation.copy()

# Scenario 7.x
new_container = dataclasses.replace(container, can_connect=True)
duplicate_relation = copy.deepcopy(relation)
```

### Define resources with the Resource class

The resources in State objects were previously plain dictionaries, and are now
`scenario.Resource` objects, aligning with all of the other State components.

```python
# Older Scenario code
state = State(resources={"/path/to/foo", pathlib.Path("/mock/foo")})

# Scenario 7.x
resource = Resource(location="/path/to/foo", source=pathlib.Path("/mock/foo"))
state = State(resources={resource})
```

### Give Network objects a binding name attribute

Previously, `Network` objects were added to the state as a dictionary of
`{binding_name: network}`. Now, `Network` objects are added to the state as a
set, like the other components. This means that the `Network` object now
requires a binding name to be passed in when it is created.

```python
# Older Scenario code
state = State(networks={"foo": Network.default()})

# Scenario 7.x
state = State(networks={Network.default("foo")})
```

### Use the .deferred() method to populate State.deferred

Previously, there were multiple methods to populate the `State.deferred` list:
events with a `.deferred()` method, the `scenario.deferred()` method, and
creating a `DeferredEvent` object manually. Now, for Juju events, you should
always use the `.deferred()` method of the event -- this also ensures that the
deferred event has all of the required links (to relations, containers, secrets,
and so on).

```python
# Older Scenario code
deferred_start = scenario.deferred('start', handler=MyCharm._on_start)
deferred_relation_created = Relation('foo').changed_event.deferred(handler=MyCharm._on_foo_relation_changed)
deferred_config_changed = DeferredEvent(
    handle_path='MyCharm/on/config_changed[1]',
    owner='MyCharm',
    observer='_on_config_changed'
)

# Scenario 7.x
deferred_start = ctx.on.start().deferred(handler=MyCharm._on_start)
deferred_relation_changed = ctx.on.relation_changed(Relation('foo')).deferred(handler=MyCharm._on_foo_relation_changed)
deferred_config_changed = ctx.on.config_changed().deferred(handler=MyCharm._on_config_changed)
```

### Update names: State.storages, State.stored_states, Container.execs, Container.service_statuses

The `State.storage` and `State.stored_state` attributes are now plurals. This
reflects that you may have more than one in the state, and also aligns with the
other State components.

```python
# Older Scenario code
state = State(stored_state=[ss1, ss2], storage=[s1, s2])

# Scenario 7.x
state = State(stored_states={s1, s2}, storages={s1, s2})
```

Similarly, `Container.exec_mocks` is now named `Container.execs`,
`Container.service_status` is now named `Container.service_statuses`, and
`ExecOutput` is now named `Exec`.

```python
# Older Scenario code
container = Container(
    name="foo",
    exec_mock={("ls", "-ll"): ExecOutput(return_code=0, stdout=....)},
    service_status={"srv1": ops.pebble.ServiceStatus.ACTIVE}
)

# Scenario 7.x
container = Container(
    name="foo",
    execs={Exec(["ls", "-ll"], return_code=0, stdout=....)},
    service_statuses={"srv1": ops.pebble.ServiceStatus.ACTIVE},
)
```

### Don't use `Event`, or `StoredState.data_type_name`

Several attributes and classes that were never intended for end users have been
made private:

* The `data_type_name` attribute of `StoredState` is now private.
* The `Event` class is now private.

### Use Catan rather than `scenario.sequences`

The `scenario.sequences` module has been removed. We encourage you to look at
the new [Catan](https://github.com/PietroPasotti/catan) package.

### Use the jsonpatch library directly

The `State.jsonpatch_delta()` and `state.sort_patch()` methods have been
removed. We are considering adding delta-comparisons of state again in the
future, but have not yet decided how this will look. In the meantime, you can
use the jsonpatch package directly if necessary. See the tests/helpers.py file
for an example.

### Remove calls to `cleanup`/`clear`

The `Context.cleanup()` and `Context.clear()` methods have been removed. You
do not need to manually call any cleanup methods after running an event. If you
want a fresh `Context` (e.g. with no history), you should create a new object.

### Include secrets in the state only if the charm has permission to view them

`Secret.granted` has been removed. Only include in the state the secrets that
the charm has permission to (at least) view.

### Use 'app' for application-owned secrets

`Secret.owner` should be `'app'` (or `'unit'` or `None`) rather than
`'application'`.

### Compare statuses with status objects

It is no longer possible to compare statuses with tuples. Create the appropriate
status object and compare to that. Note that you should always compare statuses
with `==` not `is`.

### Pass the name of the container to `State.get_container`

The `State.get_container` method previously allowed passing in a `Container`
object or a container name, but now only accepts a name. This is more consistent
with the other new `get_*` methods, some of which would be quite complex if they
accepted an object or key.

### Use `State.storages` to get all the storages in the state

The `State.get_storages` method has been removed. This was primarily intended
for internal use. You can use `State.get_storage` or iterate through
`State.storages` instead.

### Use .replace() to change can_connect, leader, and unit_status

The `State` class previously had convenience methods `with_can_connect`,
`with_leadership`, and `with_unit_status`. You should now use the regular
`.replace()` mechanism instead.

```python
# Older Scenario code
new_state = state.with_can_connect(container_name, can_connect=True)
new_state = state.with_leadership(leader=True)
new_state = state.with_unit_status(status=ActiveStatus())

# Scenario 7.x
new_container = dataclasses.replace(container, can_connect=True)
new_state = dataclasses.replace(containers={container})
new_state = dataclasses.replace(state, leader=True)
new_state = dataclasses.replace(state, status=ActiveStatus())
```

### Let Scenario handle the relation, action, and notice IDs, and storage index

Scenario previously had `next_relation_id`, `next_action_id`,
`next_storage_index`, and `next_notice_id` methods. You should now let Scenario
manage the IDs and indexes of these objects.

### Get the output state from the run() call

The `Context` class previously had an `output_state` attribute that held the
most recent output state. You should now get the output state from the `run()`
return value.

### Don't use internal details

The `*_SUFFIX`, and `_EVENTS` names, the `hook_tool_output_fmt()` methods, the
`normalize_name` method, the `DEFAULT_JUJU_VERSION` and `DEFAULT_JUJU_DATABAG`
names have all been removed, and shouldn't need replacing.

The `capture_events` and `consistency_checker` modules are also no longer
available for public use - the consistency checker will still run automatically,
and the `Context` class has attributes for capturing events.

The `AnyRelation` and `PathLike` names have been removed: use `RelationBase` and
`str | Path` instead.
