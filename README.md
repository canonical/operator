# Operators Framework for Charms

This framework is not yet stable and is subject to change, but is available
for early testing.

## Getting Started

The best way to get started is to download a copy of the [skeleton charm][].
Once you have a copy, you will first need to install the framework into the
`lib/` directory:

```
pip install -t lib/ https://github.com/canonical/operator
```

You can then modify the `lib/charm.py` code and, once ready, deploy the charm:

```
juju deploy .
```

You can sync subsequent changes from the framework by running the `pip`
command again with `--upgrade`.


[skeleton charm]: https://github.com/johnsca/charm-skeleton
