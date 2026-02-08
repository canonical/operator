(turn-a-hooks-based-charm-into-an-ops-charm)=
# How to turn a hooks-based charm into an ops charm
> See first: {external+juju:ref}`Juju | Charm taxonomy <charm-taxonomy>`

Suppose you have a hooks-based charm and you decide to rewrite it using the Ops framework in Python.

The core concept tying hooks to the Ops framework is that hooks are no longer scripts stored in files that are named like the event they are meant to respond to; hooks are, instead, blocks of Python code that are best written as methods of a class. The class represents the charm; the methods, the operator logic to be executed as specific events occur.

Here we'll look at just how to do that. You will learn how to:
 - look at a simple hooks-based charm to understand its relationship with the Juju state machine;
- map that forward to the Ops framework;
- translate some shell commands to their Ops counterparts;
- translate some more shell commands by using some handy charm libraries.


This guide will refer to a local LXD cloud and a machine charm, but you can easily generalize the approach to Kubernetes.


## Analyse the charm


We start by looking at the charm we intend to translate; as an example, we will take [`microsample`](https://github.com/erik78se/charm-microsample), an educational charm, because it is simple and includes a number of hooks, while implementing little-to-no business logic (the charm does very little).

From the charm root directory we see:

```text
$ tree .
.
├── charmcraft.yaml
├── config.yaml
├── copyright
├── hooks
│   ├── config-changed
│   ├── install
│   ├── start
│   ├── stop
│   ├── update-status
│   ├── upgrade-charm
│   ├── website-relation-broken
│   ├── website-relation-changed
│   ├── website-relation-departed
│   └── website-relation-joined
├── icon.svg
├── LICENSE
├── metadata.yaml
├── microsample-ha.png
├── README.md
└── revision
```

By looking at the `hooks` folder, we can already tell that there are two categories of hooks we'll need to port;
- core lifecycle hooks:
  - `config-changed`
  - `install`
  - `start`
  - `stop`
  - `update-status`
  - `upgrade-charm`
- hooks related to a `website` relation:
  - `website-relation-*`

If we look at `metadata.yaml` in fact we'll see:
```yaml
provides:
  website:
    interface: http
```

### Setting up the stage

If we look at `charmcraft.yaml`, we'll see a section:
```yaml
parts:
  microsample:
    plugin: dump
    source: .
    prime:
      - LICENSE
      - README.md
      - config.yaml
      - copyright
      - hooks
      - icon.svg
      - metadata.yaml
```
This is a spec required to make charmcraft work in 'legacy mode' and support older charm frameworks, such as the hooks charm we are working with.
As such, if we take a look at the packed `.charm` file, we'll see that the files and folders listed in 'prime' are copied over one-to-one in the archive.

If we remove that section, run `charmcraft pack`, and then attempt to deploy the charm, the command will fail with a
```bash
Processing error: Failed to copy '/root/stage/src': no such file or directory.
```

### An approach to avoid

The minimal-effort solution in this case could be to create a file `/src/charm.py` and translate the built-in `self.on` event hooks to subprocess calls to the Bash event hooks as-they-are. Roughly:

```python
#!/usr/bin/env python3
import os
import ops

class Microsample(ops.CharmBase):
  def __init__(self, *args):
    super().__init__(*args)
    self.framework.observe(self.on.config_changed, lambda _: os.popen('../hooks/config-changed'))
    self.framework.observe(self.on.install, lambda _: os.popen('../hooks/install'))
    self.framework.observe(self.on.start, lambda _: os.popen('../hooks/start'))
    self.framework.observe(self.on.stop, lambda _: os.popen('../hooks/stop'))
    # etc...

if __name__ == "__main__":
    main(ops.Microsample)

```
Relying on `popen` is _not_ how Ops is supposed to be used. However, this code will work, and it demonstrates the core principle of mapping hook names to handler code.

```{important}


We need a few preparatory steps:\
  • Add a `requirements.txt` file to ensure that the charm's Python environment will install for us the `ops` package.\
• Modify the install hook to install `snap` for us, which is used in the script.\
• In practice we cannot bind lambdas to `observe`, we need to write dedicated _methods_ for that.\
• We need to figure out the required environment variables for the commands to work, which is not trivial.\
\
A more detailed explanation of this process is worthy of its own how-to guide, so we'll skip to the punchline here: it works. Check out [this branch](https://github.com/PietroPasotti/hooks-to-ops/tree/1-sh-charm) and see for yourself.

```

### A better plan

It is in our interest to move the handler logic for each `/hooks/<hook_name>` to `Microsample._on_<hook_name>`, for several reasons:
- We can avoid code duplication by accessing shared data via the CharmBase interface provided through `self`.
- The code is all in one place, easier to maintain.
- We automatically have one Python object we can test, instead of going back and forth between Bash scripts and Python wrappers.

So let's do that.

The idea is to turn those bash scripts into Python code we can call from aptly-named `Microsample` methods; but does it always make sense to do so? We'll see in a minute.

### Step 1: Move script contents as-they-are into dedicated charm methods


```python
class Microsample(ops.CharmBase):
    def __init__(self, framework):
        super().__init__(framework)
        framework.observe(self.on.install, self._on_install)
        framework.observe(self.on.config_changed, self._on_config_changed)
        framework.observe(self.on.start, self._on_start)
        # etc ...
```
Let's begin with `install`.
The `/hooks/install` script checks if a snap package is installed; if not, it installs it. We need to still reach out to a shell to grab the `snap` package info and install the package, but we can have the logic and the status management in Python, which is nice. We use `subprocessing.check_call` to reach out to the OS. And yes, there is a better way to do this, we'll get to that later.

```python
    def _on_install(self, _event):
        snapinfo_cmd = Popen("snap info microsample".split(" "),
                             stdout=subprocess.PIPE)
        output = check_output("grep -c 'installed'".split(" "),
                              stdin=snapinfo_cmd.stdout)
        is_microsample_installed = bool(output.decode("ascii").strip())

        if not is_microsample_installed:
            self.unit.status = ops.MaintenanceStatus("installing microsample")
            out = check_call("snap install microsample --edge")

        self.unit.status = ops.ActiveStatus()
```

For `on-start` and `on-stop`, which are simple instructions to `systemctl` to start/stop the `microsample` service, we can copy over the commands as they are:

```python
    def _on_start(self, _event):  # noqa
        check_call("systemctl start snap.microsample.microsample.service".split(' '))

    def _on_stop(self, _event):  # noqa
        check_call("systemctl stop snap.microsample.microsample.service".split(' '))
```
In a couple of places in the scripts, `sleep 3` calls ensure that the service has some time to come up; however, this might get the charm stuck in the waiting loop if for whatever reason the service does NOT come up, so it is quite risky and we are not going to do that. Instead, we are going to rely on the fact that if other event handlers were to fail because of the service not being up, they would handle that case appropriately (e.g., defer the event if necessary).

The rest of the translation is pretty straightforward. However, it is still useful to note a few things about relations, logging, and environment variables, which we do below.

#### Wrapping the `website` relation

`ops.Relation` provides a neat wrapper for the juju relation object.
We are going to add a helper method:

```python
    def _get_website_relation(self) -> ops.Relation:
        # WARNING: would return None if called too early, e.g. during install
        return self.model.get_relation("website")
```

That allows us to fetch the Relation wherever we need it and access its contents or mutate them in a natural way:
```python
    def _on_website_relation_joined(self, _event):
        relation = self._get_website_relation()
        relation.data[self.unit].update(
            {"hostname": self.private_address,
             "port": self.port}
        )
```

Note how `relation.data` provides an interface to the relation databag (see [](#set-up-a-relation)) and we need to select which part of that bag to access by passing an `ops.Unit` instance.

#### Logging

Every maintainable charm will have some form of logging integrated; in a few places in the Bash scripts we see calls to a `juju-log` command; we can replace them with simple `logger.log` calls; such as in
```python
    def _on_website_relation_departed(self, _event):  # noqa
        logger.debug("%s departed website relation", self.unit.name)
```
Where `logger = logging.getLogger(__name__)`.

#### Environment variables

Some of the Bash scripts read environment variables such as `$JUJU_REMOTE_UNIT`, `$JUJU_UNIT_NAME` ; of course we could do

```python
JUJU_UNIT_NAME = os.environ["JUJU_UNIT_NAME"]
```

but `CharmBase` exposes a `.unit` attribute we can read this information from, instead of grabbing it off the environment; this makes for more readable code.
So, wherever we need the juju unit name, we can write `self.unit.name` (that will get you `microsample/0` for example) or if you are actually after the *application name*, you can write `self.unit.app.name` (and get `microsample` back, without the unit index suffix).

The resulting code at this stage can be inspected at [this branch](https://github.com/PietroPasotti/hooks-to-ops/tree/2-py-charm).

### Step 2: Clean up snap & systemd code

In the `_on_install` method we had translated one-to-one the calls to `snap info` to check whether the snap was installed or not; we can however use one more Linux lib for that:

`charmcraft fetch-lib charms.operator_libs_linux.v1.snap`

Then we can replace all that `Popen` piping with simpler calls into the lib's API; `_on_install `becomes:
```python
    def _on_install(self, _event):
        microsample_snap = snap.SnapCache()["microsample"]
        if not microsample_snap.present:
            self.unit.status = ops.MaintenanceStatus("installing microsample")
            microsample_snap.ensure(snap.SnapState.Latest, channel="edge")

        self.wait_service_active()
        self.unit.status = ops.ActiveStatus()

```

Similarly all that string parsing we were doing to get a hold of the snap version, can be simplified by grabbing the `microsample_snap.channel` (not quite the same, but for the purposes of this charm, it is close enough).

```python
    def _get_microsample_version(self):
        microsample_snap = snap.SnapCache()["microsample"]
        return microsample_snap.channel
```

Also, we can interact with the `microsample` service via the `operator_libs_linux.v0` charm library, which wraps `systemd` and allows us to write simply:

```python
    def _on_start(self, _event):  # noqa
        systemd.service_start("snap.microsample.microsample.service")

    def _on_stop(self, _event):  # noqa
        systemd.service_stop("snap.microsample.microsample.service")
```

```{note}

To install:\
`charmcraft fetch-lib charms.operator_libs_linux.v0.systemd`\
`charmcraft fetch-lib charms.operator_libs_linux.v1.snap`\

To use, add line to imports:
`from charms.operator_libs_linux.v0 import systemd` \
`from charms.operator_libs_linux.v1 import snap`

```

By inspecting more closely the flow of the events, we realize that not all of the event handlers that we currently subscribe to are necessary. For example, the relation data is going to be set once the relation is joined, but nothing needs to be done when the relation changes or is broken/departed. Since it depends on configurable values, however, we will need to make sure that the `config-changed` handler also keeps the relation data up to date.

Furthermore we can get rid of the `start` handler, since the `snap.ensure()` call will also start the service for us on `install`.  Similarly we can strip away most of the calls in `_on_upgrade_charm` (originally invoking multiple other hooks) and only call `snap.ensure(...)`.

The final result can be inspected at [this branch](https://github.com/PietroPasotti/hooks-to-ops/tree/3-py-final).

### Testing

After you've prepared the event handlers, you should write tests for the charm. See {ref}`write-unit-tests-for-a-charm` and {ref}`write-integration-tests-for-a-charm`.

## Closing notes

We have seen how to turn a hooks-based charm to one using the state-of-the-art Ops framework---this basically boils down to moving code from files in a folder to methods in a `CharmBase` subclass.
That is, this is what it amounts to _to a developer_. But what about _the system_?

The fact is, hooks charms can be written in Assembly, or any other language, so long as the shebang references something (a command / an interpreter) known to the script runner. The starting charm was as a result very lightweight, since it is written in Bash and that is included in the base Linux image.

Ops charms, on the other hand, are Python charms. As such, even though Ops is not especially large in and of itself, Ops charms bring a virtual environment with them. That makes the resulting charm package somewhat heavier. That might be a consideration when the charm target is a resource-constrained system.

### Todo's / disclaimers


Above, the `website` relation has not been tested; implementing the `Requires` part of it is also left as an exercise to the reader.
