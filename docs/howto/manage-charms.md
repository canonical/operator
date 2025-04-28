(manage-charms)=
# How to manage charms

> See first: {external+juju:ref}`Juju | Build a charm <build-a-charm>`, {external+charmcraft:ref}`Charmcraft | Manage charms <manage-charms>`

## Prepare your environment

Hit the ground running with Ops by setting up standard project structure and tools.

> See more: {external+charmcraft:ref}`Charmcraft | Manage Charmcraft <manage-charmcraft>`

Other useful tools:

```{tip}
To prepare an environment for running integration tests, such as in CI, use
the `concierge tool <https://github.com/jnsgruk/concierge>`_ or the
`actions-operator <https://github.com/charmed-kubernetes/actions-operator>`_.
```

```{tip}
The `charming-actions <https://github.com/canonical/charming-actions>`_
repository includes actions to ensure that libraries are up-to-date, publish
charms and libraries, and more.
```

## Initialise your charm project

Use Charmcraft to quickly initialise your charm project. This generates the
folder structure, creates placeholder configuration and code files, and
configures development tooling.

The Charmcraft profiles also all provide the recommended tooling and
configuration for developing charms. You'll need to install
[`tox`](https://tox.wiki/en/stable/), and can then run ``tox list`` in the root
folder to see the available commands.

> See more:
>
> * {external+charmcraft:ref}`Charmcraft | Manage charms > Initialize a charm <initialise-a-charm>` (see also the best practice note on setting up a repository and considering your CI)
> * [Charmcraft | Manage charms > Add charm project metadata, an icon, docs](https://canonical-charmcraft.readthedocs-hosted.com/en/latest/howto/manage-charms/#add-charm-project-metadata-an-icon-docs)

## Develop your charm

The Charmcraft profile you've chosen has configured a number of recommended
tools for developing charms. To use these, [install
`tox`](https://tox.wiki/en/stable/installation.html#as-tool) on your development
server.

```{tip}
If you use the `charm-dev` [Multipass](https://canonical.com/multipass)
blueprint or the [`concierge`](https://github.com/jnsgruk/concierge) tool to
configure your development environment, you'll already have `tox` installed.
```

- Run `tox` to format and lint the code, and run static type checking and the
  charm unit tests.
- Run `tox -e integration` to run the charm integration tests.
- Run `tox list` to see the available commands.

```{admonition} Best practice
:class: hint

All charms should provide the commands configured by the charmcraft profiles, to
allow easily testing across the charm ecosystem. It's fine to tweak the
configuration of individual tools, or to add additional commands, but keep the
command names and meanings that the profiles provide.
```

```{admonition} Best practice
:class: hint

The quality assurance pipeline of a charm should be automated using a
continuous integration (CI) system.
```

<!--
TODO: Add a reference link in charmcraft for the link above and the 'runtime details' one below, and switch over to external refs.
-->

The essence of a charm is the ``src/charm.py`` file. This is the entry point for
your code whenever Juju emits an event, and defines the interface between Juju
and the charm workflow.

> See more: {ref}`run-workloads-with-a-charm-kubernetes`, {ref}`run-workloads-with-a-charm-machines`, {ref}`write-and-structure-charm-code`, {ref}`write-unit-tests-for-a-charm`, {ref}`write-integration-tests-for-a-charm`, {ref}`manage-logs`

The next thing to do is add functionality to your charm.
As you do that, you'll frequently pack, test, and debug your charm.
Finally, when you're ready, you'll publish your charm on Charmhub.

```{admonition} Best practice
:class: hint
One of the powers of charms is their reusability. As such, do not try to
duplicate functionality already achieved by an existing charm – rather, make
your charm take advantage of the [charm ecosystem](https://charmhub.io) by
supporting integrating with existing charm solutions for observability,
identity, scaling, and so on.

This also helps you stay compliant with another fundamental rule in charms,
namely that, following the Unix philosophy, each charm should do one thing and
do it well.
```

> See more:
>
> * Make use of core Juju functionality
>   - {ref}`manage-storage`
>   - {ref}`manage-resources`
>   - {ref}`manage-secrets`
> * Add functionality
>   - [Charmcraft | Add runtime details to a charm](https://canonical-charmcraft.readthedocs-hosted.com/en/latest/howto/manage-charms/#add-runtime-details-to-a-charm)
>   - {ref}`manage-actions`
>   - {ref}`manage-configurations`
>   - {ref}`manage-opened-ports`
> * {external+charmcraft:ref}`Charmcraft | Manage charms > Pack a charm <pack-a-charm>`
> * {external+juju:ref}`Juju | Manage charms > Deploy a charm <deploy-a-charm>` (you'll need to follow the "Deploy a local charm" example)
> * {external+juju:ref}`Juju | Manage charms > Debug a charm <debug-a-charm>`

## Publish your charm

When you're ready, you'll publish your charm on Charmhub.

> See more:
>
> * {external+charmcraft:ref}`Charmcraft | Publish a charm on Charmhub <publish-a-charm>` (see especially the note on requesting formal review for your charm)

A charm is software: while there can be milestones, there is never a finish
line. So, keep investing in every bit of your charm so that it looks and feels
professional – from polishing metadata (including an icon, a website, docs, and
so on) through polishing features (for example, working to ensure correct and
reliable behavior, adding libraries so people can quickly integrate with your
charm, and so on) all the way to turning it into a successful open source
project with a community that enjoys it and wants to contribute to it.
