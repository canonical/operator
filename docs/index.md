---
relatedlinks: "[Charmcraft](https://documentation.ubuntu.com/charmcraft/stable/), [Charmlibs](https://documentation.ubuntu.com/charmlibs/), [Concierge](https://github.com/canonical/concierge), [Jubilant](https://documentation.ubuntu.com/jubilant/), [Juju](https://documentation.ubuntu.com/juju/3.6/), [Pebble](https://documentation.ubuntu.com/pebble/)"
---

# Ops documentation

```{toctree}
:maxdepth: 2
:hidden: true

tutorial/index
howto/index
reference/index
explanation/index
```

Ops is a Python framework for writing and testing [Juju](https://juju.is/) charms.

The core `ops` package provides an API to respond to Juju events and manage the charm's application. Ops also includes extra packages for testing and tracing charms.

Ops promotes consistent and maintainable charm code. Its APIs help you separate different aspects of the charm, such as managing the application's state and integrating with other charms.

## In this documentation

````{grid} 1 1 2 2

```{grid-item-card} [Tutorials](tutorial/index)
**Start here:** hands-on introductions to Ops, guiding you through writing charms
- [Write your first machine charm](tutorial/write-your-first-machine-charm)
- [Write your first Kubernetes charm](tutorial/from-zero-to-hero-write-your-first-kubernetes-charm/index)
```

```{grid-item-card} [How-to guides](howto/index)
**Step-by-step guides** covering key operations and common tasks
- [Manage charms](howto/manage-charms)
- [Manage relations](howto/manage-relations)
- [Manage containers](howto/manage-containers/index)
```

````

````{grid} 1 1 2 2
:reverse:

```{grid-item-card} [Reference](reference/index)
**Technical information** about Ops APIs
- [ops](reference/ops)
- [ops.testing](reference/ops-testing), [ops.tracing](reference/ops-tracing)
- [ops.pebble](reference/pebble)
```

```{grid-item-card} [Explanation](explanation/index)
**Discussion and clarification** of key topics
- [Testing](explanation/testing)
- [Tracing](explanation/tracing)
- [Security](explanation/security)
```

````

## Releases

[Read the release notes](https://github.com/canonical/operator/releases)

Ops releases are tracked in GitHub. To get notified when there's a new release, watch the [Ops repository](https://github.com/canonical/operator).

The `ops` package is [published on PyPI](https://pypi.org/project/ops/).

## Project and community

Ops is a member of the Ubuntu family. It's an open source project that warmly welcomes community contributions, suggestions, fixes and constructive feedback.

- [Report a bug](https://github.com/canonical/operator/issues)
- [Contribute](https://github.com/canonical/operator/blob/main/CONTRIBUTING.md)
- [Code of conduct](https://ubuntu.com/community/ethos/code-of-conduct)

For support, join [Charm Development](https://matrix.to/#/#charmhub-charmdev:ubuntu.com) on Matrix. You'll be able to chat with the maintainers of Ops (the Canonical Charm Tech team) and a friendly community of charm developers!

## Looking for more?

The Ops repository has several [demo charms](https://github.com/canonical/operator/tree/main/examples) that you can experiment with.

If you're new to charm development, the {external+charmcraft:ref}`Charmcraft tutorials <tutorial>` are a great place to start. The tutorials don't require any experience with Ops. You can learn about Ops after completing one of the tutorials.

To follow along with updates and tips about charm development, join our [Discourse forum](https://discourse.charmhub.io/).

[Learn more about the Juju ecosystem](https://juju.is/docs)
