(how-to-manage-charms)=
# How to manage charms

TODO: I get that "manage charms" as a name provides a through-link for Juju-ops-charmcraft ... *but* this is really "how to develop charms", not "manage". At best, "how to manage charm development".

> See first: https://canonical-juju.readthedocs-hosted.com/en/3.6/user/howto/manage-charms/#build-a-charm, https://canonical-charmcraft.readthedocs-hosted.com/en/stable/howto/manage-charms/

TODO: make those external ref links.

## Create a repository and initialise it

Create a repository with your source control of choice. Commit the code you
have added and changed after every significant change, so that you have a
record of the work, and can revert to an earlier version when required.

.. admonition:: Best practice
    :class: hint

    Name the repository using the pattern ``<charm name>-operator`` for a single
    charm, or ``<base charm name>-operators`` when the repository will hold
    multiple related charms. For the charm name, see
    {external+charmcraft:ref}`<specify-a-name>`.
    
In your new repository, run ``charmcraft init`` to generate the recommended
structure for building a charm.

```{note}
In most cases, you'll want to use `--profile=machine` or `profile=kubernetes`.
If you are charming an application built with a popular framework, check if
charmcraft has a specific profile: https://canonical-charmcraft.readthedocs-hosted.com/en/stable/tutorial/

TODO: make that an external ref link

Avoid the default (`--profile=simple`), which provides a demo charm, rather than
a base for building a charm of your own.
```

````{tip}
If your repository will hold multiple charms, or a charm and source for other
artifacts, like a Rock, create a `charms` folder at the top level, then a folder
for each charm inside of that one, and run `charmcraft --init` in each charm
folder. You'll end up with a structure similar to:

```
my-charm-set-operators/
├── charms
│   ├── my-charm
│   │   ├── charmcraft.yaml
│   │   ├── pyproject.toml
│   │   ├── README.md
│   │   ├── requirements.txt
│   │   ├── src
│   │   │   └── charm.py
│   │   ├── tests
│   │   │   ├── integration
│   │   │   │   └── test_charm.py
│   │   │   └── unit
│   │   │       └── test_charm.py
│   │   └── tox.ini
│   ├── my-charm-dashboard
|   |   └── ...
│   └── my-charm-helper
|   |   └── ...
├── CONTRIBUTING.md
├── LICENSE
├── README.md
└── rock
    └── ...
```

````

## Development tooling

The charmcraft profiles configured recommended tools for developing charms. To
use these, install [tox](https://tox.wiki/en/stable/index.html) on your
development server.

```{tip}
If you use the `charm-dev` [Multipass](https://canonical.com/multipass) image or
the [`concierge`](https://github.com/jnsgruk/concierge) tool to configure your
development environment, you'll already have `tox` installed.
```

- Run `tox` to format and lint the code, and run static type checking and the
  charm unit tests.
- Run `tox -e integration` to run the charm integration tests.
- Run `tox list` to see the available commands.

```{admonition} Best practice
:class: hint

All charms should provide the commands configured by the charmcraft profiles, to
allow easily testing across the charm ecosystem. It's fine to tweak the
configuration of individual tools, or to add additional commands, but keep the
command names and meanings the the profiles provide.
```

## Dependencies

### Python version

Charms run using the Python version provided by the base Ubuntu version. Write
charm code that will run with the Python version of the oldest base you support.

> See also: https://canonical-juju.readthedocs-hosted.com/en/3.6/user/reference/juju/juju-roadmap-and-releases/

TODO: make that an external:refs link

```{admonition} Best practice
:class: hint

Set the [`requires-python`](https://packaging.python.org/en/latest/specifications/pyproject-toml/#requires-python)
version in your `pyproject.toml` so that tooling will detect any use of Python
features not available in the versions you support.
```

## Python packages

Specify all the all direct dependencies of your charm in your `pyproject.toml`
file in the top-level charm folder. For example:

```toml
# Required group: these are all dependencies required to run the charm.
dependencies = [
    "ops~=2.19",
]

# Required group: these are all dependencies required to run all the charm's tests.
[dependency-groups]
test = [
    "ops[testing]",
    "pytest",
    "coverage[toml]",
    "jubilant",
]
# Optional additional groups:
docs = [
    "canonical-sphinx-extensions",
    "furo",
    "sphinx ~= 8.0.0",
    "sphinxext-opengraph",
]
```

Use the `pyproject.toml` dependencies should to specify *all* dependencies
(including indirect or transitive dependencies) in a lock file.

````{admonition} Best practice
:class: hint

When using the `charm` plugin with charmcraft, ensure that you set strict
dependencies to true, for example:

```yaml
parts:
  my-charm:
    plugin: charm
    charm-strict-dependencies: false
```
````

The default lock file is a plain `requirements.txt` file (you can use a tool
such as [pip-compile](https://pip-tools.readthedocs.io/en/latest/) to produce
it from `pyproject.toml`), but using
[uv](https://canonical-charmcraft.readthedocs-hosted.com/en/stable/reference/plugins/uv_plugin/)
with a `uv.lock` file or
[poetry](https://canonical-charmcraft.readthedocs-hosted.com/en/stable/reference/plugins/poetry_plugin/)
is also supported.

TODO: make those an external:refs link

TODO: CC0005 recommends uv or poetry only, and it is better than needing pip-tools as well. Should we switch to that? Seems weird to not be the same as the charmcraft profile, maybe update that to use uv?

```{admonition} Best practice
:class: hint

Ensure that the `pyproject.toml` *and* the lock file are committed to version
control, so that exact versions of charms can be reproduced.
```

```{tip}
Including an external dependency is a significant choice. It can help with
reducing the complexity and development cost. However, it also increases the
complexity of understanding the entire system, and adds a maintenance burden of
keeping track of upstream versions, particularly around security issues.

> See more: [Our Software Dependency Problem](https://research.swtch.com/deps)
```

```{admonition} Best practice
:class: hint

Ensure that tooling is configured to automatically detect new versions,
particularly security releases, for all your dependencies.
```

## Module layout

Your `src` folder will have at least two Python modules, `charm.py` and a
workload module.

TODO: David to add something about what goes into charm.py and what goes into
`{workload}.py`.

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

## Events

TODO: something here about which events are required, pointing to the other
how-tos for adding functionality. Maybe linking to something that explains the
difference between Juju and Lifecycle and custom events?

```{important}
Charms should never define custom events themselves. They have no need for
emitting events (custom or otherwise) for their own consumption, and as they
lack consumers, they don’t need to emit any for others to consume either.
Custom events should only be defined and emitted in a library.
```

## Error handling

Throughout your charm code, handle potential errors rather than letting the
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

## Subprocesses

```{admonition} Best practice
:class: hint

Limit the use of shell scripts and commands as much as possible in favour of
writing Python for charm code.
```

```{admonition} Best practice
:class: hint

Log the return (exit) code as well as `stderr` when errors occur.
```

```{admonition} Best practice
:class: hint

Use absolute paths to prevent security issues.
```

```{admonition} Best practice
:class: hint

Execute processes directly rather than via the shell.
```

For example:

```python
import subprocess

try:
    # Comment to explain why subprocess is used.
    result = subprocess.run(
        # Array based execution.
        ["/usr/bin/echo", "hello world"],
        capture_output=True,
        check=True,
    )
    logger.debug("Command output: %s", result.stdout)
except subprocess.CalledProcessError as err:
    logger.error("Command failed with code %i: %s", err.returncode, err.stderr)
    raise
```

## How to log a message in a charm

> See first: {external+juju:ref}`Juju | Log <log>`, {external+juju:ref}`Juju | How to manage logs <manage-logs>`

Ops configures Python logging and warnings to end up in the Juju log, and the
charmcraft profiles provide a `logger` object for your charm to use at the top
of your `src/charm.py` and `src/{workload}.py` files. This lets you use the
Juju `debug-log` command to display logs from the charm. Note that it shows
logs from the charm code, but not the workload.

Use the provided logger to log information relevant to the Juju admin. For
example:

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
            logger.info("Found a new thing: %r", current)
            self._stored.things.append(current)
```

```{tip}
The default logging level for a Juju model is `INFO`. To see, for example,
`DEBUG` level messages, you should change the model configuration. See
{external+juju:ref`debug-log <>` for more information.

TODO: https://canonical-juju.readthedocs-hosted.com/en/3.6/user/howto/manage-logs/#configure-the-logging-level as a ref link
```

> See more: [`logging`](https://docs.python.org/3/library/logging.html), [`logging.getLogger()`](https://docs.python.org/3/library/logging.html#logging.getLogger)

```{admonition} Best practice

Capture output to `stdout` and `stderr` in your charm and use the logging and
warning functionality to send messages to the Juju admin, rather than rely on
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

## Continuous integration

TODO: something about what should be done here, like definitely have the linting and tests running, maybe more things?

.. admonition:: Best practice
    :class: hint

    The quality assurance pipeline of a charm should be automated using a
    continuous integration (CI) system.

.. tip::

    The `charming-actions <https://github.com/canonical/charming-actions>`_
    repository includes actions to ensure that libraries are up-to-date, publish
    charms and libraries, and more.

## Next steps / charm maturity or something like that

Consider how you could enhance your charm by supporting relations with an
observability stack, identity-platform, [and something that would help with scaling].
Charms providing applications for all of this functionality can be found on
[Charmhub](https://charmhub.io).

TODO: what about https://canonical-juju.readthedocs-hosted.com/en/3.6/user/reference/charm/charm-maturity/ - does that get absorbed here, or should we work through it? Maybe it goes into separate places?
