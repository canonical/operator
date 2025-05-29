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

Also in the `src/charm.py file`, create a class for each action that defines the schema of the action parameters. For example:

```python
class CompressionKind(enum.Enum):
    GZIP = 'gzip'
    BZIP = 'bzip2'
    XZ = 'xz'

class Compression(pydantic.BaseModel):
    kind: CompressionKind = pydantic.Field(CompressionKind.BZIP)

    quality: int = pydantic.Field(5, description="Compression quality.")

    @pydantic.validator("quality")
    def validate_quality(cls, value):
        if 0 <= quality <= 9:
            return value
        raise ValueError("Quality must be an integer between 0 and 9 inclusive.")

class SnapshotAction(pydantic.BaseModel):
    """Take a snapshot of the database."""

    filename: str = pydantic.Field(description="The name of the snapshot file.")

    compression: Compression = pydantic.Field(
        Compression.GZIP,
        description="The type of compression to use.",
    )
```

Now, in the body of the charm definition, define the action event handler. For example:

```python
def _on_snapshot_action(self, event):
    """Handle the snapshot action."""
    # Fetch the parameters. If the user passes something invalid, this will
    # fail the action with an appropriate message.
    params = event.load_params(SnapshotAction, errors="fail")
    # This might take a while, so let the user know we're working on it.
    # This is sent back to the Juju user in real-time, and appears in the output
    # of the `juju run` command.
    event.log(f"Generating snapshot into {params.filename}")
    # Do the snapshot.
    success = self.do_snapshot(
        filename=params.filename,
        kind=params.compression.kind,
        quality=params.compression.quality,
    )
    if not success:
        # Report to the user that the action has failed.
        event.fail(f"Failed to generate snapshot.")  # Ideally, include more details than this!
        # Note that `fail()` doesn't interrupt code, so is typically followed by a `return`.
        return
    # Set the results of the action.
    msg = f"Stored snapshot in {params.filename}."
    # These will be displayed in the `juju run` output.
    event.set_results({"result": msg})
```

> See more: [](ops.ActionEvent.load_params), [](ops.ActionEvent.params), [](ops.ActionEvent.fail), [](ops.ActionEvent.set_results), [](ops.ActionEvent.log)

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

### Write unit tests

> See first: {ref}`write-unit-tests-for-a-charm`

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
