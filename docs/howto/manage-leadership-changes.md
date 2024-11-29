(manage-leadership-changes)=
# Manage leadership changes

> See first: [`juju` | Leader](https://juju.is/docs/juju/leader)


## Implement response to leadership changes

### Observe the `leader-elected` event and define an event handler

In the `src/charm.py` file, in the `__init__` function of your charm, set up an observer for the `leader-elected` event and pair that with an event handler. For example:

```python
self.framework.observe(self.on.leader_elected, self._on_leader_elected)
```

> See more: [`ops.LeaderElectedEvent`](https://ops.readthedocs.io/en/latest/#ops.LeaderElectedEvent)

Now, in the body of the charm definition, define the event handler. For example, the handler below will update a configuration file:

```python
def _on_leader_elected(self, event: ops.LeaderElectedEvent):
    self.reconfigure(leader=self.unit)
```

> Examples: [Tempo reconfiguring ingress on leadership change](https://github.com/canonical/tempo-k8s-operator/blob/3f94027b6173f436968a4736a1f2d89a1f17b2e1/src/charm.py#L263), [Kubeflow Dashboard using a holistic handler to configure on leadership change and other events](https://github.com/canonical/kubeflow-dashboard-operator/blob/02caa736a6ea8986b8cba23b63c08a12aaedb86c/src/charm.py#L82)

To have the leader notify other units about leadership changes, change data in a peer relation.

> See more: [Peer Relations](https://juju.is/docs/juju/relation#heading--peer)

{ref}`note status="Use the peer relation rather than `leader-setting-changed`"]
In the past, this was done by observing a `leader-setting-changed` event, which is now deprecated.
[/note]

Commonly, other event handlers will need to check for leadership. For example,
only the leader unit can change charm application secrets, so checks for
leadership are needed to guard against non-leaders. For example:

```python
if self.unit.is_leader():
    secret = self.model.get_secret(label="my-label")
    secret.set_content({"username": "user", "password": "pass"})
```

Note that Juju guarantees leadership for only 30 seconds after a `leader-elected`
event or an `is-leader` check. If the charm code may run longer, then extra
`is_leader()` calls should be made to ensure that the unit is still the leader.

## Test response to leadership changes

> See first: {ref}`get-started-with-charm-testing`


### Write unit tests

> See first: {ref}`write-unit-tests-for-a-charm`

When using Harness for unit tests, use the `set_leader()` method to control whether the unit is the leader. For example, to verify that leadership change is handled correctly:

```python
@pytest.fixture()
def harness():
    yield ops.testing.Harness(MyCharm)
    harness.cleanup()


def test_new_leader(harness):
    # Before the test, the unit is not leader.
    harness.set_leader(False)
    harness.begin()
    # Simulate Juju electing the unit as leader.
    harness.set_leader(True)
    # Assert that it was handled correctly.
    assert ...


def test_leader_sets_secrets(harness):
    # The unit is the leader throughout the test, and no leader-elected event
    # is emitted.
    harness.set_leader(True)
    harness.begin()
    secret_id = harness.add_model_secret(APP_NAME, content={"secret": "sssh"})
    harness.update_config(secret_option=secret_id)
    # Assert that the config-changed handler set additional secret metadata:
    assert ...
```

> See more: [`ops.testing.Harness.set_leader`](https://ops.readthedocs.io/en/latest/harness.html#ops.testing.Harness.set_leader)

## Write scenario tests

> See first: {ref}`write-scenario-tests-for-a-charm`

When using Scenario for unit tests, pass the leadership status to the `State`. For example:

```python
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
    ctx = scenario.Context(MyCharm, meta={"name": "foo"})
    out = ctx.run('start', scenario.State(leader=leader))
    assert out.unit_status == ops.ActiveStatus('I rule' if leader else 'I am ruled')
```


## Write integration tests

> See first: {ref}`write-integration-tests-for-a-charm`

Juju is in sole control over which unit is the leader, so leadership changes are
not usually tested with integration tests. If this is required, then the test
needs to remove the leader unit (machine charms) or run `juju_stop_unit` in the
charm container (Kubernetes charms). The test then needs to wait up to 60 seconds
for Juju to elect a new leader.

More commonly, an integration test might want to verify that leader and non-leader behaviour is
as expected. For example:

```python
async def get_leader_unit(ops_test, app, model=None):
    """Utility method to get the current leader unit."""
    leader_unit = None
    if model is None:
        model = ops_test.model
    for unit in model.applications[app].units:
        if await unit.is_leader_from_status():
            leader_unit = unit
            break

    return leader_unit
```

> Examples: [Zookeeper testing upgrades](https://github.com/canonical/zookeeper-operator/blob/106f9c2cd9408a172b0e93f741d8c9f860c4c38e/tests/integration/test_upgrade.py#L22), [postgresql testing password rotation action](https://github.com/canonical/postgresql-k8s-operator/blob/62645caa89fd499c8de9ac3e5e9598b2ed22d619/tests/integration/test_password_rotation.py#L38)

> See more: [`juju.unit.Unit.is_leader_from_status`](https://pythonlibjuju.readthedocs.io/en/latest/api/juju.unit.html#juju.unit.Unit.is_leader_from_status)

 
