(integrate-your-charm-with-postgresql)=
# Integrate your charm with PostgreSQL

> <small> {ref}`From Zero to Hero: Write your first Kubernetes charm <from-zero-to-hero-write-your-first-kubernetes-charm>` > Integrate your charm with PostgreSQL</small>
>
> **See previous: {ref}`Make your charm configurable <make-your-charm-configurable>`**

````{important}

This document is part of a  series, and we recommend you follow it in sequence.  However, you can also jump straight in by checking out the code from the previous chapter:

```text
git clone https://github.com/canonical/operator.git
cd operator/examples/k8s-2-configurable
```

````

A charm often requires or supports relations to other charms. For example, to make our application fully functional we need to connect it to the database. In this chapter of the tutorial we will update our charm so that it can be integrated with the existing [PostgreSQL charm](https://charmhub.io/postgresql-k8s?channel=14/stable).

## Fetch the required database interface charm library

In `charmcraft.yaml`, add a `charm-libs` section before the `containers` section:

```yaml
charm-libs:
  - lib: data_platform_libs.data_interfaces
    version: "0"
```

This tells Charmcraft that your charm requires the [`data_interfaces`](https://charmhub.io/data-platform-libs/libraries/data_interfaces) charm library from Charmhub.

Next, run the following command to download the library:

```text
ubuntu@juju-sandbox-k8s:~/fastapi-demo$ charmcraft fetch-libs
```

When you run this command, you might see a warning:

```text
WARNING: Cannot get a keyring. Every store interaction that requires authentication will require you to log in again.
```

You won't need to authenticate with Charmhub, so you can ignore the warning.

After Charmcraft has downloaded the library, your project directory contains a `lib` directory:

```text
lib
└── charms
    └── data_platform_libs
        └── v0
            └── data_interfaces.py
```

Well done, you've got everything you need to set up a database relation!

## Define the charm relation interface

Now, time to define the charm relation interface.

First, find out the name of the interface that PostgreSQL offers for other charms to connect to it. According to the [documentation of the PostgreSQL charm](https://charmhub.io/postgresql-k8s?channel=14/stable), the interface is called `postgresql_client`.

Next, open the `charmcraft.yaml` file of your charm and, before the `charm-libs` section, define a relation endpoint using a `requires` block, as below. This endpoint says that our charm is requesting a relation called `database` over an interface called `postgresql_client` with a maximum number of supported connections of 1. (Note: Here, `database` is a custom relation name, though in general we recommend sticking to default recommended names for each charm.)

```yaml
requires:
  database:
    interface: postgresql_client
    limit: 1
    optional: false
```

That will tell `juju` that our charm can be integrated with charms that provide the same `postgresql_client` interface, for example, the official PostgreSQL charm.

Import the database interface library and define database event handlers

We now need to implement the logic that wires our application to a database. When a relation between our application and the data platform is formed, the provider side (that is: the data platform) will create a database for us and it will provide us with all the information we need to connect to it over the relation -- for example, username, password, host, port, and so on. On our side, we nevertheless still need to set the relevant environment variables to point to the database and restart the service.

To do so, we need to update our charm `src/charm.py` to do all of the following:

* Import the `DataRequires` class from the interface library; this class represents the relation data exchanged in the client-server communication.
* Define the event handlers that will be called during the relation lifecycle.
* Bind the event handlers to the observed relation events.

### Import the database interface library

At the top of `src/charm.py`, import the database interfaces library:

```python
# Import the 'data_interfaces' library.
# The import statement omits the top-level 'lib' directory
# because 'charmcraft pack' copies its contents to the project root.
from charms.data_platform_libs.v0.data_interfaces import (
    DatabaseCreatedEvent,
    DatabaseEndpointsChangedEvent,
    DatabaseRequires,
)
```

````{important}

You might have noticed that despite the charm library being placed in the `lib/charms/...`, we are importing it via:

```python
from charms.data_platform_libs ...
```

and not

```python
from lib.charms.data_platform_libs...
```

The former is not resolvable by default but everything works fine when the charm is deployed. Why? Because the `dispatch` script in the packed charm sets the `PYTHONPATH` environment variable to include the `lib` directory when it executes your `src/charm.py` code. This tells Python it can check the `lib` directory when looking for modules and packages at import time.

If you're experiencing issues with your IDE, make sure to set/update `PYTHONPATH` to include the `lib` directory as well.

```bash
# in your project directory (~/k8s-tutorial), set
export PYTHONPATH=lib
# or update
export PYTHONPATH=lib:$PYTHONPATH
```

````

### Add relation event observers

In the `__init__` method, define a new instance of the 'DatabaseRequires' class. This is required to set the right permissions scope for the PostgreSQL charm. It will create a new user with a password and a database with the required name (below, `names_db`), and limit the user permissions to only this particular database (that is, below, `names_db`).


```python
# The 'relation_name' comes from the 'charmcraft.yaml file'.
# The 'database_name' is the name of the database that our application requires.
self.database = DatabaseRequires(self, relation_name="database", database_name="names_db")
```

Next, add event observers for all the database events:

```python
# See https://charmhub.io/data-platform-libs/libraries/data_interfaces
framework.observe(self.database.on.database_created, self._on_database_endpoint)
framework.observe(self.database.on.endpoints_changed, self._on_database_endpoint)
```

Finally, define the method that is called on the database events:

```python
def _on_database_endpoint(
    self, _: DatabaseCreatedEvent | DatabaseEndpointsChangedEvent
) -> None:
    """Event is fired when the database is created or its endpoint is changed."""
    self._replan_workload()
```

We now need to make sure that our application knows how to access the database.

### Fetch the database authentication data

Our application consumes database authentication data in the form of environment variables. Let's define a method that prepares database authentication data in that form:

```python
def get_app_environment(self) -> dict[str, str]:
    """Return a dictionary of environment variables for the application."""
    db_data = self.fetch_database_relation_data()
    if not db_data:
        return {}
    return {
        "DEMO_SERVER_DB_HOST": db_data["db_host"],
        "DEMO_SERVER_DB_PORT": db_data["db_port"],
        "DEMO_SERVER_DB_USER": db_data["db_username"],
        "DEMO_SERVER_DB_PASSWORD": db_data["db_password"],
    }
```

This method depends on the following method, which extracts the database authentication data:

```python
def fetch_database_relation_data(self) -> dict[str, str]:
    """Retrieve relation data from a database."""
    relations = self.database.fetch_relation_data()
    logger.debug("Got following database data: %s", relations)
    for data in relations.values():
        if not data:
            continue
        logger.info("New database endpoint is %s", data["endpoints"])
        host, port = data["endpoints"].split(":")
        db_data = {
            "db_host": host,
            "db_port": port,
            "db_username": data["username"],
            "db_password": data["password"],
        }
        return db_data
    return {}
```

### Share the authentication data with your application

Let's change the Pebble service definition to include a dynamic `environment` key.

First, update `_replan_workload()` to provide environment variables when creating the Pebble layer:

```python
def _replan_workload(self) -> None:
    """Define and start a workload using the Pebble API.

    You'll need to specify the right entrypoint and environment
    configuration for your specific workload. Tip: you can see the
    standard entrypoint of an existing container using docker inspect
    Learn more about interacting with Pebble at
        https://documentation.ubuntu.com/ops/latest/reference/pebble/
    Learn more about Pebble layers at
        https://documentation.ubuntu.com/pebble/how-to/use-layers/
    """
    # Learn more about statuses at
    # https://documentation.ubuntu.com/juju/3.6/reference/status/
    self.unit.status = ops.MaintenanceStatus("Assembling Pebble layers")
    try:
        config = self.load_config(FastAPIConfig)
    except ValueError as e:
        logger.error("Configuration error: %s", e)
        return
    env = self.get_app_environment()
    try:
        self.container.add_layer(
            "fastapi_demo",
            self._get_pebble_layer(config.server_port, env),
            combine=True,
        )
        logger.info("Added updated layer 'fastapi_demo' to Pebble plan")

        # Tell Pebble to incorporate the changes, including restarting the
        # service if required.
        self.container.replan()
        logger.info(f"Replanned with '{self.pebble_service_name}' service")
    except (ops.pebble.APIError, ops.pebble.ConnectionError) as e:
        logger.info("Unable to connect to Pebble: %s", e)
```

We removed three `self.unit.status = ` lines from this version of the method. We'll handle replacing those shortly.

Next, update `_get_pebble_layer()` to put the environment variables in the Pebble layer:

```python
def _get_pebble_layer(self, port: int, environment: dict[str, str]) -> ops.pebble.Layer:
    """Pebble layer for the FastAPI demo services."""
    command = " ".join(
        [
            "uvicorn",
            "api_demo_server.app:app",
            "--host=0.0.0.0",
            f"--port={port}",
        ]
    )
    pebble_layer: ops.pebble.LayerDict = {
        "summary": "FastAPI demo service",
        "description": "pebble config layer for FastAPI demo server",
        "services": {
            self.pebble_service_name: {
                "override": "replace",
                "summary": "fastapi demo",
                "command": command,
                "startup": "enabled",
                "environment": environment,
            }
        },
    }
    return ops.pebble.Layer(pebble_layer)
```

With these changes, we've made sure that our application knows how to access the database.

When Pebble starts or restarts the service:

* If there's a database relation and database authentication data is available from the relation, our application can get the database authentication data from environment variables.
* Otherwise, the service environment is empty, so our application can't get database authentication data. In this case, we'd like the unit to show `blocked` or `maintenance` status, depending on whether the Juju user needs to take action.

We'll now make sure that the unit status is set correctly.

(integrate-your-charm-with-postgresql-update-unit-status)=
## Update the unit status to reflect the relation state

Now that the charm is getting more complex, there are many more cases where the unit status needs to be set. It's often convenient to do this in a more declarative fashion, which is where the collect-status event can be used.

> Read more: [](ops.CollectStatusEvent)

In your charm's `__init__` add a new observer:

```python
# Report the unit status after each event.
framework.observe(self.on.collect_unit_status, self._on_collect_status)
```

And define a method that does the various checks, adding appropriate statuses. The library will take care of selecting the 'most significant' status for you.

```python
def _on_collect_status(self, event: ops.CollectStatusEvent) -> None:
    try:
        self.load_config(FastAPIConfig)
    except ValueError as e:
        event.add_status(ops.BlockedStatus(str(e)))
    if not self.model.get_relation("database"):
        # We need the user to do 'juju integrate'.
        event.add_status(ops.BlockedStatus("Waiting for database relation"))
    elif not self.database.fetch_relation_data():
        # We need the charms to finish integrating.
        event.add_status(ops.WaitingStatus("Waiting for database relation"))
    try:
        status = self.container.get_service(self.pebble_service_name)
    except (ops.pebble.APIError, ops.pebble.ConnectionError, ops.ModelError):
        event.add_status(ops.MaintenanceStatus("Waiting for Pebble in workload container"))
    else:
        if not status.is_running():
            event.add_status(ops.MaintenanceStatus("Waiting for the service to start up"))
    # If nothing is wrong, then the status is active.
    event.add_status(ops.ActiveStatus())
```

We also want to clean up the code to remove the places where we're setting the status outside of this method, other than anywhere we're wanting a status to show up *during* the event execution (such as `MaintenanceStatus`). If you missed doing so above, in `_replan_workload`, remove the lines:

```python
self.unit.status = ops.ActiveStatus()
```

```python
self.unit.status = ops.MaintenanceStatus("Waiting for Pebble in workload container")
```

```python
self.unit.status = ops.BlockedStatus(str(e))
```

## Validate your charm

Time to check the results!

First, repack and refresh your charm:

```text
charmcraft pack
juju refresh \
  --path="./fastapi-demo_amd64.charm" \
  fastapi-demo --force-units --resource \
  demo-server-image=ghcr.io/canonical/api_demo_server:1.0.2
```

Next, deploy the `postgresql-k8s` charm:

```text
juju deploy postgresql-k8s --channel=14/stable --trust
```

Now,  integrate our charm with the newly deployed `postgresql-k8s` charm:

```text
juju integrate postgresql-k8s fastapi-demo
```

> Read more: {external+juju:ref}`Juju | Relation (integration) <relation>`, [`juju integrate`](inv:juju:std:label#command-juju-integrate)

Finally, run:

```text
juju status --relations --watch 1s
```

You should see both applications get to the `active` status, and also that the `postgresql-k8s` charm has a relation to the `fastapi-demo` over the `postgresql_client` interface, as below:

```text
Model    Controller     Cloud/Region  Version  SLA          Timestamp
testing  concierge-k8s  k8s           3.6.13   unsupported  13:50:39+01:00

App             Version  Status  Scale  Charm           Channel    Rev  Address         Exposed  Message
fastapi-demo             active      1  fastapi-demo                 2  10.152.183.233  no
postgresql-k8s  14.15    active      1  postgresql-k8s  14/stable  495  10.152.183.195  no

Unit               Workload  Agent  Address      Ports  Message
fastapi-demo/0*    active    idle   10.1.157.90
postgresql-k8s/0*  active    idle   10.1.157.92         Primary

Integration provider           Requirer                       Interface          Type     Message
postgresql-k8s:database        fastapi-demo:database          postgresql_client  regular
postgresql-k8s:database-peers  postgresql-k8s:database-peers  postgresql_peers   peer
postgresql-k8s:restart         postgresql-k8s:restart         rolling_op         peer
postgresql-k8s:upgrade         postgresql-k8s:upgrade         upgrade            peer
```

The relation appears to be up and running, but we should also test that it's working as intended. First, let's try to write something to the database by posting some name to the database via API using `curl` as below -- where `10.1.157.90` is a pod IP and `8000` is our app port. You can repeat the command for multiple names.

```text
curl -X 'POST' \
  'http://10.1.157.90:8000/addname/' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -d 'name=maksim'
```

```{important}

If you changed the `server-port` config value in the previous chapter, don't forget to change it back to 8000 before doing this!
```

Second, let's try to read something from the database by running:

```text
curl 10.1.157.90:8000/names
```

This should produce something similar to the output below (of course, with the names that *you* decided to use):

```text
{"names":{"1":"maksim","2":"simon"}}
```

Congratulations, your relation with PostgreSQL is functional!

## Write unit tests

Now that our charm uses `fetch_database_relation_data` to extract database authentication data and endpoint information from the relation data, we should write a test for the feature. Here, we're not testing the `fetch_database_relation_data` function directly, but rather, we're checking that the response to a Juju event is what it should be:

```python
def test_relation_data():
    ctx = testing.Context(FastAPIDemoCharm)
    relation = testing.Relation(
        endpoint="database",
        interface="postgresql_client",
        remote_app_name="postgresql-k8s",
        remote_app_data={
            "endpoints": "example.com:5432",
            "username": "foo",
            "password": "bar",
        },
    )
    container = testing.Container(name="demo-server", can_connect=True)
    state_in = testing.State(
        containers={container},
        relations={relation},
        leader=True,
    )

    state_out = ctx.run(ctx.on.relation_changed(relation), state_in)

    assert state_out.get_container(container.name).layers["fastapi_demo"].services[
        "fastapi-service"
    ].environment == {
        "DEMO_SERVER_DB_HOST": "example.com",
        "DEMO_SERVER_DB_PORT": "5432",
        "DEMO_SERVER_DB_USER": "foo",
        "DEMO_SERVER_DB_PASSWORD": "bar",
    }
```

In this chapter, we also defined a new method `_on_collect_status` that checks various things, including whether the required database relation exists. If the relation doesn't exist, we wait and set the unit status to `blocked`. We can also add a test to cover this behaviour:

```python
def test_no_database_blocked():
    ctx = testing.Context(FastAPIDemoCharm)
    container = testing.Container(name="demo-server", can_connect=True)
    state_in = testing.State(
        containers={container},
        leader=True,
    )  # We've omitted relation data from the input state.

    state_out = ctx.run(ctx.on.collect_unit_status(), state_in)

    assert state_out.unit_status == testing.BlockedStatus("Waiting for database relation")
```

Then modify `test_pebble_layer`. Since `test_pebble_layer` doesn't arrange a database relation, the unit will be in `blocked` status instead of `active`. Replace the `assert state_out.unit_status` line by:

```python
    # Check the unit is blocked:
    assert state_out.unit_status == testing.BlockedStatus("Waiting for database relation")
```

Now run `tox -e unit` to make sure all test cases pass.

## Write an integration test

Now that our charm integrates with the database, if there's not a database relation, the app will be in `blocked` status instead of `active`. Let's tweak our existing integration test `test_deploy` accordingly, setting the expected status as `blocked` in `juju.wait`:

```python
import logging
import pathlib

import jubilant
import yaml

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(pathlib.Path("./charmcraft.yaml").read_text())
APP_NAME = METADATA["name"]


def test_deploy(charm: pathlib.Path, juju: jubilant.Juju):
    """Deploy the charm under test.

    Assert on the unit status before any relations/configurations take place.
    """
    resources = {
        "demo-server-image": METADATA["resources"]["demo-server-image"]["upstream-source"]
    }

    # Deploy the charm and wait for it to report blocked, as it needs Postgres.
    juju.deploy(f"./{charm}", app=APP_NAME, resources=resources)
    juju.wait(jubilant.all_blocked)
```

Then, let's add another test case to check the integration is successful. For that, we need to deploy a database to the test cluster and integrate both applications. If everything works as intended, the charm should report an active status.

In your `tests/integration/test_charm.py` file add the following test case:

```python
def test_database_integration(juju: jubilant.Juju):
    """Verify that the charm integrates with the database.

    Assert that the charm is active if the integration is established.
    """
    juju.deploy("postgresql-k8s", channel="14/stable", trust=True)
    juju.integrate(APP_NAME, "postgresql-k8s")
    juju.wait(jubilant.all_active)
```

In your Multipass Ubuntu VM, run the test again:

```text
ubuntu@juju-sandbox-k8s:~/fastapi-demo$ tox -e integration
```

The test may again take some time to run.

When it's done, the output should show two passing tests:

```text
tests/integration/test_charm.py::test_deploy
...
INFO     jubilant.wait:_juju.py:1164 wait: status changed:
- .apps['fastapi-demo'].units['fastapi-demo/0'].juju_status.current = 'executing'
- .apps['fastapi-demo'].units['fastapi-demo/0'].juju_status.message = 'running start hook'
+ .apps['fastapi-demo'].units['fastapi-demo/0'].juju_status.current = 'idle'
PASSED
```

```text
tests/integration/test_charm.py::test_database_integration
...
INFO     jubilant.wait:_juju.py:1164 wait: status changed:
- .apps['postgresql-k8s'].app_status.current = 'waiting'
- .apps['postgresql-k8s'].app_status.message = 'awaiting for cluster to start'
+ .apps['postgresql-k8s'].app_status.current = 'active'
+ .apps['postgresql-k8s'].app_status.message = 'Primary'
- .apps['postgresql-k8s'].units['postgresql-k8s/0'].workload_status.current = 'waiting'
- .apps['postgresql-k8s'].units['postgresql-k8s/0'].workload_status.message = 'awaiting for cluster to start'
+ .apps['postgresql-k8s'].units['postgresql-k8s/0'].workload_status.current = 'active'
+ .apps['postgresql-k8s'].units['postgresql-k8s/0'].workload_status.message = 'Primary'
PASSED
```

Congratulations, with this integration test you have verified that your charm's relation to PostgreSQL works as well!

## Review the final code

For the full code, see [our example charm for this chapter](https://github.com/canonical/operator/tree/main/examples/k8s-3-postgresql).

> **See next: {ref}`Expose your charm's operational tasks via actions <expose-operational-tasks-via-actions>`**
