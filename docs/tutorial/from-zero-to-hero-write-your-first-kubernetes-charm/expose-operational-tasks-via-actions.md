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

```{literalinclude} ../../../examples/k8s-4-action/charmcraft.yaml
:language: yaml
:start-at: 'actions:'
:end-at: 'additionalProperties: false'
```

## Define an action class

Open your `src/charm.py` file, and add an action class that matches the definition you used in `charmcraft.yaml`:

```{literalinclude} ../../../examples/k8s-4-action/src/charm.py
:language: python
:pyobject: GetDbInfoAction
```

We'll use [](ActionEvent.load_params) to create an instance of your config class from the Juju action event. This allows IDEs to provide hints when we are accessing the action parameter, and static type checkers are able to validate that we are using the parameter correctly.

## Define the action event handlers

Open the `src/charm.py` file.

In the  charm  `__init__` method, add an action event observer, as below. As you can see, the name of the event consists of the name defined in the `charmcraft.yaml` file (`get-db-info`) and the word `action`.

```{literalinclude} ../../../examples/k8s-4-action/src/charm.py
:language: python
:start-at: "# Events on charm actions that are run via 'juju run'."
:end-at: framework.observe(self.on.get_db_info_action
:dedent:
```

Now, define the action event handler, as below:  First, read the value of the parameter defined in the `charmcraft.yaml` file (`show-password`). Then, use the `fetch_database_relation_data` method (that we defined in a previous chapter) to read the contents of the database relation data and, if the parameter value read earlier is `True`, add the username and password to the output. Finally, use `event.set_results` to attach the results to the event that has called the action; this will print the output to the terminal.

If we are not able to get the data (for example, if the charm has not yet been integrated with the postgresql-k8s application) then we use the `fail` method of the event to let the user know.

```{literalinclude} ../../../examples/k8s-4-action/src/charm.py
:language: python
:pyobject: FastAPIDemoCharm._on_get_db_info_action
:dedent:
```

## Validate your charm

First, repack and refresh your charm:

```text
charmcraft pack
juju refresh fastapi-demo --force-units \
  --path ./fastapi-demo_amd64.charm \
  --resource demo-server-image=ghcr.io/canonical/api_demo_server:1.0.4
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

```{literalinclude} ../../../examples/k8s-4-action/tests/unit/test_charm.py
:language: python
:pyobject: test_get_db_info_action
```

Since the `get_db_info` action has a parameter `show-password`, let's also add a test to cover the case where the user wants to show the password:

```{literalinclude} ../../../examples/k8s-4-action/tests/unit/test_charm.py
:language: python
:pyobject: test_get_db_info_action_show_password
```

Run `tox -e unit` to check that all tests pass.

## Review the final code

For the full code, see [our example charm for this chapter](https://github.com/canonical/operator/tree/main/examples/k8s-4-action).

> **See next: {ref}`Observe your charm with COS Lite <observe-your-charm-with-cos-lite>`**
