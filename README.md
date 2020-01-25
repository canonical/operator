# Operator Framework for Charms

This framework is not yet stable and is subject to change, but is available
for early testing.

## Getting Started

The following overall structure for your charm directory is recommended:

```
.
+-- config.yaml
+-- metadata.yaml
+-- mod/
+-- lib/
|   +-- ops -> ../mod/operator/ops
+-- src/
|   +-- charm.py
+-- hooks/
    +-- install -> ../src/charm.py
    +-- start -> ../src/charm.py  # for k8s charms per below
```

The `mod/` directory should contain the operator framework dependency as a git
submodule:

```
git submodule add https://github.com/canonical/operator mod/operator
```

You can sync subsequent changes from the framework and other submodule
dependencies by running:

```
git submodule update
```

Then symlink from the git submodule for the operator framework into the `lib/`
directory of your charm so it can be imported at run time:

```
ln -s ../mod/operator/ops lib/ops
```

Other dependencies included as git submodules can be added in the `mod/`
directory and symlinked into `lib/` as well.

Your `src/charm.py` is the entry point for your charm logic. It should be set
to executable and use Python 3.6 or greater (as such, operator charms can only
support Ubuntu 18.04 or later). At a minimum, it needs to define a subclass of
`CharmBase` and pass that into the framework's `main` function:

```python
import sys

from lib.ops.charm import CharmBase
from lib.ops.main import main


class MyCharm(CharmBase):
    pass


if __name__ == "__main__":
    main(MyCharm)
```

This charm does nothing, because the `MyCharm` class passed to the operator
framework's `main` function is empty. Functionality can be added to the charm
by instructing it to observe particular Juju events when the `MyCharm` object
is initialized. In the example below we're observing the `start` event. The
name of the event is a function of `self.on`, so in this case `self.on.start`
is passed to `self.framework.observe`. This will look for method named
`on_start` when that Juju event is triggered.

```python
class MyCharm(CharmBase):
    def __init__(self, *args):
        super().__init__(*args)
        self.framework.observe(self.on.start, self)

     def on_start(self, event):
        # Handle the start event here.
```

Every standard event in Juju may be observed that way, and you can also easily
define your own events in your custom types. For example, to observe the
`config-changed` Juju event:

```python
class MyCharm(CharmBase):
    def __init__(self, *args):
        super().__init__(*args)
        self.framework.observe(self.on.start, self)
        self.framework.observe(self.on.config_changed, self)

     def on_start(self, event):
        # Handle the start event here.

     def on_config_changed(self, event):
        # Handle the config-changed event here.
```

The `hooks/` directory must contain a symlink to your `src/charm.py` entry
point so that Juju can call it. You only need to set up the `hooks/install` link
(`hooks/start` for K8s charms, until [lp#1854635](https://bugs.launchpad.net/juju/+bug/1854635)
is resolved), and the framework will create all others at runtime.

Once your charm is ready, upload it to the charm store and deploy it as
normal with:

```
# Replace ${CHARM} with the name of the charm.
charm push . cs:~${USER}/${CHARM}
# Replace ${VERSION} with the version created by `charm push`.
charm release cs:~${USER}/${CHARM}-${VERSION}
charm grant cs:~${USER}/${CHARM}-${VERSION} everyone
# And now deploy your charm.
juju deploy cs:~${USER}/$CHARM
```

Alternatively, to deploy directly from local disk, run:

```
juju deploy .
```
