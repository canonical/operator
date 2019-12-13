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

In your `lib/charm.py` file, you will need to define a class subclassed from
`ops.charm.CharmBase` which observes and handles at least `self.on.install`
(or `self.on.start` for K8s charms). You will then need to call the
`ops.main.main(YourCharm)` function, passing in the charm class that you
defined.

Once ready your charm code is ready, deploy the charm as normal with:

```
juju deploy .
```

You can sync subsequent changes from the framework by running the `pip`
command again with `--upgrade`.
