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

You should **always** include the `additionalProperties` field, which controls whether users can provide properties that are not in the definition. The default value of the field changed from `true` in Juju 3 to `false` in Juju 4. If you don't explicitly include the field, the charm behaviour will differ depending on which Juju version the charm is deployed to.

In the `src/charm.py` file of the charm, add a class that mirrors the
configuration from `charmcraft.yaml`. This lets your static type checker and
IDE know what Python type the parameters should be, and provides a place to do
additional validation. Using the example from above:

```python
class CompressionKind(enum.Enum):
    GZIP = 'gzip'
    BZIP = 'bzip2'
    XZ = 'xz'

class Compression(pydantic.BaseModel):
    kind: CompressionKind = pydantic.Field(CompressionKind.BZIP)

    quality: int = pydantic.Field(5, description='Compression quality.', ge=0, le=9)

class SnapshotAction(pydantic.BaseModel):
    """Take a snapshot of the database."""

    filename: str = pydantic.Field(description="The name of the snapshot file.")

    compression: Compression = pydantic.Field(
        default_factory=Compression,
        description="The type of compression to use.",
    )
```

### Observe the action event and define an event handler

In the `src/charm.py` file, in the `__init__` function of your charm, set up an observer for the action event associated with your action and pair that with an event handler. For example:

```
framework.observe(self.on['snapshot'].action, self._on_snapshot_action)
```

Now, in the body of the charm definition, define the action event handler. For example:

```python
def _on_snapshot_action(self, event: ops.ActionEvent):
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
        event.fail("Failed to generate snapshot.")  # Ideally, include more details than this!
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

If the charm code calls `event.fail()` to indicate that the action has failed,
an `ActionFailed` exception will be raised. This avoids having to include
success checks in every test where the action is successful.

```python
def test_backup_action_failed():
    ctx = testing.Context(MyCharm)

    with pytest.raises(testing.ActionFailed) as exc_info:
        ctx.run(ctx.on.action('do_backup'), State())
    assert exc_info.value.message == "sorry, couldn't do the backup"
    # The state is also available if that's required:
    assert exc_info.value.state.get_container(...)

    # You can still assert action results and logs that occurred as well as the failure:
    assert ctx.action_logs == ['baz', 'qux']
    assert ctx.action_results == {'foo': 'bar'}
```

> See more: [](ops.testing.Context.action_logs), [](ops.testing.Context.action_results), [](ops.testing.ActionFailed)

### Write integration tests

> See first: {ref}`write-integration-tests-for-a-charm`

To verify that an action works correctly against a real Juju instance, write an integration test with `jubilant`. For example:

```python
def test_logger(juju: jubilant.Juju):
    action = juju.run("your-app/0", "snapshot", {"filename": "db-snapshot.tar.gz"})
    assert action.status == "completed"
    assert action.results["snapshot-size"].isdigit()
```
