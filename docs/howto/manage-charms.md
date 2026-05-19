(manage-charms)=
# How to manage charms

> See first: {external+juju:ref}`Juju | Build a charm <build-a-charm>`, {external+charmcraft:ref}`Charmcraft | Manage charms <manage-charms>`

(prepare-your-environment)=
## Prepare your environment

You'll need the following tools:

- **Charmcraft** - For initialising and packing your charm. See {external+charmcraft:ref}`Charmcraft | Manage Charmcraft <manage-charmcraft>`.
- **uv** - For managing your charm's dependencies, including Ops. See [Installing uv](https://docs.astral.sh/uv/getting-started/installation/).
- **tox** - For running checks and tests. To install tox: `uv tool install tox --with tox-uv`.

To deploy your charm locally and to run integration tests, you'll also need a Juju controller.

[Concierge](https://github.com/canonical/concierge) can automatically install and configure most of the tools that you'll need. Instead of installing everything on your host machine, consider using a [Multipass](https://canonical.com/multipass/install) virtual machine.

> See more:
>
> - [Prepare your environment to develop Kubernetes charms](#set-up-your-development-environment)
> - [Prepare your environment to develop machine charms](#machine-charm-tutorial-environment)
> - [Prepare a continuous integration environment](#set-up-ci-integration)

## Initialise your charm project

Use Charmcraft to quickly initialise your charm project. This generates the
folder structure, creates placeholder configuration and code files, and
configures development tooling.

> See more:
>
> - {ref}`init-charm`

(develop-your-charm)=
## Develop your charm

The Charmcraft profile has configured some commands to help you develop your charm:

- Run `tox` to format and lint the code, and run static type checking and the
  charm unit tests.
- Run `tox -e integration` to run the charm integration tests.
- Run `tox list` to see the available commands.

```{admonition} Best practice
:class: hint

All charms should provide the commands configured by the Charmcraft profile, to
allow easy testing across the charm ecosystem. It's fine to tweak the
configuration of individual tools, or to add additional commands, but keep the
command names and meanings that the profile provides.
```

The following tools can also be useful during development:

- To prepare an environment for running integration tests, such as in continuous integration, use [Concierge](https://github.com/canonical/concierge) or [`actions-operator`](https://github.com/charmed-kubernetes/actions-operator).
- The [`charming-actions`](https://github.com/canonical/charming-actions) repository includes actions to ensure that libraries are up-to-date, publish charms and libraries, and more.

The essence of a charm is the ``src/charm.py`` file. This is the entry point for
your code whenever Juju emits an event, and defines the interface between Juju
and the charm workflow.

> See more:
>
> - {ref}`manage-containers`
> - {ref}`run-workloads-with-a-charm-machines`
> - {ref}`write-and-structure-charm-code`
> - {ref}`write-unit-tests-for-a-charm`
> - {ref}`write-integration-tests-for-a-charm`
> - {ref}`set-up-ci`
> - {ref}`log-from-your-charm`
> - {ref}`debug-your-charm`

The next thing to do is add functionality to your charm.
As you do that, you'll frequently pack, test, and debug your charm.

One of the powers of charms is their reusability. As such, do not try to
duplicate functionality already achieved by an existing charm – rather, make
your charm take advantage of the [charm ecosystem](https://charmhub.io) by
supporting integrating with existing charm solutions for observability,
identity, scaling, and so on.

This also helps you stay compliant with another fundamental rule in charms,
namely that, following the Unix philosophy, each charm should do one thing and
do it well.

> See more:
>
> * Make use of core Juju functionality
>   - {ref}`manage-storage`
>   - {ref}`manage-resources`
>   - {ref}`manage-secrets`
> * Add functionality
>   - {external+charmcraft:ref}`Charmcraft | Add runtime details to a charm <add-runtime-details-to-a-charm>`
>   - {ref}`manage-actions`
>   - {ref}`manage-configuration`
>   - {ref}`manage-opened-ports`
> * {external+charmcraft:ref}`Charmcraft | Manage charms > Pack a charm <pack-a-charm>`
> * {external+juju:ref}`Juju | Manage charms > Deploy a charm <deploy-a-charm>` (you'll need to follow the "Deploy a local charm" example)
> * {external+juju:ref}`Juju | Manage charms > Debug a charm <debug-a-charm>`

## Publish your charm

When you're ready, you'll publish your charm on Charmhub.

> See more:
>
> * [](#publish-your-charm)

A charm is software: while there can be milestones, there is never a finish
line. So, keep investing in every bit of your charm so that it looks and feels
professional – from polishing metadata (including an icon, a website, docs, and
so on) through polishing features (for example, working to ensure correct and
reliable behavior, adding libraries so people can quickly integrate with your
charm, and so on) all the way to turning it into a successful open source
project with a community that enjoys it and wants to contribute to it.
