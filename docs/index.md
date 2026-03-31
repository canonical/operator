# Ops documentation

```{toctree}
:maxdepth: 2
:hidden: true

tutorial/index
howto/index
reference/index
explanation/index
```

Ops is a Python framework for writing and testing [Juju](https://canonical.com/juju) charms.

The core `ops` package provides an API to respond to Juju events and manage your charm's application. Ops also includes extra packages for testing and tracing charms.

Ops promotes consistent and maintainable charm code. Its APIs help you separate different aspects of your charm, such as managing the application's state and integrating with other charms.

## Get started

````{grid} 1 1 2 2
```{grid-item-card} Generate charm code for a web app
Use our CLI tools to turn your 12-factor app into a charm that's ready to deploy. We support Django, FastAPI, Go, and more!

<a class="show-external" href="https://documentation.ubuntu.com/charmcraft/latest/tutorial/" title="(in Charmcraft latest)" target="_blank">Write your first 12-factor app charm</a>
```
```{grid-item-card} Write your first charm from scratch
For a hands-on introduction to charm development with Ops, try our tutorials:

- [Write your first machine charm](tutorial/write-your-first-machine-charm)
- [Write your first Kubernetes charm](tutorial/from-zero-to-hero-write-your-first-kubernetes-charm/index)
```
````

## In this documentation

```{list-table}
:class: top-aligned

* - **Starting a project**
  - [Manage charms](howto/manage-charms) • [Write and structure charm code](howto/write-and-structure-charm-code)
* - **Running workloads**
  - [Manage packages on machines](howto/run-workloads-with-a-charm-machines) • [Manage Kubernetes workloads](howto/manage-containers/index)
* - **Adding functionality**
  - [Manage relations](howto/manage-relations) • [Manage configuration](howto/manage-configuration) • [More Juju features](#how-to-guides-managing-features)
* - **Testing & CI**
  - [Write unit tests](howto/write-unit-tests-for-a-charm) • [Write integration tests](howto/write-integration-tests-for-a-charm) • [Set up continuous integration](howto/set-up-continuous-integration-for-a-charm)
* - **Design & best practices**
  - [Holistic vs delta charms](explanation/holistic-vs-delta-charms) • [Follow best practices](#follow-best-practices) • [Trace your charm](howto/trace-your-charm)
* - **Publishing**
  - [Make your charm discoverable](howto/make-your-charm-discoverable)
```

## How this documentation is organised

This documentation uses the [Diátaxis documentation structure](https://diataxis.fr/).

- [Tutorials](tutorial/index)
- [How-to guides](howto/index)
- [Reference](reference/index), including [ops](reference/ops), [ops.testing](reference/ops-testing), and [ops.tracing](reference/ops-tracing)
- [Explanation](explanation/index)

## Related documentation

```{list-table}
:class: top-aligned

* - **{external+charmcraft:doc}`Charmcraft <index>`**
  - The CLI tool for initialising charms, packing charms, and interacting with [Charmhub](https://charmhub.io/). You'll find the {external+charmcraft:ref}`charmcraft.yaml specification <charmcraft-yaml-file>` especially helpful.
* - **{external+charmlibs:doc}`Charmlibs <index>`**
  - A listing of charm libraries and guidance on how to distribute your own libraries.
* - **[Concierge](https://github.com/canonical/concierge)**
  - A CLI tool for setting up charm development environments.
* - **{external+jubilant:doc}`Jubilant <index>`**
  - A Python library that wraps the Juju CLI. Use Jubilant for your integration tests.
* - **{external+juju:doc}`Juju <index>`**
  - The orchestration engine and CLI tool. You'll find the {external+juju:ref}`hooks reference <hook>` especially helpful. Juju's hooks correspond to events that your charm can observe.
* - **{external+pebble:doc}`Pebble <index>`**
  - The service manager inside containers (Kubernetes charms only). You'll find the {external+pebble:ref}`layer specification <layer-specification>` especially helpful.
```

## Demo charms

The Ops repository has several [demo charms](https://github.com/canonical/operator/tree/main/examples) that you can experiment with.

## Ops releases

[Read the release notes](https://github.com/canonical/operator/releases)

Ops releases are tracked in GitHub. To get notified when there's a new release, watch the [Ops repository](https://github.com/canonical/operator).

The `ops` package is [published on PyPI](https://pypi.org/project/ops/).

## Project and community

Ops is a member of the Ubuntu family. It's an open source project that warmly welcomes community contributions, suggestions, fixes and constructive feedback.

- [Report a bug](https://github.com/canonical/operator/issues)
- [Contribute](https://github.com/canonical/operator/blob/main/CONTRIBUTING.md)
- [Code of conduct](https://ubuntu.com/community/ethos/code-of-conduct)

For support, join [Charm Development](https://matrix.to/#/#charmhub-charmdev:ubuntu.com) on Matrix. You'll be able to chat with the maintainers of Ops (the Canonical Charm Tech team) and a friendly community of charm developers!

To follow along with updates and tips about charm development, join our [Discourse forum](https://discourse.charmhub.io/).
