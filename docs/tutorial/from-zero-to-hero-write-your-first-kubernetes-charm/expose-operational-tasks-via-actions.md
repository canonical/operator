(expose-operational-tasks-via-actions)=
# Expose operational tasks via actions

> <small> {ref}`From Zero to Hero: Write your first Kubernetes charm <from-zero-to-hero-write-your-first-kubernetes-charm>` > Expose operational tasks via actions </small>
>
> **See previous: {ref}`Integrate your charm with PostgreSQL <integrate-your-charm-with-postgresql>`**

````{important}

This document is part of a  series, and we recommend you follow it in sequence.  However, you can also jump straight in by checking out the code from the previous chapter:

```text
git clone https://github.com/canonical/operator.git
cd operator/examples/k8s-3-postgresql
```

````

A charm should ideally cover all the complex operational logic within the code, to help avoid the need for manual human intervention.

Unfortunately, that is not always possible. As a charm developer, it is thus useful to know that you can also expose charm operational tasks to the charm user by defining special methods called `actions`.

This can be done by adding an `actions` section in your `charmcraft.yaml` file and then adding action event handlers to the `src/charm.py` file.

In this part of the tutorial we will follow this process to add an action that will allow a charm user to view the current database access points and, if set, also the username and the password.

## Define the actions

Open the `charmcraft.yaml` file and add to it a block defining an action, as below. As you can see, the  action is called `get-db-info` and it is intended to help the user access database authentication information. The action has a single parameter, `show-password`; if set to `True`, it will show the username and the password.

```yaml
actions:
  get-db-info:
    description: Fetches database authentication information
    params:
      show-password:
        description: Show username and password in output information
        type: boolean
        default: false
    additionalProperties: false
```

## Define an action class

Open your `src/charm.py` file, and add an action class that matches the definition you used in `charmcraft.yaml`:

```python
@dataclasses.dataclass(frozen=True, kw_only=True)
class GetDbInfoAction:
    """Fetches database authentication information."""

    show_password: bool
    """Show username and password in output information."""
```

We'll use [](ActionEvent.load_params) to create an instance of your config class from the Juju action event. This allows IDEs to provide hints when we are accessing the action parameter, and static type checkers are able to validate that we are using the parameter correctly.

## Define the action event handlers

Open the `src/charm.py` file.

In the  charm  `__init__` method, add an action event observer, as below. As you can see, the name of the event consists of the name defined in the `charmcraft.yaml` file (`get-db-info`) and the word `action`.

```python
# Events on charm actions that are run via 'juju run'.
framework.observe(self.on.get_db_info_action, self._on_get_db_info_action)
```

Now, define the action event handler, as below:  First, read the value of the parameter defined in the `charmcraft.yaml` file (`show-password`). Then, use the `fetch_database_relation_data` method (that we defined in a previous chapter) to read the contents of the database relation data and, if the parameter value read earlier is `True`, add the username and password to the output. Finally, use `event.set_results` to attach the results to the event that has called the action; this will print the output to the terminal.

If we are not able to get the data (for example, if the charm has not yet been integrated with the postgresql-k8s application) then we use the `fail` method of the event to let the user know.

```python
def _on_get_db_info_action(self, event: ops.ActionEvent) -> None:
    """Return information about the integrated database.

    This method is called when "get_db_info" action is called. It shows information about
    database access points by calling the `fetch_database_relation_data` method and creates
    an output dictionary containing the host, port, if show_password is True, then include
    username, and password of the database.

    If the PostgreSQL charm is not integrated, the output is set to "No database connected".

    Learn more about actions at https://documentation.ubuntu.com/ops/latest/howto/manage-actions/
    """
    params = event.load_params(GetDbInfoAction, errors="fail")
    db_data = self.fetch_database_relation_data()
    if not db_data:
        event.fail("No database connected")
        return
    output = {
        "db-host": db_data.get("db_host", None),
        "db-port": db_data.get("db_port", None),
    }
    if params.show_password:
        output.update(
            {
                "db-username": db_data.get("db_username", None),
                "db-password": db_data.get("db_password", None),
            }
        )
    event.set_results(output)
```

## Validate your charm

First, repack and refresh your charm:

```text
charmcraft pack
juju refresh \
  --path="./fastapi-demo_amd64.charm" \
  fastapi-demo --force-units --resource \
  demo-server-image=ghcr.io/canonical/api_demo_server:1.0.2
```

Next, test that the basic action invocation works:

```text
juju run fastapi-demo/0 get-db-info
```

It might take a few seconds, but soon you should see an output similar to the one below, showing the database host and port:

```text
Running operation 1 with 1 task
  - task 2 on unit-fastapi-demo-0

Waiting for task 2...
db-host: postgresql-k8s-primary.testing.svc.cluster.local
db-port: "5432"
```

Now, test that the action parameter (`show-password`) works as well by setting it to `True`:

```text
juju run fastapi-demo/0 get-db-info show-password=True
```

The output should now include the username and the password:

```text
Running operation 3 with 1 task
  - task 4 on unit-fastapi-demo-0

Waiting for task 4...
db-host: postgresql-k8s-primary.testing.svc.cluster.local
db-password: RGv80aF9WAJJtExn
db-port: "5432"
db-username: relation_id_4
```

Congratulations, you now know how to expose operational tasks via actions!

## Write unit tests

Let's add a test to check the behaviour of the `get_db_info` action that we just set up. Our test sets up the context, defines the input state with a relation, then runs the action and checks whether the results match the expected values:

```python
def test_get_db_info_action():
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

    ctx.run(ctx.on.action("get-db-info", params={"show-password": False}), state_in)

    assert ctx.action_results == {
        "db-host": "example.com",
        "db-port": "5432",
    }
```

Since the `get_db_info` action has a parameter `show-password`, let's also add a test to cover the case where the user wants to show the password:

```python
def test_get_db_info_action_show_password():
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

    ctx.run(ctx.on.action("get-db-info", params={"show-password": True}), state_in)

    assert ctx.action_results == {
        "db-host": "example.com",
        "db-port": "5432",
        "db-username": "foo",
        "db-password": "bar",
    }
```

Run `tox -e unit` to check that all tests pass.

## Review the final code

For the full code, see [our example charm for this chapter](https://github.com/canonical/operator/tree/main/examples/k8s-4-action).

> **See next: {ref}`Observe your charm with COS Lite <observe-your-charm-with-cos-lite>`**
