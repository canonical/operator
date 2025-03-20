
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

```{tip}
The default logging level for a Juju model is `INFO`. To see, for example,
`DEBUG` level messages, you should change the model configuration.
```

> See more: [`logging`](https://docs.python.org/3/library/logging.html)

```{admonition} Best practice
:class: important

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
:class: important

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
:class: important

Avoid spurious logging. Ensure that log messages are clear and meaningful and
provide the information a user would require to rectify any issues.
```

```{admonition} Best practice
:class: important
Never log credentials or other sensitive information.
```
