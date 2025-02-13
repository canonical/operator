(how-to-log-a-message-in-a-charm)=
# How to log a message in a charm

> See first: {external+juju:ref}`Juju | Log <log>`, {external+juju:ref}`Juju | Manage logs <manage-logs>`

<!--
> 
> - **tl;dr:** <br>
The default logging level for a Juju model is `INFO`. To see, e.g., `DEBUG` level messages,  you should change the model configuration: `juju model-config logging-config="<root>=DEBUG"`. 
-->

To log a message in a charm, import Python's `logging` module, then use the `getLogger()` function with the desired level. For example:

```python
import logging
# ...
logger = logging.getLogger(__name__)

class HelloOperatorCharm(ops.CharmBase):
    # ...

    def _on_config_changed(self, _):
        current = self.config["thing"]
        if current not in self._stored.things:
            # Note the use of the logger here:
            logger.debug("found a new thing: %r", current)
            self._stored.things.append(current)
```

> See more: 
> - [`logging`](https://docs.python.org/3/library/logging.html), [`logging.getLogger()`](https://docs.python.org/3/library/logging.html#logging.getLogger)
> - [`logging.getLogger().critical()`](https://docs.python.org/3/library/logging.html#logging.Logger.critical)
> - [`logging.getLogger().error()`](https://docs.python.org/3/library/logging.html#logging.Logger.error)
> - [`logging.getLogger().warning()`](https://docs.python.org/3/library/logging.html#logging.Logger.warning)
> - [`logging.getLogger().info()`](https://docs.python.org/3/library/logging.html#logging.Logger.info)
> - [`logging.getLogger().debug()`](https://docs.python.org/3/library/logging.html#logging.Logger.debug)

Juju automatically picks up logs from charm code that uses the Python [logging facility](https://docs.python.org/3/library/logging.html), so we can use the Juju [`debug-log` command](inv:juju:std:label#command-juju-debug-log) to display logs for a model. Note that it shows logs from the charm code (charm container), but not the workload container.

Besides logs, `stderr` is also captured by Juju. So, if a charm generates a warning, it will also end up in Juju's debug log. This behaviour is consistent between K8s charms and machine charms.

**Tips for good practice:**

- Note that some logging is performed automatically by the Juju controller, for example when an event handler is called. Try not to replicate this behaviour in your own code. 

-  Keep developer specific logging to a minimum, and use `logger.debug()` for such output. If you are debugging a problem, ensure you comment out or remove large information dumps (such as config files, etc.) from the logging once you are finished.

- When passing messages to the logger, do not build the strings yourself. Allow the logger to do this for you as required by the specified log level. That is:

<!--
| DON'T &#10060; | DO :white_check_mark: | 
|-|-|
| `logger.info("Got some information {}".format(info))`| `logger.info("Got some information %s", info)` |
|`logger.info(f"Got some more information {more_info}")`| |
-->

```python
# Do this!
logger.info("Got some information %s", info)
# Don't do this
logger.info("Got some information {}".format(info))
# Or this ...
logger.info(f"Got some more information {more_info}")
```
