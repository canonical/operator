(manage-relations)=
# How to manage relations
> See first: {external+juju:ref}`Juju | Relation <relation>`, {external+juju:ref}`Juju | Manage relations <manage-relations>`, {external+charmcraft:ref}`Charmcraft | Manage relations <manage-relations>`

To add relation capabilities to a charm, you’ll have to define the relation in your charm’s charmcraft.yaml file and then add relation event handlers in your charm’s `src/charm.py` file.

## Implement the feature

### Declare the relation endpoint

To integrate with another charm, or with itself (to communicate with other units of the same charm), declare the required and optional relations in your charm’s `charmcraft.yaml` file.

```{caution}

**If you're using an existing interface:**

Make sure to consult [the `charm-relations-interfaces` repository](https://github.com/canonical/charm-relation-interfaces) for guidance about how to implement them correctly.

**If you're defining a new interface:**

Make sure to add your interface to [the `charm-relations-interfaces` repository](https://github.com/canonical/charm-relation-interfaces).
```

To exchange data with other units of the same charm, define one or more `peers` endpoints including an interface name for each. Each peer relation must have an endpoint, which your charm will use to refer to the relation (as [](ops.Relation.name)).

```yaml
peers:
  replicas:
    interface: charm_gossip
```

To exchange data with another charm, define a `provides` or `requires` endpoint including an interface name. By convention, the interface name should be unique in the ecosystem. Each relation must have an endpoint, which your charm will use to refer to the relation (as [](ops.Relation.name)).

```yaml
provides:
  smtp:
    interface: smtp
```

```yaml
requires:
  db:
    interface: postgresql
    limit: 1
```

Note that implementing a cross-model relation is done in the same way as one between applications in the same model. The ops library does not distinguish between data from a different model or from the same model as the one the charm is deployed to.

Which side of the relation is the “provider” or the “requirer” is often arbitrary, but if one side has a workload that is a server and the other a client, then the server side should be the provider. This becomes important for how Juju sets up network permissions in cross-model relations.

If the relation is with a subordinate charm, make sure to set the `scope` field to `container`.

```yaml
requires:
  log-forwarder:
    interface: rsyslog-forwarder
    scope: container
```

Other than this, implement a subordinate relation in the same way as any other relation. Note however that subordinate units cannot see each other's peer data.

> See also: {external+juju:ref}`Juju | Charm taxonomy <charm-taxonomy>`

### Add code to use a relation

#### Using a charm library

For most relations, you will now want to progress with using the charm library recommended by the charm that you are integrating with. Read the documentation for the other charm on Charmhub and follow the instructions, which will typically involve adding a requirer object in your charm’s `__init__` and then observing custom events.

In most cases, the charm library will handle observing the Juju relation events, and your charm will only need to interact with the library’s custom API. Come back to this guide when you are ready to add tests.

> See more: [Charmhub](https://charmhub.io)

#### Implementing your own interface

If you are developing your own interface - most commonly for charm-specific peer data exchange, then you will need to observe the Juju relation events and add appropriate handlers.

##### Set up a relation

To do initial setup work when a charm is first integrated with another charm (or, in the case of a peer relation, when a charm is first deployed) your charm will need to observe the relation-created event. For example, a charm providing a database relation might need to create the database and credentials, so that the requirer charm can use the database. In the `src/charm.py` file, in the `__init__` function of your charm, set up `relation-created` event observers for the relevant relations and pair those with an event handler.

The name of the event to observe is combined with the name of the endpoint. With an endpoint named “db”, to observe `relation-created`, our code would look like:

```python
framework.observe(self.on.db_relation_created, self._on_db_relation_created)
```

Now, in the body of the charm definition, define the event handler. In this example, if we are the leader unit, then we create a database and pass the credentials to use it to the charm on the other side via the relation data:

```python
def _on_db_relation_created(self, event: ops.RelationCreatedEvent):
    if not self.unit.is_leader():
        return
    credentials = self.create_database(event.app.name)
    event.relation.data[event.app].update(credentials)
```

The event object that is passed to the handler has a `relation` property, which contains an [](ops.Relation) object. Your charm uses this object to find out about the relation (such as which units are included, in the [`.units` attribute](ops.Relation.units), or whether the relation is broken, in the [`.active` attribute](ops.Relation.active)) and to get and set data in the relation databag.

> See more: [](ops.RelationCreatedEvent)

To do additional setup work when each unit joins the relation (both when the charms are first integrated and when additional units are added to the charm), your charm will need to observe the `relation-joined` event. In the `src/charm.py` file, in the `__init__` function of your charm, set up `relation-joined` event observers for the relevant relations and pair those with an event handler. For example:

```python
framework.observe(self.on.smtp_relation_joined, self._on_smtp_relation_joined)
```

Now, in the body of the charm definition, define the event handler. In this example, a “smtp_credentials” key is set in the unit data with the ID of a secret:

```python
def _on_smtp_relation_joined(self, event: ops.RelationJoinedEvent):
    smtp_credentials_secret_id = self.create_smtp_user(event.unit.name)
    event.relation.data[event.unit]["smtp_credentials"] = smtp_credentials_secret_id
```

> See more: [](ops.RelationJoinedEvent)

##### Exchange data with other units

To use data received through the relation, have your charm observe the `relation-changed` event. In the `src/charm.py` file, in the `__init__` function of your charm, set up `relation-changed` event observers for each of the defined relations. For example:

```python
framework.observe(self.on.replicas_relation_changed, self._update_configuration)
```

> See more: [](ops.RelationChangedEvent), {external+juju:ref}`Juju | Relation (integration) <relation>`

Most of the time, you should use the same holistic handler as when receiving other data, such as `secret-changed` and `config-changed`. To access the relation(s) in your holistic handler, use the [](ops.Model.get_relation) method or [](ops.Model.relations) attribute.

> See also: [](/explanation/holistic-vs-delta-charms)

If your change will have at most one relation on the endpoint, to get the `Relation` object use `Model.get_relation`; for example:

```python
rel = self.model.get_relation("db")
if not rel:
    # Handle the case where the relation does not yet exist.
```

If your charm may have multiple relations on the endpoint, to get the relation objects use `Model.relations` rather than `Model.get_relation` with the relation ID; for example:

```python
for rel in self.model.relations.get('smtp', ()):
    # Do something with the relation object.
```

Once your charm has the relation object, it can be used in exactly the same way as when received from an event.

Now, in the body of the charm definition, define the holistic event handler. In this example, we check if the relation exists yet, and for a provided secret using the ID provided in the relation data, and if we have both of those then we push that into a workload configuration:

```python
def _update_configuration(self, _: ops.Eventbase):
    # This handles secret-changed and relation-changed.
    db_relation = self.model.get_relation('db')
    if not db_relation:
        # We’re not integrated with the database charm yet.
        return
    secret_id = db_relation.data[self.model.app]['credentials']
    if not secret_id:
        # The credentials haven’t been added to the relation by the remote app yet.
        return
    secret_contents = self.model.get_secret(id=secret_id).get_contents(refresh=True)
    self.push_configuration(
        username=secret['username'],
        password=secret['password'],
    )
```

##### Exchange data across the various relations

To add data to the relation databag, use the [`.data` attribute](ops.Relation.data) much as you would a dictionary, after selecting whether to write to the app databag (leaders only) or unit databag. For example, to copy a value from the charm config to the relation data:

```python
def _on_config_changed(self, event: ops.ConfigChangedEvent):
    if relation := self.model.get_relation('ingress'):
        relation.data[self.app]["domain"] = self.model.config["domain"]
```

To read data from the relation databag, again use the `.data` attribute, selecting the appropriate databag, and then using it as if it were a regular dictionary.

The charm can inspect the contents of the remote unit databags:

```python
def _on_database_relation_changed(self, event: ops.RelationChangedEvent):
    remote_units_databags = {
        event.relation.data[unit] for unit in event.relation.units if unit.app is not self.app
    }
```

Or the peer unit databags:

```python
def _on_database_relation_changed(self, e: ops.RelationChangedEvent):
    peer_units_databags = {
        event.relation.data[unit] for unit in event.relation.units if unit.app is self.app
    }
```

Or the remote leader databag:

```python
def _on_database_relation_changed(self, event: ops.RelationChangedEvent):
    remote_app_databag = event.relation.data[relation.app]
```

Or the local application databag:

```python
def _on_database_relation_changed(self, event: ops.RelationChangedEvent):
    local_app_databag = event.relation.data[self.app]
```

Or the local unit databag:

```python
def _on_database_relation_changed(self, event: ops.RelationChangedEvent):
    local_unit_databag = event.relation.data[self.unit]
```

If the charm does not have permission to do an operation (e.g. because it is not the leader unit), an exception will be raised.

##### Clean up when a relation is removed

To do clean-up work when a unit in the relation is removed (for example, removing per-unit credentials), have your charm observe the `relation-departed` event. In the `src/charm.py` file, in the `__init__` function of your charm, set up `relation-departed` event observers for the relevant relations and pair those with an event handler. For example:

```python
framework.observe(self.on.smtp_relation_departed, self._on_smtp_relation_departed)
```

Now, in the body of the charm definition, define the event handler. For example:

```python
def _on_smtp_relation_departed(self, event: ops.RelationDepartedEvent):
    if self.unit != event.departing_unit:
        self.remove_smtp_user(event.unit.name)
```

> See more: [](ops.RelationDepartedEvent)

To clean up after a relation is entirely removed, have your charm observe the `relation-broken` event. In the `src/charm.py` file, in the `__init__` function of your charm, set up `relation-broken` events for the relevant relations and pair those with an event handler. For example:

```python
framework.observe(self.on.db_relation_broken, self._on_db_relation_broken)
```

Now, in the body of the charm definition, define the event handler. For example:

```python
def _on_db_relation_broken(self, event: ops.RelationBrokenEvent):
    if not self.is_leader():
        return
    self.drop_database(event.app.name)
```

> See more: [](ops.RelationBrokenEvent)

## Test the feature

### Write unit tests

For each relation event that your charm observes, write at least one test. Create a `Relation` object that defines the relation, include that in the input state, run the relation event, and assert that the output state is what you’d expect. For example:

```python
from ops import testing

ctx = testing.Context(MyCharm)
relation = testing.Relation(endpoint='smtp', remote_units_data={1: {}})
state_in = testing.State(relations=[relation])
state_out = ctx.run(ctx.on.relation_joined(relation, remote_unit_id=1), state=state_in)
assert 'smtp_credentials' in state_out.get_relation(relation.id).remote_units_data[1]
```

> See more: [Scenario Relations](ops.testing.RelationBase)

### Write integration tests

Write an integration test that verifies that your charm behaves as expected in a real Juju environment. Other than when testing peer relations, as well as deploying your own charm, the test needs to deploy a second application, either the real charm or a facade that provides enough functionality to test against.

The pytest-operator plugin provides methods to deploy multiple charms. For example:

```python
# This assumes that your integration tests already include the standard
# build and deploy test that the charmcraft profile provides.

@pytest.mark.abort_on_fail
async def test_active_when_deploy_db_facade(ops_test: OpsTest):
    await ops_test.model.deploy('facade')
    await ops_test.model.integrate(APP_NAME + ':postgresql', 'facade:provide-postgresql')

    present_facade('postgresql', model=ops_test.model_name,
                   app_data={
                       'credentials': 'secret:abc',
                   })

    await ops_test.model.wait_for_idle(
        apps=[APP_NAME],
        status='active',
        timeout=600,
    )
```

> See more: [`pytest-operator`](https://pypi.org/project/pytest-operator/)
