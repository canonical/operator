# Operator Framework for Charms

This framework is not yet stable and is subject to change, but is available
for early testing.

## Getting Started

Start by creating a charm directory with at least the following files:

* `src/charm.py` (must be executable and use Python 3.6+)
* `hooks/install` (or `hooks/start` for K8s charms) sym-linked to `../src/charm.py`
* `metadata.yaml`

Then install the framework into the `lib/` directory using:

```
mkdir lib/
pip3 install -t lib/ git+https://github.com/canonical/operator
```

> Note: Due to [pip#3826](https://github.com/pypa/pip/issues/3826), you may get
> a "can't combine user with prefix" if you are using pip3 provided by Ubuntu
> prior to 19.04, in which case you simply need to add `--system` to the command.

Your `src/charm.py` is the entry point for your charm logic. At a minimum, it
needs to define a subclass of `CharmBase` and pass that into the framework's
`main` function:

```python
import sys
sys.path.insert.append('lib')

from ops.charm import CharmBase
from ops.main import main

class MyCharm(CharmBase):
    pass


if __name__ == "__main__":
    main(MyCharm)
```

This charm does nothing, though, so you'll typically want to observe some Juju
events, such as `start`:

```python
class MyCharm(CharmBase):
    def __init__(self, *args):
        super().__init__(*args)
        self.framework.observe(self.on.start, self.on_start)

     def on_start(self, event):
        # Handle the event here.
```

Every standard event in Juju may be observed that way, and you can also easily
define your own events in your custom types.

Once your charm is ready, deploy it as normal with:

```
juju deploy .
```

You can sync subsequent changes from the framework by running the `pip`
command again with `--upgrade`.
