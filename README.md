# The Operator Framework

The Operator Framework simplifies Kubernetes operator development for
better application management.

A Kubernetes operator is a container that drives lifecycle management,
configuration, integration and daily actions for an application.
Operators simplify software management and operations. They capture
app domain knowledge from experts in a reusable component that can
be shared.

This project extends the operator pattern to make it universal, not just
for Kubernetes but also operators for traditional Linux or Windows
application management.

Operators use an Operator Lifecycle Manager (OLM) to coordinate their
work in a cluster. The system uses Golang for concurrent event
processing under the hood, but enables the operators to be written in
Python.

## Simple, composable operators

Operators should 'do one thing and do it well'. Each operator drives a
single microservice and can be composed with other operators to deliver
a complex application.

It is better to have small, reusable operators that each drive a single
microservice very well. The operator handles instantiation, scaling,
configuration, optimisation, networking, service mesh, observability,
and day-2 operations specific to that microservice.

Operator composition takes place through declarative integration in
the OLM. Operators declare integration endpoints, and discover lines of
integration between those endpoints dynamically at runtime.

## Pure Python operators

The framework provides a standard Python library and object model that
represents the application graph, and an event distribution mechanism for
distributed system coordination and communication.

The OLM is written in Golang for efficient concurrency in event handling
and distribution. The operators interact with the OLM in a language-neutral
fashion. We recommend this Python framework for ease of design, development
and collaboration.

## Better collaboration

Operator developers publish Python libraries that make it easy to integrate
your operator with their operator. The framework includes standard tools
to distribute these integration libraries and keep them up to date.

Development collaboration happens at [Charmhub.io](https://charmhub.io/) where
operators are published along with integration libraries. Design and
code review discussions are hosted in the
[Charmhub forum](https://discourse.charmhub.io/). We recommend the
[Open Operator Manifesto](https://charmhub.io/manifesto) as a guideline for
high quality operator engineering.

## Event serialization and operator services

Distributed systems can be hard! So this framework exists to make it much
simpler to reason about operator behaviour, especially in complex deployments.

Coordination between operators is provided by a cluster-wide event
distribution system. Events are serialized to avoid race conditions in any
given container or machine. This greatly simplifies the development of
operators for high availability, scale-out and integrated applications.

Operators can request services such as leader election, persistent state,
secrets and messaging from the operator lifecycle manager.

## Model-driven Operator Lifecycle Manager

A key goal of the project is to improve the user experience for admins
working with multiple different operators.

We embrace model-driven operations in the Operator Lifecycle Manager.
Admins describe the application graph of integrated microservices, and
the OLM then drives instantiation. A change in the model is propagated
to all affected operators, reducing the duplication of effort and
repetition normally found in operating a complex topology of services.

Administrative actions, updates, configuration and integration are all
driven through the OLM.

# Getting started

A package of operator code is called a charm. You will use the charmcraft
tool to register your operator name, and publish it when you are ready.

```
$ sudo snap install charmcraft --beta
charmcraft (beta) 0.6.0 from John Lenton (chipaca) installed
```

Charms written using the operator framework are just Python code. The goal
is to feel natural for somebody used to coding in Python, and reasonably
easy to learn for somebody who is not a pythonista.

The dependencies of the operator framework are kept as minimal as possible;
currently that's Python 3.5 or greater, and `PyYAML` (both are included by
default in Ubuntu's cloud images from 16.04 on).

## The Juju OLM

The [Juju OLM](https://juju.is/) makes it possible to create operators not
only on Kubernetes, where they run in containers and drive cloud-native
applications, but also on traditional Linux or Windows environments.

<!--
If you're new to the world of Juju and charms, you should probably dive into our
[tutorial](/TBD).

If you have used Juju, or have written charms that didn't use the operator
framework, we have an [introduction to the operator framework](/TBD) just
for you.

If you've gone through the above already and just want a refresher, or are
really impatient and need to dive in, feel free to carry on down.
-->

## A Quick Introduction

Make an empty directory `my-charm` and cd into it. Then start a new charm
with:

```
$ charmcraft init
All done.
There are some notes about things we think you should do.
These are marked with ‘TODO:’, as is customary. Namely:
      README.md: fill out the description
      README.md: explain how to use the charm
  metadata.yaml: fill out the charm's description
  metadata.yaml: fill out the charm's summary
```

Charmed operators are just Python code. The entry point to your charm can
be any filename, by default this is `src/charm.py` which must be executable
(and probably have `#!/usr/bin/env python3` on the first line).

You need a `metadata.yaml` to describe your charm, and if you will support
configuration of your charm then `config.yaml` files is required too. The
`requirements.txt` specifies any Python dependencies.



```
$ tree my-charm/
my-charm/
├── actions.yaml
├── config.yaml
├── LICENSE
├── metadata.yaml
├── README.md
├── requirements-dev.txt
├── requirements.txt
├── run_tests
├── src
│   └── charm.py
├── tests
│   ├── __init__.py
│   └── my_charm.py
```

`src/charm.py` here is the entry point to your charm code. At a minimum, it
needs to define a subclass of `CharmBase` and pass that into the framework
`main` function:

```python
from ops.charm import CharmBase
from ops.main import main

class MyCharm(CharmBase):
    def __init__(self, *args):
        super().__init__(*args)
        self.framework.observe(self.on.start, self.on_start)

    def on_start(self, event):
        # Handle the start event here.

if __name__ == "__main__":
    main(MyCharm)
```

That should be enough for you to be able to run

```
$ charmcraft build
Done, charm left in 'my-charm.charm'
$ juju deploy ./my-charm.charm
```

> 🛈 More information on [`charmcraft`](https://pypi.org/project/charmcraft/) can
> also be found on its [github page](https://github.com/canonical/charmcraft).

Happy charming!

# Testing your charms

The operator framework provides a testing harness, so that you can check your
charm does the right thing when presented with different scenarios, without
having to have a full deployment. `pydoc3 ops.testing` has the details,
including this example:

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
IRC: we're in [#smooth-operator] on freenode (or try the [webchat]).

We also pay attention to the [Charmhub discourse](https://discourse.charmhub.io/)

You can also deep dive into the [API docs] if that's your thing.

[webchat]: https://webchat.freenode.net/#smooth-operator
[#smooth-operator]: irc://chat.freenode.net/%23smooth-operator
[discourse]: https://discourse.juju.is/c/charming
[API docs]: https://ops.rtfd.io/

## Operator Framework development

If you want to work in the framework *itself* you will need Python >= 3.5 and
the dependencies declared in `requirements-dev.txt` installed in your system.
Or you can use a virtualenv:

    virtualenv --python=python3 env
    source env/bin/activate
    pip install -r requirements-dev.txt

Then you can try `./run_tests`, it should all go green.

For improved performance on the tests, ensure that you have PyYAML
installed with the correct extensions:

    apt-get install libyaml-dev
    pip install --force-reinstall --no-cache-dir pyyaml

If you want to build the documentation you'll need the requirements from
`docs/requirements.txt`, or in your virtualenv

    pip install -r docs/requirements.txt

and then you can run `./build_docs`.
