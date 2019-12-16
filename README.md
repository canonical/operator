# Operator Framework for Charms

This framework is not yet stable and is subject to change, but is available
for early testing.

## Getting Started

Start by creating a charm directory with at least the following files:

* `lib/charm.py` (must be executable and use Python 3.6+)
* `hooks/install` (or `hooks/start` for K8s charms) sym-linked to `../lib/charm.py`
* `metadata.yaml`

Then install the framework into the `lib/` directory using:

```
pip install -t lib/ https://github.com/canonical/operator
```

Your `lib/charm.py` is the entry point for your charm logic. The minimum it
needs to do is define a subclass of `CharmBase` and call the framework's main
function:

```python
from ops.charm import CharmBase
from ops.main import main

class MyCharm(CharmBase):
    pass

if __name__ == "__main__":
    main(MyCharm)
```

This charm does nothing, though. Typically, you'll want to observe specific
Juju events with logic similar to this:

```python
class MyCharm(CharmBase):
    def __init__(self, *args):
        super().__init__(*args)
        self.framework.observe(self.on.start, self.on_start)

     def on_start(self, event):
        # Handle the event here.
```

Every standard event in juju may observed that way, and you can also easily
define your own events in your custom types.

Once ready your charm code is ready, deploy the charm as normal with:

```
juju deploy .
```

You can sync subsequent changes from the framework by running the `pip`
command again with `--upgrade`.
