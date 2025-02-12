(manage-libraries)=
# Manage libraries
> See first: {external+charmcraft:ref}`Charmcraft | Manage libraries <manage-libraries>`


## Write a library

When you're writing libraries, instead of callbacks, you can use custom events; that'll result in a more `ops`-native-feeling API. A custom event is, from a technical standpoint, an EventBase subclass that can be emitted at any point throughout the charm's lifecycle. These events are therefore totally unknown to Juju. They are essentially charm-internal, and can be useful to abstract certain conditional workflows and wrap the toplevel Juju event so it can be observed independently.

For example, suppose you have a charm lib wrapping a relation endpoint. The wrapper might want to check that the remote end has sent valid data and, if that is the case, communicate it to the charm. For example, suppose that you have a `DatabaseRequirer` object, and the charm using it is interested in knowing when the database is ready. The `DatabaseRequirer` then will be:

```python
class DatabaseReadyEvent(ops.charm.EventBase):
    """Event representing that the database is ready."""


class DatabaseRequirerEvents(ops.framework.ObjectEvents):
    """Container for Database Requirer events."""
    ready = ops.charm.EventSource(DatabaseReadyEvent)

class DatabaseRequirer(ops.framework.Object):
    on = DatabaseRequirerEvents()

    def __init__(self, charm, ...):
        [...]
        self.framework.observe(self.charm.on.database_relation_changed, self._on_db_changed)
    
    def _on_db_changed(self, e):
        if [...]:  # check remote end has sent valid data
            self.on.ready.emit()
```


## Write tests for a library

In this guide we will go through how to write tests for a charm library we are developing:

`<charm root>/lib/charms/my_charm/v0/my_lib.py`

The intended behaviour of this library (requirer side) is to copy data from the provider app databags and collate it in the own application databag.
The requirer side library does not interact with any lifecycle event; it only listens to relation events.

### Setup

Assuming you have a library file already set up and ready to go (see `charmcraft create-lib` otherwise), you now need to

`pip install ops[testing]` and create a test file in `<charm root>/tests/unit/test_my_lib.py`

### Base test

```python
#  `<charm root>/tests/unit/test_my_lib.py`
import pytest
import ops
from ops import testing
from lib.charms.my_Charm.v0.my_lib import MyObject

class MyTestCharm(ops.CharmBase):
    META = {
        "name": "my-charm"
    }
    def __init__(self, framework):
        super().__init__(framework)
        self.obj = MyObject(self)
        framework.observe(self.on.start, self._on_start)
        
    def _on_start(self, _):
        pass

    
@pytest.fixture
def context():
    return testing.Context(MyTestCharm, meta=MyTestCharm.META)

@pytest.mark.parametrize('event', (
    'start', 'install', 'stop', 'remove', 'update-status', #...
))
def test_charm_runs(context, event):
    """Verify that MyObject can initialise and process any event except relation events."""
    # Arrange:
    state_in = testing.State()
    # Act:
    context.run(getattr(context.on, event), state_in)
```

### Simple use cases

#### Relation endpoint wrapper lib

If `MyObject` is a relation endpoint wrapper such as [`traefik's ingress-per-unit`](https://github.com/canonical/traefik-k8s-operator/blob/main/lib/charms/traefik_k8s/v1/ingress_per_unit.py) lib, a frequent pattern is to allow customizing the name of the endpoint that the object is wrapping. We can write a test like so:

```python
#  `<charm root>/tests/unit/test_my_lib.py`
import pytest
import ops
from ops import testing
from lib.charms.my_Charm.v0.my_lib import MyObject


@pytest.fixture(params=["foo", "bar"])
def endpoint(request):
    return request.param


@pytest.fixture
def my_charm_type(endpoint):
    class MyTestCharm(ops.CharmBase):
        META = {
            "name": "my-charm",
            "requires":
                {endpoint: {"interface": "my_interface"}}
        }

        def __init__(self, framework):
            super().__init__(framework)
            self.obj = MyObject(self, endpoint=endpoint)
            framework.observe(self.on.start, self._on_start)

        def _on_start(self, _):
            pass

    return MyTestCharm


@pytest.fixture
def context(my_charm_type):
    return testing.Context(my_charm_type, meta=my_charm_type.META)


def test_charm_runs(context):
    """Verify that the charm executes regardless of how we name the requirer endpoint."""
    # Arrange:
    state_in = testing.State()
    # Act:
    context.run(context.on.start(), state_in)


@pytest.mark.parametrize('n_relations', (1, 2, 7))
def test_charm_runs_with_relations(context, endpoint, n_relations):
    """Verify that the charm executes when there are one or more relations on the endpoint."""
    # Arrange:
    state_in = testing.State(relations={
        testing.Relation(
            endpoint=endpoint,
            interface='my-interface',
            remote_app_name=f"remote_{n}",
        )
        for n in range(n_relations
    })
    # Act:
    state_out = context.run(context.on.start(), state_in)
    # Assert:
    for relation in state_out.relations:
        assert not relation.local_app_data  # remote side didn't publish any data.


@pytest.mark.parametrize('n_relations', (1, 2, 7))
def test_relation_changed_behaviour(context, endpoint, n_relations):
    """Verify that the charm lib does what it should on relation changed."""
    # Arrange:
    relations = {
        Relation(
            endpoint=endpoint,
            interface='my-interface',
            remote_app_name=f"remote_{n}",
            remote_app_data={"foo": f"my-data-{n}"},
        )
        for n in range(n_relations)
    }
    state_in = testing.State(relations=relations)
    # act
    state_out: testing.State = context.run(context.on.relation_changed(relations[0]), state_in)
    # assert
    for relation in state_out.relations:
        assert relation.local_app_data == {"collation": ';'.join(f"my-data-{n}" for n in range(n_relations))}
```

### Advanced use cases

#### Testing internal (charm-facing) library APIs

Suppose that `MyObject` has a `data` method that exposes to the charm a list containing the remote databag contents (the `my-data-N` we have seen above).
We can use `Context` as a context manager to run code within the lifetime of the Context like so:

```python
import pytest
import ops
from ops import testing
from lib.charms.my_Charm.v0.my_lib import MyObject

@pytest.mark.parametrize('n_relations', (1, 2, 7))
def test_my_object_data(context, endpoint, n_relations):
    """Verify that the charm lib does what it should on relation changed."""
    # Arrange:
    relations = {
        Relation(
            endpoint=endpoint,
            interface='my-interface',
            remote_app_name=f"remote_{n}",
            remote_app_data={"foo": f"my-data-{n}"},
        )
        for n in range(n_relations)
    }
    state_in = testing.State(relations=relations)
    
    with context(context.on.relation_changed(relations[0]), state_in) as mgr:
        # Act:
        state_out = mgr.run()  # this will emit the event on the charm 
        # Control is handed back to us before ops is torn down.

        # Assert:
        charm = mgr.charm  # the MyTestCharm instance ops is working with
        obj: MyObject = charm.obj
        assert obj.data == [
            f"my-data-{n}" for n in range(n_relations)
        ]
```

## Use a library

Fetch the library.

In your `src/charm.py`, observe the custom events it puts at your disposal. For example, a database library may have provided a  `database_relation_ready` event -- a high-level wrapper around the relevant `juju` relation events -- so you use it to manage the database integration in your charm as below:

```python

class MyCharm(CharmBase):
    def __init__(...):
        [...]
        self.db_requirer = DatabaseRequirer(self)
        self.framework.observe(self.db_requirer.on.ready, self._on_db_ready)
```
