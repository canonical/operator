(expose-operational-tasks-via-actions)=
# Expose operational tasks via actions

> <small> {ref}`From Zero to Hero: Write your first Kubernetes charm <from-zero-to-hero-write-your-first-kubernetes-charm>` > Expose operational tasks via actions </small>
>
> **See previous: {ref}`Preserve your charm's data <preserve-your-charms-data>`** 


````{important}

This document is part of a  series, and we recommend you follow it in sequence.  However, you can also jump straight in by checking out the code from the previous branches:


```text
git clone https://github.com/canonical/juju-sdk-tutorial-k8s.git
cd juju-sdk-tutorial-k8s
git checkout 05_preserve_charm_data
git checkout -b  06_create_actions 
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
    description: Fetches Database authentication information
    params:
      show-password:
        description: "Show username and password in output information"
        type: boolean
        default: False
```


## Define the action event handlers

Open the `src/charm.py` file.

In the  charm  `__init__` method, add an action event observer, as below. As you can see, the name of the event consists of the name defined in the `charmcraft.yaml` file (`get-db-info`) and the word `action`.

```python
# events on custom actions that are run via 'juju run-action'
framework.observe(self.on.get_db_info_action, self._on_get_db_info_action)
```

<!-- I THINK THIS IS IMPLICIT IN THE FACT THAT ACTION EVENT NAMES ARE ACTION-SPECIFIC.
```{important}

 In case of multiple actions defined you need to add a separate observer for each.

```
-->



Now, define the action event handler, as below:  First, read the value of the parameter defined in the `charmcraft.yaml` file (`show-password`). Then, use the `fetch_postgres_relation_data` method (that we defined in a previous chapter) to read the contents of the database relation data and, if the parameter value read earlier is `True`, add the username and password to the output. Finally, use `event.set_results` to attach the results to the event that has called the action; this will print the output to the terminal.

If we are not able to get the data (for example, if the charm has not yet been integrated with the postgresql-k8s application) then we use the `fail` method of the event to let the user know.

<!--
The action will read the contents of the database relation data with the help of the `fetch_postgres_relation_data` method (that we have defined in previous chapter) and output its content.  
As you can see we read the value of the defined parameter `show-password` and only if it is `True` we add username and password to the output.  
To print output to the terminal we need to attach results to the event that has called the action via `event.set_results`.
-->

```python
def _on_get_db_info_action(self, event: ops.ActionEvent) -> None:
    """This method is called when "get_db_info" action is called. It shows information about
    database access points by calling the `fetch_postgres_relation_data` method and creates
    an output dictionary containing the host, port, if show_password is True, then include
    username, and password of the database.
    If PSQL charm is not integrated, the output is set to "No database connected".

    Learn more about actions at https://juju.is/docs/sdk/actions
    """
    show_password = event.params['show-password']  # see charmcraft.yaml
    db_data = self.fetch_postgres_relation_data()
    if not db_data:
        event.fail('No database connected')
        return
    output = {
        'db-host': db_data.get('db_host', None),
        'db-port': db_data.get('db_port', None),
    }
    if show_password:
        output.update(
            {
                'db-username': db_data.get('db_username', None),
                'db-password': db_data.get('db_password', None),
            }
        )
    event.set_results(output)
```

## Validate your charm

First, repack and refresh your charm:

```text
charmcraft pack
juju refresh \
  --path="./demo-api-charm_ubuntu-22.04-amd64.charm" \
  demo-api-charm --force-units --resource \
  demo-server-image=ghcr.io/canonical/api_demo_server:1.0.1
```


Next, test that the basic action invocation works:
 
```text
juju run demo-api-charm/0 get-db-info --wait 1m
```

It might take a few seconds, but soon you should see an output similar to the one below, showing the database host and port:

```text
Running operation 13 with 1 task
  - task 14 on unit-demo-api-charm-0

Waiting for task 14...
db-host: postgresql-k8s-primary.model2.svc.cluster.local
db-port: "5432"
```

Now, test that the action parameter (`show-password`) works as well by setting it to `True`:

```text
juju run demo-api-charm/0 get-db-info show-password=True --wait 1m
```

The output should now include the username and the password:
```
Running operation 15 with 1 task
  - task 16 on unit-demo-api-charm-0

Waiting for task 16...
db-host: postgresql-k8s-primary.model2.svc.cluster.local
db-password: RGv80aF9WAJJtExn
db-port: "5432"
db-username: relation_id_4
```


Congratulations, you now know how to expose operational tasks via actions!

## Review the final code

For the full code see: [06_create_actions](https://github.com/canonical/juju-sdk-tutorial-k8s/tree/06_create_actions)

For a comparative view of the code before and after this doc see: [Comparison](https://github.com/canonical/juju-sdk-tutorial-k8s/compare/05_preserve_charm_data...06_create_actions)


> **See next: {ref}`Observe your charm with COS Lite <observe-your-charm-with-cos-lite>`**
