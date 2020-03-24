# The Operator Framework

The Operator Framework provides a simple, lightweight, and powerful way of encapsulating operational experience in code.

The framework will help you to:

* model the integration of your services
* manage the lifecycle of your application
* create reusable and scalable components
* keep your code simple and readable

## Getting Started

The following overall structure for your charm directory is recommended:

```
.
├── config.yaml
├── metadata.yaml
├── mod/
├── lib/
│   └── ops -> ../mod/operator/ops
├── src/
│   └── charm.py
└── hooks/
    ├── install -> ../src/charm.py
    └── start -> ../src/charm.py  # for k8s charms per below
```

The `mod/` directory should contain the operator framework dependency as a git
submodule:

```
git submodule add https://github.com/canonical/operator mod/operator
```

Then symlink from the git submodule for the operator framework into the `lib/`
directory of your charm so it can be imported at run time:

```
ln -s ../mod/operator/ops lib/ops
```

Other dependencies included as git submodules can be added in the `mod/`
directory and symlinked into `lib/` as well.

You can sync subsequent changes from the framework and other submodule
dependencies by running:

```
git submodule update
```

Those cloning and checking out the source for your charm for the first time
will need to run:

```
git submodule update --init
```

Your `src/charm.py` is the entry point for your charm logic. It should be set
to executable and use Python 3.6 or greater. At a minimum, it needs to define
a subclass of `CharmBase` and pass that into the framework's `main` function:

```python
import sys
sys.path.append('lib')  # noqa: E402

from ops.charm import CharmBase
from ops.main import main


class MyCharm(CharmBase):
    pass


if __name__ == "__main__":
    main(MyCharm)
```

This charm does nothing, because the `MyCharm` class passed to the operator
framework's `main` function is empty. Functionality can be added to the charm
by instructing it to observe particular Juju events when the `MyCharm` object
is initialized. For example,

```python
class MyCharm(CharmBase):
    def __init__(self, *args):
        super().__init__(*args)
        self.framework.observe(self.on.start, self.on_start)

    def on_start(self, event):
        # Handle the start event here.
```

Every standard event in Juju may be observed that way, and you can also easily
define your own events in your custom types.

> The second argument to `observe` can be either the handler as a bound
> method, or the observer itself if the handler is a method of the observer
> that follows the conventional naming pattern. That is, in this case, we
> could have called just `self.framework.observe(self.on.start, self)`.

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

# Operator Framework development

If you want to work in the framework *itself* you will need the following depenencies installed in your system:

- Python >= 3.5
- PyYAML
- autopep8
- flake8

Then you can try `./run_tests`, it should all go green.
