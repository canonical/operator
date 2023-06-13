# The ops library

<!-- The text below is also at the top of ops/__init__.py. Keep in sync! -->

The ops library is a Python framework ([`available on PyPI`](https://pypi.org/project/ops/)) for developing
and testing [Juju](https://juju.is/) charms in a consistent way, using standard Python constructs
to allow for clean, maintainable, and reusable code.

A charm is an operator -- business logic encapsulated in a reusable software
package that automates every aspect of an application's life.

Charms written with ops support Kubernetes using Juju's "sidecar charm"
pattern, as well as charms that deploy to Linux-based machines and containers.

Charms should do one thing and do it well. Each charm drives a single
application and can be integrated with other charms to deliver a complex
system. A charm handles creating the application in addition to scaling,
configuration, optimisation, networking, service mesh, observability, and other
day-2 operations specific to the application.

The ops library is part of the Charm SDK (the other part being Charmcraft).
Full developer documentation for the Charm SDK is available at
https://juju.is/docs/sdk.

To learn more about Juju, visit https://juju.is/docs/olm.


## Pure Python

The framework provides a standardised Python object model that represents the
application graph, as well as an event-handling mechanism for distributed
system coordination and communication.

The latest version of ops requires Python 3.8 or above.

Juju itself is written in Go for efficient concurrency even in large
deployments. Charms can be written in any language, however, we recommend using
Python with this framework to make development easier and more standardised.
All new charms at Canonical are written using it.


## Getting started

A package of operator code is called a charmed operator or simply "charm".
You'll use [charmcraft](https://juju.is/docs/sdk/install-charmcraft) to
register your charm name and publish it when you are ready. You can follow one
of our [charming tutorials](https://juju.is/docs/sdk/tutorials) to get started
writing your first charm.


## Testing your charms

The framework provides a testing harness, so you can ensure that your charm
does the right thing in different scenarios, without having to create
a full deployment. Our [API documentation](https://ops.readthedocs.io/en/latest/#module-ops.testing)
has the details, including this example:

```python
harness = Harness(MyCharm)
# Do initial setup here
relation_id = harness.add_relation('db', 'postgresql')
# Now instantiate the charm to see events as the model changes
harness.begin()
harness.add_relation_unit(relation_id, 'postgresql/0')
harness.update_relation_data(relation_id, 'postgresql/0', {'key': 'val'})
# Check that charm has properly handled the relation_joined event for postgresql/0
self.assertEqual(harness.charm. ...)
```


## Talk to us

If you need help, have ideas, or would just like to chat with us, reach out on
the Charmhub [Mattermost].

We also pay attention to the Charmhub [Discourse].

And of course you can deep dive into the [API reference].

[Discourse]: https://discourse.charmhub.io/
[API reference]: https://ops.readthedocs.io/
[Mattermost]: https://chat.charmhub.io/charmhub/channels/charm-dev


## Development of the framework

See [HACKING.md](HACKING.md) for details on dev environments, testing, and so
on.
