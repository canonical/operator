(manage-libraries)=
# How to manage libraries

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

(manage-libraries-write-a-library)=
## Write a library

When you're writing libraries, instead of callbacks, use custom events. This results in a more Ops-native-feeling API. From a technical standpoint, a custom event is an [](ops.EventBase) subclass that can be emitted to Ops at any point throughout the charm's lifecycle. These events are totally unknown to Juju. They are essentially charm-internal, and can be useful to abstract certain conditional workflows and wrap the top level Juju event so it can be observed independently.

```{important}
Charms should never define custom events themselves. They have no need for
emitting events (custom or otherwise) for their own consumption, and as they
lack consumers, they don’t need to emit any for others to consume either.
Custom events should only be defined and emitted in a library.
```

Custom events must inherit from `EventBase`, but not from an Ops subclass of
`EventBase`, such as `RelationEvent`. When instantiating the custom event, load
any data needed from Juju from the originating event, and explicitly pass that
to the custom event object.

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
    ready = ops.EventSource(DatabaseReadyEvent)


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

```{admonition} Best practice
:class: hint

Libraries should never mutate the status of a unit or application. Instead, use
return values, or raise exceptions and let them bubble back up to the charm for
the charm author to handle as they see fit.
```

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

### Write a library that manages a relation interface

First, for a new interface, design the interface and the process that related charms
will use to populate the relation data. In the simplest case, the providing
charm might populate the local app data when the relation is created, but a
conversation between the charms is more common. In a conversation, the requiring charm will
populate its local data with a request, and the providing charm will use that to
provide a suitable response. In more complex cases, this conversation might have
multiple stages.

> See more: {ref}`manage-interfaces`

If the library is implementing an existing interface, find the interface documentation by following links from the Integrations tab on Charmhub, or by navigating to `https://charmhub.io/integrations/{integration-name}`.
Alternatively, the interface documentation can be found in the
[charm-relation-interfaces](https://github.com/canonical/charm-relation-interfaces)
repository.

In the interface documentation, find the description of the various
databags. For example, for
[v2 of the `tracing` interface](https://github.com/canonical/charm-relation-interfaces/blob/main/interfaces/tracing/v2/README.md):

```yaml
# unit_data: <empty>
application_data:
  receivers:
    - protocol:
        name: otlp_http
        type: http
      url: http://traefik_address:2331
    - protocol:
        name: otlp_grpc
        type: grpc
      url: traefik_address:2331
```

Use this to create Python classes that model the databags. In many cases, there
will already be appropriate classes in the interface documentation. Continuing
with the `tracing` example:

```python
class TransportProtocolType(enum.Enum):
    """Receiver Type."""
    HTTP = "http"
    GRPC = "grpc"


class ProtocolType(pydantic.BaseModel):
    """Protocol Type."""
    name: str = pydantic.Field(
        description="Receiver protocol name. What protocols are supported (and what they are called) "
        "may differ per provider.",
        examples=["otlp_grpc", "otlp_http", "tempo_http", "jaeger_thrift_compact"],
    )
    type: TransportProtocolType = pydantic.Field(
        description="The transport protocol used by this receiver.",
        examples=["http", "grpc"],
    )


class Receiver(pydantic.BaseModel):
    """Specification of an active receiver."""
    protocol: ProtocolType = pydantic.Field(description="Receiver protocol name and type.")
    url: str = pydantic.Field(
        description="""URL at which the receiver is reachable. If there's an ingress, it would be the external URL.
        Otherwise, it would be the service's fqdn or internal IP.
        If the protocol type is grpc, the url will not contain a scheme.""",
        examples=[
            "http://traefik_address:2331",
            "https://traefik_address:2331",
            "http://tempo_public_ip:2331",
            "https://tempo_public_ip:2331",
            "tempo_public_ip:2331",
        ],
    )


class TracingProviderAppData(pydantic.BaseModel):
    receivers: list[Receiver] = pydantic.Field(
        description="A list of enabled receivers in the form of the protocol they use and their resolvable server url.",
    )
```

```{tip}
The Ops [](ops.Relation.load) and [](ops.Relation.save) methods serialise and deserialise the values
of each field, and default to using JSON, so you do not need to wrap fields in `pydantic.Json`.
```

In your `src/charm.py` file, use the class you created to load and save data from the
relation:

```python
receiver_protocol_to_transport_protocol: dict[str, TransportProtocolType] = {
    "zipkin": TransportProtocolType.HTTP,
    "otlp_grpc": TransportProtocolType.GRPC,
    "otlp_http": TransportProtocolType.HTTP,
    "jaeger_thrift_http": TransportProtocolType.HTTP,
    "jaeger_grpc": TransportProtocolType.GRPC,
}

def _publish_provider(self, relation: ops.Relation, receivers: Iterable[tuple[str, str]]):
    data = TracingProviderAppData(
        receivers=[
            Receiver(
                url=url,
                protocol=ProtocolType(
                    name=protocol,
                    type=receiver_protocol_to_transport_protocol[protocol],
                ),
            )
            for protocol, url in receivers
        ],
    )
    relation.save(data, self._charm.app)
```

> See more: [](ops.Relation.save)
