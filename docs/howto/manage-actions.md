(manage-actions)=
# How to manage actions
> See first: {external+juju:ref}`Juju | Charm <action>`, {external+juju:ref}`Juju | Manage actions <manage-actions>`, {external+charmcraft:ref}`Charmcraft | Manage actions <manage-actions>`

## Implement the feature

### Declare the action in `charmcraft.yaml`

To tell users what actions can be performed on the charm, define an `actions` section in `charmcraft.yaml` that lists the actions and information about each action. The actions should include a short description that explains what running the action will do. Normally, all parameters that can be passed to the action are also included here, including the type of parameter and any default value. You can also specify that some parameters are required when the action is run.
For example:

```yaml
actions:
  snapshot:
    description: Take a snapshot of the database.
    params:
      filename:
        type: string
        description: The name of the snapshot file.
      compression:
        type: object
        description: The type of compression to use.
        properties:
          kind:
            type: string
            enum:
            - gzip
            - bzip2
            - xz
            default: gzip
          quality:
            description: Compression quality
            type: integer
            default: 5
            minimum: 0
            maximum: 9
    required:
    - filename
    additionalProperties: false
```

### Observe the action event and define an event handler

In the `src/charm.py` file, in the `__init__` function of your charm, set up an observer for the action event associated with your action and pair that with an event handler. For example:

```
self.framework.observe(self.on.grant_admin_role_action, self._on_grant_admin_role_action)
```

Now, in the body of the charm definition, define the action event handler. For example:

```python
def _on_grant_admin_role_action(self, event):
    """Handle the grant-admin-role action."""
    # Fetch the user parameter from the ActionEvent params dict
    user = event.params["user"]
    # Do something useful with it
    cmd = ["/usr/bin/myapp", "roles", "system_admin", user]
    # Set a log message for the action
    event.log(f"Running this command: {' '.join(cmd)}")
    granted = subprocess.run(cmd, capture_output=True)
    if granted.returncode != 0:
        # Fail the action if there is an error
        event.fail(
            f"Failed to run '{' '.join(cmd)}'. Output was:\n{granted.stderr.decode('utf-8')}"
        )
    else:
        # Set the results of the action
        msg = f"Ran grant-admin-role for user '{user}'"
        event.set_results({"result": msg})
```

More detail below:

#### Use action params

To make use of action parameters, either ones that the user has explicitly passed, or default values, use the `params` attribute of the event object that is passed to the handler. This is a dictionary of parameter name (string) to parameter value. For example:

```python
def _on_snapshot(self, event: ops.ActionEvent):
    filename = event.params["filename"]
    ...
```

> See more: [](ops.ActionEvent.params)

#### Report that an action has failed

To report that an action has failed, in the event handler definition, use the fail() method along with a message explaining the failure to be shown to the person running the action. Note that the `fail()` method doesn’t interrupt code execution, so you will usually want to immediately follow the call to `fail()` with a `return`, rather than continue with the event handler. For example:

```python
def _on_snapshot(self, event: ops.ActionEvent):
    filename = event.params['filename']
    kind = event.params['compression']['kind']
    quality = event.params['compression']['quality']
    cmd = ['/usr/bin/do-snapshot', f'--kind={kind}', f'--quality={quality}', filename]
    subprocess.run(cmd, capture_output=True)
    if granted.returncode != 0:
        event.fail(
            f"Failed to run {' '.join(cmd)!r}. Output was:\n{granted.stderr.decode('utf-8')}"
        )
   ...
```

> See more: [](ops.ActionEvent.fail)

#### Return the results of an action

To pass back the results of an action to the user, use the `set_results` method of the action event. These will be displayed in the `juju run` output. For example:

```python
def _on_snapshot(self, event: ops.ActionEvent):
    size = self.do_snapshot(event.params['filename'])
    event.set_results({'snapshot-size': size})
```

> See more: [](ops.ActionEvent.set_results)

#### Log the progress of an action

In a long-running action, to give the user updates on progress, use the `.log()` method of the action event. This is sent back to the user, via Juju, in real-time, and appears in the output of the `juju run` command. For example:

```python
def _on_snapshot(self, event: ops.ActionEvent):
    event.log('Starting snapshot')
    self.snapshot_table1()
    event.log('Table1 complete')
    self.snapshot_table2()
    event.log('Table2 complete')
    self.snapshot_table3()
```

> See more: [](ops.ActionEvent.log)

#### Record the ID of an action task

When a unique ID is needed for the action task - for example, for logging or creating temporary files, use the `.id` attribute of the action event. For example:

```python
def _on_snapshot(self, event: ops.ActionEvent):
    temp_filename = f'backup-{event.id}.tar.gz'
    logger.info("Using %s as the temporary backup filename in task %s", filename, event.id)
    self.create_backup(temp_filename)
    ... 
```
> See more: [](ops.ActionEvent.id)

## Test the feature

> See first: {ref}`get-started-with-charm-testing`

What you need to do depends on what kind of tests you want to write.

### Write unit tests

> See first: {ref}`write-scenario-tests-for-a-charm`

To verify that the charm state is as expected after executing an action, use the `run` method of the `Context` object, with `ctx.on.action`. The context contains any logs and results that the charm set.

For example:

```python
from ops import testing

def test_backup_action():
    ctx = testing.Context(MyCharm)
    ctx.run(ctx.on.action('snapshot', params={'filename': 'db-snapshot.tar.gz'}), testing.State())
    assert ctx.action_logs == ['Starting snapshot', 'Table1 complete', 'Table2 complete']
    assert 'snapshot-size' in ctx.action_results
```

> See more: [](ops.testing.Context.action_logs), [](ops.testing.Context.action_results), [](ops.testing.ActionFailed)


### Write integration tests

> See first: {ref}`write-integration-tests-for-a-charm`

To verify that an action works correctly against a real Juju instance, write an integration test with `pytest_operator`. For example:

```python
async def test_logger(ops_test):
    app = ops_test.model.applications[APP_NAME]
    unit = app.units[0]  # Run the action against the first unit.
    action = await unit.run_action('snapshot', filename='db-snapshot.tar.gz')
    action = await action.wait()
    assert action.status == 'completed'
    assert action.results['snapshot-size'].isdigit()
```
