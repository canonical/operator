(manage-pebble-custom-notices)=
# How to manage Pebble custom notices

## Record a notice

To record a custom notice, use the `pebble notify` CLI command. For example, the workload might have a script to back up the database and then record a notice:

```sh
pg_dump mydb >/tmp/mydb.sql
/charm/bin/pebble notify canonical.com/postgresql/backup-done path=/tmp/mydb.sql
```

The first argument to `pebble notify` is the key, which must be in the format `<domain>/<path>`. The caller can optionally provide map data arguments in `<name>=<value>` format; this example shows a single data argument named `path`.

The `pebble notify` command has an optional `--repeat-after` flag, which tells Pebble to only allow the notice to repeat after the specified duration (the default is to repeat for every occurrence). If the caller says `--repeat-after=1h`, Pebble will prevent the notice with the same type and key from repeating within an hour -- useful to avoid the charm waking up too often when a notice occurs frequently.

> See more: [Pebble | `pebble notify`](inv:pebble:std:label#reference_pebble_notify_command)

## Respond to a notice

To have the charm respond to a notice, observe the `pebble_custom_notice` event and switch on the notice's `key`:

```python
class PostgresCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        # Note that "db" is the workload container's name
        framework.observe(self.on["db"].pebble_custom_notice, self._on_pebble_custom_notice)

    def _on_pebble_custom_notice(self, event: ops.PebbleCustomNoticeEvent) -> None:
        if event.notice.key == "canonical.com/postgresql/backup-done":
            path = event.notice.last_data["path"]
            logger.info("Backup finished, copying %s to the cloud", path)
            f = event.workload.pull(path, encoding=None)
            s3_bucket.upload_fileobj(f, "db-backup.sql")

        elif event.notice.key == "canonical.com/postgresql/other-thing":
            logger.info("Handling other thing")
```

All notice events have a [`notice`](ops.PebbleNoticeEvent.notice) property with the details of the notice recorded. That is used in the example above to switch on the notice `key` and look at its `last_data` (to determine the backup's path).

## Fetch notices

A charm can also query for notices using the following two `Container` methods:

* [`get_notice`](ops.Container.get_notice), which gets a single notice by unique ID (the value of `notice.id`).
* [`get_notices`](ops.Container.get_notices), which returns all notices by default, and allows filtering notices by specific attributes such as `key`.

## Write unit tests

To test charms that use Pebble Notices, use the [`pebble_custom_notice`](ops.testing.CharmEvents.pebble_custom_notice) method to simulate recording a notice with the given details. For example, to simulate the "backup-done" notice handled above, as well as two other notices in the queue, the
charm tests could do the following:

```python
from ops import testing

@patch('charm.s3_bucket.upload_fileobj')
def test_backup_done(upload_fileobj):
    # Arrange:
    ctx = testing.Context(PostgresCharm)

    notice = testing.Notice(
        'canonical.com/postgresql/backup-done',
        last_data={'path': '/tmp/mydb.sql'},
    )
    container = testing.Container('db', can_connect=True, notices=[
        testing.Notice(key='example.com/a', occurrences=10),
        testing.Notice(key='example.com/b'),
        notice,
    ])
    root = container.get_filesystem()
    (root / "tmp").mkdir()
    (root / "tmp" / "mydb.sql").write_text("BACKUP")
    state_in = testing.State(containers={container})

    # Act:
    state_out = ctx.run(ctx.on.pebble_custom_notice(container, notice), state_in)

    # Assert:
    upload_fileobj.assert_called_once()
    upload_f, upload_key = upload_fileobj.call_args.args
    self.assertEqual(upload_f.read(), b"BACKUP")
    self.assertEqual(upload_key, "db-backup.sql")
```
