
(manage-logs)=
# How manage logs

> See first: {external+juju:ref}`Juju | Log <log>`, {external+juju:ref}`Juju | How to manage logs <manage-logs>`

Ops configures Python logging and warnings to end up in the Juju log, and the
Charmcraft profiles provide a `logger` object for your charm to use at the top
of your `src/charm.py` file. This lets you use the Juju `debug-log` command to
display logs from the charm. Note that it shows logs from the charm code, but
not the workload.

Use the provided logger to log information relevant to the charm user. For
example:

```python
import logging
...
logger = logging.getLogger(__name__)

class HelloOperatorCharm(ops.CharmBase):
    ...

    def _on_config_changed(self, _):
        current = self.config["thing"]
        if current not in self._stored.things:
            # Note the use of the logger here:
            logger.info("Found a new thing: %r", current)
            self._stored.things.append(current)
```

````{tip}
In addition to logs from your charm, `juju debug-log` contains a wealth of
information about everything happening in your model. To focus on what's
happening in your charm, you can adjust the logging configuration. For example,
to limit logs to ones from your charm and the uniter operation (generally: which
events are being emitted), and include `DEBUG` level logs, use:

```
juju debug-log --debug --include-module juju.worker.uniter.operation --include-module unit.<charm name>/<unit number>.juju-log
```

````

> See more: [`logging`](https://docs.python.org/3/library/logging.html)

```{admonition} Best practice
:class: hint

Capture output to `stdout` and `stderr` in your charm and use the logging and
warning functionality to send messages to the charm user, rather than rely on
Juju capturing output.

In particular, you should avoid `print()` calls, and ensure that any subprocess
calls capture output.
```

```{tip}
Some logging is performed automatically by the Juju controller; for example,
when an event handler is called. Try not to replicate this behaviour in your
charm code.
```

````{admonition} Best practice
:class: hint

Do not build log strings yourself: allow the logger to do this for you as
required. That is:

```python
# Do this!
logger.info("Got some information %s", info)
# Don't do this
logger.info("Got some information {}".format(info))
# Or this ...
logger.info(f"Got some more information {more_info}")
```
````

```{admonition} Best practice
:class: hint

Avoid spurious logging. Ensure that log messages are clear and meaningful and
provide the information a user would require to rectify any issues.
```

```{admonition} Best practice
:class: hint
Never log credentials or other sensitive information.
```
