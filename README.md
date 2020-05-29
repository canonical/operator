# The Operator Framework

The Operator Framework provides a simple, lightweight, and powerful way of
writing Juju charms, the best way to encapsulate operational experience in code.

The framework will help you to:

* model the integration of your services
* manage the lifecycle of your application
* create reusable and scalable components
* keep your code simple and readable

## Getting Started

Charms written using the operator framework are just Python code. The intention
is for it to feel very natural for somebody used to coding in Python, and
reasonably easy to pick up for somebody who might be a domain expert but not
necessarily a pythonista themselves.

The dependencies of the operator framework are kept as minimal as possible;
currently that's Python 3.5 or greater, and `PyYAML` (both are included by
default in Ubuntu's cloud images from 16.04 on).

<!--
If you're new to the world of Juju and charms, you should probably dive into our
[tutorial](/TBD).

If you know about Juju, and have written charms that didn't use the operator
framework (be it with reactive or without), we have an [introduction to the
operator framework](/TBD) just for you.

If you've gone through the above already and just want a refresher, or are
really impatient and need to dive in, feel free to carry on down.
-->
## A Quick Introduction

Operator framework charms are just Python code. The entry point to your charm is
a particular Python file. It could be anything that makes sense to your project,
but let's assume this is `src/charm.py`. This file must be executable (and it
must have the appropriate shebang line).

You need the usual `metadata.yaml` and (probably) `config.yaml` files, and a
`requirements.txt` for any Python dependencies.  In other words, your project
might look like this:

```
my-charm
├── config.yaml
├── metadata.yaml
├── requirements.txt
└── src/
    └── charm.py
```

`src/charm.py` here is the entry point to your charm code. At a minimum, it
needs to define a subclass of `CharmBase` and pass that into the framework's
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
$ juju deploy my-charm.charm
```

> 🛈 More information on [`charmcraft`](https://pypi.org/project/charmcraft/) can
> also be found on its [github page](https://github.com/canonical/charmcraft).

Happy charming!

## Testing your charms

The operator framework provides a testing harness, so that you can test that
your charm does the right thing when presented with different scenarios, without
having to have a full deployment to do so. `pydoc3 ops.testing` has the details
for that, including this example:

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

We also pay attention to Juju's [discourse], but currently we don't actively
post there outside of our little corner of the [docs]; most discussion at this
stage is on IRC.

[webchat]: https://webchat.freenode.net/#smooth-operator
[#smooth-operator]: irc://chat.freenode.net/%23smooth-operator
[discourse]: https://discourse.juju.is/c/charming
[docs]: https://discourse.juju.is/c/docs/operator-framework

## Operator Framework development

If you want to work in the framework *itself* you will need Python >= 3.5 and
the dependencies declared in `requirements-dev.txt` installed in your system.
Or you can use a virtualenv:

    virtualenv --python=python3 env
    source env/bin/activate
    pip install -r requirements-dev.txt

Then you can try `./run_tests`, it should all go green.

If you want to build the documentation you'll need the requirements from
`docs/requirements.txt`, or in your virtualenv

    pip install -r docs/requirements.txt

and then you can run `./build_docs`.
