(manage-libraries)=
# Manage libraries

> See first: {external+charmcraft:ref}`Charmcraft | Manage libraries <manage-libraries>`

## Use a library

In your `src/charm.py` file, observe the custom events that the library provides. For example, a database library may have provided a  `ready` event -- a high-level wrapper around the relevant Juju relation events. You can use the `ready` event to manage the database relation in your charm:

```python
import ops
from charms.charm_with_lib.v0.database_lib import DatabaseReadyEvent, DatabaseRequirer


class MyCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self.database = DatabaseRequirer(self, 'db-relation')
        framework.observe(self.database.on.ready, self._on_db_ready)

    def _on_db_ready(self, event: DatabaseReadyEvent):
        secret_content = event.credential_secret.get_content()
        ...
```

A unit test for the charm that uses the database library looks like:

```python
from ops import testing
from charms.charm_with_lib.v0.database_lib import DatabaseRequirer

def test_ready_event():
    ctx = testing.Context(MyCharm)
    secret = testing.Secret({'username': 'admin', 'password': 'admin'})
    state_in = testing.State(secrets={secret})

    state_out = ctx.run(ctx.on.custom(DatabaseRequirer, credential_secret=secret), state_in)

    assert ...
```

## Write a library

When you're writing libraries, instead of callbacks, use custom events. This results in a more Ops-native-feeling API. From a technical standpoint, a custom event is an [](ops.EventBase) subclass that can be emitted to Ops at any point throughout the charm's lifecycle. These events are totally unknown to Juju. They are essentially charm-internal, and can be useful to abstract certain conditional workflows and wrap the top level Juju event so it can be observed independently.

```{important}
Custom events must inherit from `EventBase`, but not from an Ops subclass of
`EventBase`, such as `RelationEvent`. When instantiating the custom event, load
any data needed from Juju from the originating event, and explicitly pass that
to the custom event object.
```

For example, suppose you have a charm library wrapping a relation endpoint. The wrapper might want to check that the remote end has sent valid data and, if that is the case, communicate it to the charm. In this example, you have a `DatabaseRequirer` object, and the charm using it is interested in knowing when the database is ready. In your `lib/charms/my_charm/v0/my_lib.py` file, the `DatabaseRequirer` then will be:

```python
class DatabaseReadyEvent(ops.EventBase):
    """Event representing that the database is ready."""

    def __init__(self, handle: ops.Handle, *, credential_secret: ops.Secret):
        super().__init__(handle)
        self.credential_secret = credential_secret

    def snapshot(self) -> dict[str, str]:
        data = super().snapshot()
        data['credential_secret_id'] = self.credential_secret.id
        return data

    def restore(self, snapshot: dict[str, Any]):
        super().restore(snapshot)
        credential_secret_id = snapshot['credential_secret_id']
        self.credential_secret = self.framework.model.get_secret(id=credential_secret_id)


class DatabaseRequirerEvents(ops.ObjectEvents):
    """Container for Database Requirer events."""
    ready = ops.charm.EventSource(DatabaseReadyEvent)


class DatabaseRequirer(ops.Object):
    on = DatabaseRequirerEvents()

    def __init__(self, charm: ops.CharmBase, relation_name: str):
        super().__init__(charm, relation_name)
        self.framework.observe(charm.on['database'].relation_changed, self._on_db_changed)
    
    def _on_db_changed(self, event: ops.RelationChangedEvent):
        if remote_data_is_valid(event.relation):
            secret = ...
            self.on.ready.emit(credential_secret=secret)
```

## Write tests

### Test that the library initialises

In your `tests/unit/test_my_lib.py` file, add a test that validates that a charm can initialise
the library, and that no events are unexpectedly emitted.

```python
import pytest
import ops
from ops import testing
from lib.charms.my_Charm.v0.my_lib import DatabaseRequirer


class MyTestCharm(ops.CharmBase):
    META = {
        "name": "my-charm"
    }
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self.db = DatabaseRequirer(self, 'my-relation')
        
    
@pytest.mark.parametrize('event', (
    'start', 'install', 'stop', 'remove', 'update-status', #...
))
def test_charm_runs(event):
    """Verify that the charm can create the library object, and doesn't see unexpected events."""
    ctx = testing.Context(MyTestCharm, meta=MyTestCharm.META)
    state_in = testing.State()
    ctx.run(getattr(ctx.on, event), state_in)
    assert len(ctx.emitted_events) == 0
    assert isinstance(ctx.emitted_events[0], ops.StartEvent)
```

### Test custom endpoint names

If `DatabaseRequirer` is a relation endpoint wrapper, a frequent pattern is to
allow customising the name of the endpoint that the object is wrapping.

> Examples: Traefik's [`ingress-per-unit`](https://github.com/canonical/traefik-k8s-operator/blob/main/lib/charms/traefik_k8s/v1/ingress_per_unit.py) lib

In your `tests/unit/test_my_lib.py` file, add a test that validates that custom
names are supported:

```python
import pytest
import ops
from ops import testing
from lib.charms.my_charm.v0.my_lib import DatabaseRequirer


@pytest.fixture(params=["foo", "bar"])
def endpoint(request):
    return request.param


@pytest.fixture
def my_charm_type(endpoint: str):
    class MyTestCharm(ops.CharmBase):
        META = {
            "name": "my-charm",
            "requires":
                {endpoint: {"interface": "my_interface"}}
        }

        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            self.db = DatabaseRequirer(self, endpoint=endpoint)
            framework.observe(self.on.start, self._on_start)
            self.saw_start = False

        def _on_start(self, _):
            self.saw_start = True

    return MyTestCharm


@pytest.fixture
def context(my_charm_type):
    return testing.Context(my_charm_type, meta=my_charm_type.META)


def test_charm_runs(context):
    """Verify that the charm executes regardless of how we name the requirer endpoint."""
    state_in = testing.State()
    with context(context.on.start(), state_in) as mgr:
        mgr.run()
        assert mgr.charm.saw_start
```

### Test that the custom event is emitted

To verify that the library does emit the custom event appropriately,
add a test in your `tests/unit/test_my_lib.py` file:

```python
def test_ready_event():
    ctx = testing.Context(MyTestCharm, meta=MyTestCharm.META)
    relation = testing.Relation('database')
    secret = testing.Secret({'username': 'admin', 'password': 'admin'})
    state_in = testing.State(relations={relation}, secrets={secret})
    ctx.run(ctx.on.relation_changed(relation), state_in)
    relation_changed_event, custom_event = ctx.emitted_events
    assert isinstance(relation_changed_event, ops.RelationChangedEvent)
    assert isinstance(custom_event, DatabaseReadyEvent)
    assert custom_event.credential_secret.id == secret.id
```
