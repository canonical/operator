(how-to-manage-charm-design)=
# How to manage charm design

## Module layout

In your `src` folder, use the `charm.py` file provided by `charmcraft init` to
define the charm class and manage the charm's interface with Juju: set up the
event observation and add the handlers. For each workload that the charm
manages, add a `{workload}.py` file that contains methods for interacting with
the workload.

```{note}
If there is an existing Python library for managing your workload, then use that
rather than creating a `{workload}.py` file yourself.
```

In your `src/charm.py` file, you will have a single class inheriting from
[](ops.CharmBase). Arrange the content of that charm in the following order:

1. An `__init__` that instantiates any needed library objects and then observes
   all relevant events.
2. Event handlers, in the order that they are observed in the `__init__` method.
   Note that these handlers should all be private to the class
   (`def _on_install(...):` not `def on_install(...):`)
3. Public methods.
3. Other private methods.

```{tip}
Use private methods or module-level functions rather than nested functions.
```

## Error handling

Throughout your charm code, handle potential errors in preference to letting the
charm crash and have the charm go to an error state.

* Automatically recoverable error: the charm should go into `maintenance` status
  until the error is resolved and then back to `active` status. Examples of
  automatically recoverable errors are those where the operation that resulted
  in the error can be retried. Retry a small number of times, with short
  delays between attempts, rather than having the charm error out and relying on
  Juju or the Juju admin for the retry. If the error is not resolved after
  retrying, then use one of the following techniques.
* Operator recoverable error: the charm should go into the `blocked` state until
  the operator resolves the error. An example is that a configuration option is
  invalid.
* Unexpected/unrecoverable error: the charm should enter the error state. Do
  this by raising an appropriate exception in the charm code. Note that the unit
  status will only show an `error` status, and the Juju admin will need to use
  the Juju log to get details of the problem. Ensure that the logging and
  exception raised makes it clear what is happening, and - when possible - how
  the Juju admin can solve it. The admin may need to file a bug and potentially
  downgrade to a previous version of the charm.

```{tip}
By default, Juju will retry hooks that fail, but Juju admins can disable this
behaviour, so charms should not rely on it.
```

## Adopt the charming ecosystem

Consider how you could enhance your charm by supporting relations with an
observability stack, identity-platform, and ingress or scaling. Charms providing
applications for all of this functionality can be found on
[Charmhub](https://charmhub.io).
