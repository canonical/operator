(harness-migration)=
# How to migrate unit tests from Harness

TODO: Introduction, including links to other resources.

(harness-migration-action)=
## Test a minimal action

Suppose that we have the following charm code:

```python
"""A demo charm."""

import ops


class DemoCharm(ops.CharmBase):
    """Manage the workload."""

    def __init__(self, framework: ops.Framework) -> None:
        super().__init__(framework)
        framework.observe(self.on.get_value_action, self._on_get_value_action)
        ...  # Observe other events.

    def _on_get_value_action(self, event: ops.ActionEvent) -> None:
        """Handle the get-value action."""
        if event.params["value"] == "please fail":
            event.fail("Action failed, as requested")
        else:
            event.set_results({"out-value": event.params["value"]})

    ...  # Handle other events.


if __name__ == "__main__":
    ops.main(DemoCharm)
```

Also suppose that we have the following testing code, written using Harness:

```python
from ops import testing

from charm import DemoCharm


def test_action():
    harness = testing.Harness(DemoCharm)

    harness.begin()
    output = harness.run_action("get-value", {"value": "foo"})
    assert output.results == {"out-value": "foo"}

    harness.cleanup()
```

Let's implement this test as a state-transition test.

We'll structure the test around [`Context.on.action`](ops.testing.CharmEvents.action). Our expected input and output states are:

- Before `action` runs -- A generic state. The action doesn't use data from the charm or workload.
- After `action` runs -- A successful action result.

Here's the test:

```python
from ops import testing

from charm import DemoCharm


def test_get_value_action():
    ctx = testing.Context(DemoCharm)

    state_in = testing.State()
    ctx.run(ctx.on.action("get-value", params={"value": "foo"}), state_in)
    assert ctx.action_results == {"out-value": "foo"}
```

While we're here, let's write a test for the action's failure case:

```python
import pytest
from ops import testing

from charm import DemoCharm


def test_get_value_action_failed():
    ctx = testing.Context(DemoCharm)

    state_in = testing.State()
    with pytest.raises(testing.ActionFailed) as exc_info:
        ctx.run(ctx.on.action("get-value", params={"value": "please fail"}), state_in)
    assert exc_info.value.message == "Action failed, as requested"
```

In a more realistic charm, the action will use data from the charm or workload. For an example, see [](#harness-migration-relation). When writing state-transition tests for a real action, we also need to consider collect-status.

(harness-migration-collect-status)=
## Consider collect-status

A significant difference between Harness tests and state-transition tests is how the testing framework handles `collect_unit_status` and `collect_app_status`.

- In a Harness test, you need to trigger these events using [`evaluate_status`](ops.testing.Harness.evaluate_status).
- In a state-transition test, the framework automatically triggers these events. This matches what happens when the charm is deployed.

To demonstrate the difference, let's modify the charm code from [](#harness-migration-action) to include a workload container and observe `collect_unit_status`:

```python
"""A demo charm that has a workload container."""

import ops


class DemoCharm(ops.CharmBase):
    """Manage the workload."""

    def __init__(self, framework: ops.Framework) -> None:
        super().__init__(framework)
        self.container = self.unit.get_container("my-container")
        framework.observe(self.on.collect_unit_status, self._on_collect_status)
        framework.observe(self.on.get_value_action, self._on_get_value_action)
        ...  # Observe other events, including pebble-ready.

    def _on_collect_status(self, event: ops.CollectStatusEvent) -> None:
        """Report the status of the workload."""
        try:
            service = self.container.get_service("workload")
            if not service.is_running():
                event.add_status(ops.MaintenanceStatus("waiting for workload"))
        except (ops.ModelError, ops.pebble.ConnectionError):
            # ModelError: The service wasn't found, likely because we define
            # the service on pebble-ready and that event hasn't happened yet.
            # pebble.ConnectionError: Pebble isn't ready yet, or perhaps the
            # connection to the container is temporarily down.
            event.add_status(ops.MaintenanceStatus("waiting for container"))
        event.add_status(ops.ActiveStatus())

    def _on_get_value_action(self, event: ops.ActionEvent) -> None:
        """Handle the get-value action."""
        if event.params["value"] == "please fail":
            event.fail("Action failed, as requested")
        else:
            event.set_results({"out-value": event.params["value"]})

    ...  # Handle other events, including pebble-ready.


if __name__ == "__main__":
    ops.main(DemoCharm)
```

Our Harness test `test_action` still works (although it doesn't exercise `_on_collect_status`). However, our state-transition test `test_get_value_action` now fails with an error:

```text
FAILED tests/unit/test_charm.py::test_get_value_action -
scenario.errors.UncaughtCharmError: Uncaught RuntimeError in charm, ...
```

When `test_get_value_action` uses `Context.on.action` to simulate running the action, the testing framework also simulates running `_on_collect_status`. Then, when `_on_collect_status` tries to determine the status of the workload, `self.container.get_service("workload")` produces an error because we didn't provide a container to the testing framework.

As a reminder, here's our definition of `test_get_value_action`:

```python
def test_get_value_action():
    ctx = testing.Context(DemoCharm)

    state_in = testing.State()
    ctx.run(ctx.on.action("get-value", params={"value": "foo"}), state_in)
    assert ctx.action_results == {"out-value": "foo"}
```

To fix the test, we need to add a mock container to the input state:

```python
def test_get_value_action():
    ctx = testing.Context(DemoCharm)

    container = testing.Container("my-container", can_connect=True)
    state_in = testing.State(containers={container})
    ctx.run(ctx.on.action("get-value", params={"value": "foo"}), state_in)
    assert ctx.action_results == {"out-value": "foo"}
```

> See more:
>
> - [`testing.Container`](ops.testing.Container)
> - [`testing.State`](ops.testing.State)

In [](#harness-migration-container), we'll work through a more realistic example that shows:

- How to test the pebble-ready event handler.
- How to test the status reporting logic in `_on_collect_status`.

(harness-migration-relation)=
## Test how a relation is handled

### Charm with Harness tests

Suppose that we have the following charm code:

```python
"""A demo charm that requires a database."""

import ops

# Use the 'data_interfaces' library to help integrate with a database provider.
from charms.data_platform_libs.v0.data_interfaces import (
    DatabaseCreatedEvent,
    DatabaseEndpointsChangedEvent,
    DatabaseRequires,
)


class DemoCharm(ops.CharmBase):
    """Manage the workload."""

    def __init__(self, framework: ops.Framework) -> None:
        super().__init__(framework)
        self.database = DatabaseRequires(self, relation_name="database", database_name="my-db")
        framework.observe(self.database.on.database_created, self._on_database_available)
        framework.observe(self.database.on.endpoints_changed, self._on_database_available)
        framework.observe(self.on.get_db_endpoint_action, self._on_get_db_endpoint_action)
        ...  # Observe other events.

    def _on_database_available(
        self, _: DatabaseCreatedEvent | DatabaseEndpointsChangedEvent
    ) -> None:
        """When a database endpoint becomes available or changes, reconfigure the workload."""
        endpoint = self.get_endpoint_from_relation()
        if endpoint:
            self.write_workload_config(endpoint)
            ...  # Ask the workload to reload configuration.

    def _on_get_db_endpoint_action(self, event: ops.ActionEvent) -> None:
        """Handle the get-db-endpoint action."""
        endpoint = self.get_endpoint_from_relation()
        if endpoint:
            event.set_results({"endpoint": endpoint})
        else:
            event.fail("Database endpoint is not available")

    ...  # Handle other events.

    def get_endpoint_from_relation(self) -> str | None:
        """Get the database endpoint from the relation data."""
        relations = self.database.fetch_relation_data()
        for data in relations.values():
            if data:
                return data["endpoints"]

    def write_workload_config(self, config: str) -> None:
        """Update the workload's configuration."""
        ...  # Write a config file. Or in a K8s charm, use Pebble to push config to the container.


if __name__ == "__main__":
    ops.main(DemoCharm)
```

Also suppose that we have the following testing code, written using Harness:

```python
import pytest
from ops import testing

from charm import DemoCharm


class MockWorkload:
    """Mock object that represents the workload."""

    def __init__(self, current_config: str):
        self.config = current_config

    def write_config(self, new_config: str):
        self.config = new_config


def test_db_endpoint(monkeypatch: pytest.MonkeyPatch):
    harness = testing.Harness(DemoCharm)

    # Prepare the charm with initial relation data.
    relation_id = harness.add_relation("database", "postgresql")
    harness.update_relation_data(
        relation_id,
        "postgresql",
        {"endpoints": "foo.local:1234"},
    )
    harness.begin_with_initial_hooks()

    # Prepare a mock workload object with matching config.
    workload = MockWorkload("foo.local:1234")
    monkeypatch.setattr("charm.DemoCharm.write_workload_config", workload.write_config)

    # Update the relation data and check that the charm wrote new workload config.
    harness.update_relation_data(
        relation_id,
        "postgresql",
        {"endpoints": "bar.local:5678"},
    )
    assert workload.config == "bar.local:5678"

    # Check that the action returns the expected database endpoint.
    output = harness.run_action("get-db-endpoint")
    assert output.results == {"endpoint": "bar.local:5678"}

    harness.cleanup()
```

The `test_db_endpoint` function tests the following aspects of the charm:

1. When the relation data changes, the charm writes new workload config.
2. The action returns the correct value from the current relation data.

Let's implement these tests as independent state-transition tests.

### Test a data change

To test what happens when relation data changes, we'll structure a test around [`Context.on.relation_changed`](ops.testing.CharmEvents.relation_changed). Our expected input and output states are:

- Before `relation_changed` runs -- A mock workload object configured with `foo.local:1234`. Relation data `bar.local:5678`.
- After `relation_changed` runs -- The mock workload object configured with `bar.local:5678`.

Here's the test:

```python
import pytest
from ops import testing

from charm import DemoCharm


class MockWorkload:
    """Mock object that represents the workload."""

    def __init__(self, current_config: str):
        self.config = current_config

    def write_config(self, new_config: str):
        self.config = new_config


def test_relation_changed(monkeypatch: pytest.MonkeyPatch):
    ctx = testing.Context(DemoCharm)

    workload = MockWorkload("foo.local:1234")
    monkeypatch.setattr("charm.DemoCharm.write_workload_config", workload.write_config)
    relation = testing.Relation(
        endpoint="database",
        remote_app_data={"endpoints": "bar.local:5678"},
    )
    state_in = testing.State(relations={relation})
    ctx.run(ctx.on.relation_changed(relation), state_in)
    assert workload.config == "bar.local:5678"
```

> See more:
>
> - [`testing.Relation`](ops.testing.Relation)
> - [`testing.State`](ops.testing.State)
> - [How to manage relations > Test the feature](#manage-relations-test-the-feature)

### Test the action

To test the charm's action, we'll structure a test around [`Context.on.action`](ops.testing.CharmEvents.action), as in [](#harness-migration-action). Our expected input and output states are:

- Before `action` runs -- Relation data `bar.local:5678`.
- After `action` runs -- An action result with `bar.local:5678`.

We don't need to use the mock workload object for this test, because the charm doesn't interact with the workload while handling the action. Here's the test:

```python
from ops import testing

from charm import DemoCharm


def test_get_db_endpoint_action():
    ctx = testing.Context(DemoCharm)

    relation = testing.Relation(
        endpoint="database",
        remote_app_data={"endpoints": "bar.local:5678"},
    )
    state_in = testing.State(relations={relation})
    ctx.run(ctx.on.action("get-db-endpoint"), state_in)
    assert ctx.action_results == {"endpoint": "bar.local:5678"}
```

(harness-migration-container)=
## Test how a container is handled

### Charm with Harness tests

Suppose that we have the following charm code:

```python
"""A demo charm that has a workload container."""

import ops


class DemoCharm(ops.CharmBase):
    """Manage the workload."""

    def __init__(self, framework: ops.Framework) -> None:
        super().__init__(framework)
        self.container = self.unit.get_container("my-container")
        framework.observe(self.on["my-container"].pebble_ready, self._on_pebble_ready)
        framework.observe(self.on.collect_unit_status, self._on_collect_status)
        ...  # Observe other events.

    def _on_pebble_ready(self, _: ops.PebbleReadyEvent) -> None:
        """Use Pebble to configure and start the workload in the container."""
        layer: ops.pebble.LayerDict = {
            "services": {
                "workload": {
                    "override": "replace",
                    "command": "run-workload",
                    "startup": "enabled",
                }
            }
        }
        self.container.add_layer("base", layer, combine=True)
        self.container.replan()
        # In a real charm, we should check that the workload is actually
        # running. For example, by trying to connect to it over HTTP.

    def _on_collect_status(self, event: ops.CollectStatusEvent) -> None:
        """Report the status of the workload."""
        try:
            service = self.container.get_service("workload")
            if not service.is_running():
                event.add_status(ops.MaintenanceStatus("waiting for workload"))
        except (ops.ModelError, ops.pebble.ConnectionError):
            # ModelError: The service wasn't found, likely because we define
            # the service on pebble-ready and that event hasn't happened yet.
            # pebble.ConnectionError: Pebble isn't ready yet, or perhaps the
            # connection to the container is temporarily down.
            event.add_status(ops.MaintenanceStatus("waiting for container"))
        event.add_status(ops.ActiveStatus())

    ...  # Handle other events.


if __name__ == "__main__":
    ops.main(DemoCharm)
```

Also suppose that we have the following testing code, written using Harness:

```python
import ops
import pytest
from ops import testing

from charm import DemoCharm


def test_container():
    harness = testing.Harness(DemoCharm)

    # Check that the charm goes into active status when it starts.
    harness.begin_with_initial_hooks()  # Triggers the pebble-ready event.
    harness.evaluate_status()
    assert isinstance(harness.charm.unit.status, ops.model.ActiveStatus)

    # Check the Pebble plan in the workload container.
    plan = harness.get_container_pebble_plan("my-container")
    assert "workload" in plan.services
    assert plan.services["workload"].command == "run-workload"

    # Simulate a dropped connection to the container, then check the charm's status.
    harness.set_can_connect("my-container", False)
    harness.evaluate_status()
    assert isinstance(harness.charm.unit.status, ops.model.MaintenanceStatus)
    assert harness.charm.unit.status.message == "waiting for container"

    harness.cleanup()
```

The `test_container` function tests the following aspects of the charm:

1. The pebble-ready event handler defines the correct service in the workload container.
2. The charm correctly reports active or maintenance status, depending on the status of the container.

Let's implement these tests as independent state-transition tests.

### Test the Pebble setup

To test the pebble-ready event handler, we'll structure a test around [`Context.on.pebble_ready`](ops.testing.CharmEvents.pebble_ready). Our expected input and output states are:

- Before `pebble_ready` runs -- A mock container with `can_connect=True`.
- After `pebble_ready` runs -- A new mock container with the expected Pebble plan.

Here's the test:

```python
from ops import testing

from charm import DemoCharm


def test_pebble_ready():
    ctx = testing.Context(DemoCharm)

    container_in = testing.Container("my-container", can_connect=True)
    state_in = testing.State(containers={container_in})
    state_out = ctx.run(ctx.on.pebble_ready(container_in), state_in)
    container_out = state_out.get_container(container_in.name)
    assert "workload" in container_out.plan.services
    assert container_out.plan.services["workload"].command == "run-workload"
```

When writing a state-transition test, it's best to treat objects as immutable. We shouldn't expect `ctx.run` to modify the mock container that's passed to `ctx.on.pebble_ready`. In other words, this doesn't work:

```python
    ...
    ctx.run(ctx.on.pebble_ready(container_in), state_in)
    assert "workload" in container_in.plan.services  # Fails!
```

> See more:
>
> - [`testing.Container`](ops.testing.Container)
> - [`testing.State`](ops.testing.State)

The `test_pebble_ready` function doesn't fully cover the charm's `_on_pebble_ready` method. In addition to defining a service in the container, `_on_pebble_ready` uses [`replan`](ops.Container.replan) to start the service. To cover this, one option would be to check the service status at the end of `test_pebble_ready`:

```python
    ...
    assert container_out.service_statuses["workload"] == ops.pebble.ServiceStatus.ACTIVE
```

Alternatively, we can take advantage of the charm's status reporting:

```python
    ...
    assert state_out.unit_status == testing.ActiveStatus()
```

This works because the testing framework automatically simulates running `_on_collect_status` after `_on_pebble_ready`, and `_on_collect_status` reports active status if the service is running. With this addition, the full test is:

```python
def test_pebble_ready():
    ctx = testing.Context(DemoCharm)

    container_in = testing.Container("my-container", can_connect=True)
    state_in = testing.State(containers={container_in})
    state_out = ctx.run(ctx.on.pebble_ready(container_in), state_in)
    container_out = state_out.get_container(container_in.name)
    assert "workload" in container_out.plan.services
    assert container_out.plan.services["workload"].command == "run-workload"
    assert state_out.unit_status == testing.ActiveStatus()
```

### Test the status reporting

We already have a test (`test_pebble_ready`) that partially exercises the charm's status reporting, but it's a good idea to independently cover each situation that the status reporting logic accounts for.

Our Harness test uses [`evaluate_status`](ops.testing.Harness.evaluate_status) to trigger `collect_unit_status`, which causes the charm's `_on_collect_status` method to run. In a state-transition test, the best approach is to simulate the update-status event instead.

We'll structure two tests around [`Context.on.update_status`](ops.testing.CharmEvents.update_status).

1. `test_status_active`, with input and output states:
    - Before `update_status` runs -- A mock container with `can_connect=True`, a Pebble plan, and an active service. This matches the state produced by the pebble-ready event handler.
    - After `update_status` runs -- The unit is reporting active status.
2. `test_status_container_down`, with input and output states:
    - Before `update_status` runs -- A mock container with `can_connect=False`.
    - After `update_status` runs -- The unit is reporting maintenance status.

Here are the tests:

```python
from ops import pebble, testing

from charm import DemoCharm

layer = pebble.Layer(
    {
        "services": {
            "workload": {
                "override": "replace",
                "command": "mock-command",
                "startup": "enabled",
            },
        },
    }
)


def test_status_active():
    ctx = testing.Context(DemoCharm)

    container = testing.Container(
        "my-container",
        layers={"base": layer},
        service_statuses={"workload": pebble.ServiceStatus.ACTIVE},
        can_connect=True,
    )
    state_in = testing.State(containers={container})
    state_out = ctx.run(ctx.on.update_status(), state_in)
    assert state_out.unit_status == testing.ActiveStatus()


def test_status_container_down():
    ctx = testing.Context(DemoCharm)

    container = testing.Container("my-container", can_connect=False)
    state_in = testing.State(containers={container})
    state_out = ctx.run(ctx.on.update_status(), state_in)
    assert state_out.unit_status == testing.MaintenanceStatus("waiting for container")
```

These tests cover the same situations as our Harness test, but in isolation, not part of a sequence of events. The biggest difference is in `test_status_active`, where we mock a Pebble layer instead of relying on the layer produced by the pebble-ready event handler.

```{note}
The values in the mock layer don't need to exactly match the layer produced by the pebble-ready event handler. For example, in `test_status_active` we have `"command": "mock-command"` instead of `"command": "run-workload"`. Given our implementation of `_on_collect_status`, it's sufficient for the mock layer to define a service called `workload`. In general, it's good practice to populate a mock layer with values, even if the values themselves aren't important for a test.
```

The status reporting logic in `_on_collect_status` actually accounts for two more situations:

- The container has a Pebble plan, but the service isn't running. To cover this situation, we could add a variant of `test_status_active` that sets the service status to `INACTIVE`.
- The container is available, but doesn't have a Pebble plan. To cover this situation, we could add a variant of `test_status_container_down` that sets `can_connect=True`.
