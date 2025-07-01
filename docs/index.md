# Ops documentation

```{toctree}
:maxdepth: 2
:hidden: true

tutorial/index
howto/index
reference/index
explanation/index
```

```{important}
This is the documentation for version 2 of Ops, which stopped being actively developed in June 2025. Ops 2 will continue to receive security and critical bug fixes.

- If your charm needs to support Python 3.8 (Ubuntu 20.04), use Ops 2.
- Otherwise, use Ops 3.

Ops 3 removed support for Python 3.8, but is otherwise compatible with Ops 2. See the [latest documentation](https://ops.readthedocs.io).
```

The Ops library (`ops`) is a Python framework for writing and testing Juju charms.

> [See it on PyPI](https://pypi.org/project/ops/)

The library provides:

- {ref}`ops_main_entry_point`, used to initialise and run your charm
- {ref}`ops`, the API to respond to Juju events and manage the application
- {ref}`ops_pebble`, the Pebble client, a low-level API for Kubernetes containers
- {ref}`ops_testing`, the recommended API for unit testing charms
- {ref}`ops_testing_harness`, the deprecated API for unit testing charms

You can structure your charm however you like, but with the `ops` library, you get a framework that promotes consistency and readability by following best practices. It also helps you organise your code better by separating different aspects of the charm, such as managing the application's state, handling integrating with other services, and making the charm easier to test.


---------

## In this documentation

````{grid} 1 1 2 2

```{grid-item-card} [Tutorial](tutorial/index)
:link: tutorial/index
:link-type: doc

**Start here**: a hands-on introduction to `ops` for new users
```

```{grid-item-card} [How-to guides](/index)
:link: howto/index
:link-type: doc

**Step-by-step guides** covering key operations and common tasks
```

````


````{grid} 1 1 2 2
:reverse:

```{grid-item-card} [Reference](/index)
:link: reference/index
:link-type: doc

**Technical information** - specifications, APIs, architecture
```

```{grid-item-card} [Explanation](/index)
:link: explanation/index
:link-type: doc

**Discussion and clarification** of key topics
```

````


---------


## Project and community

Ops is a member of the Ubuntu family. It’s an open source project that warmly welcomes community projects, contributions, suggestions, fixes and constructive feedback.

* **[Read our code of conduct](https://ubuntu.com/community/ethos/code-of-conduct)**:
As a community we adhere to the Ubuntu code of conduct.

* **[Get support](https://discourse.charmhub.io/)**:
Discourse is the go-to forum for all questions Ops.

* **[Join our online chat](https://matrix.to/#/#charmhub-charmdev:ubuntu.com)**:
Meet us in the #charmhub-charmdev channel on Matrix.

* **[Report bugs](https://github.com/canonical/operator/issues)**:
We want to know about the problems so we can fix them.

* **[Contribute docs](https://github.com/canonical/operator/blob/main/HACKING.md#contributing-documentation)**:
Get started on GitHub.
