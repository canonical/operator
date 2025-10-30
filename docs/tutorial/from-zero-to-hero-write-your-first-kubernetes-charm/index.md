(from-zero-to-hero-write-your-first-kubernetes-charm)=
# From zero to hero: Write your first Kubernetes charm

This tutorial will guide you through the steps of writing a Kubernetes charm for an application.

By the end of the tutorial, you'll have equipped the application with operational logic and used Juju to deploy the application to a local Kubernetes cluster.
You'll also have learned how to implement typical functionality of a charm, including configuration, relations, and actions.

## What you'll need

- A workstation. For example, a laptop with an amd64 architecture. You'll need sufficient resources to launch a virtual machine with 4 CPUs, 8 GB RAM, and 50 GB disk space.
- Familiarity with Linux.
- Familiarity with the Python programming language, including Object-Oriented Programming and event handlers.

It will also help if you're familiar with Juju and Kubernetes, but don't worry if you're new to these topics.
This tutorial will guide you through each step.

## What you'll do

```{toctree}
:maxdepth: 1

study-your-application
set-up-your-development-environment
create-a-minimal-kubernetes-charm
make-your-charm-configurable
integrate-your-charm-with-postgresql
expose-operational-tasks-via-actions
observe-your-charm-with-cos-lite
```

(tutorial-kubernetes-next-steps)=
## Next steps

By the end of this tutorial, you'll have written and tested a Kubernetes charm that includes some typical functionality.
Congratulations!

```{admonition} Did you know?
:class: tip

Writing a charm is also known as "charming", and you are now a charmer!
```

As you write your own charm, use [](#write-and-structure-charm-code) as a guide to best practices. For an overview of the whole charm development process, see [](#manage-charms).

As you prepare for other people to use your charm, you'll publish your charm on Charmhub. See {external+charmcraft:ref}`Charmcraft | Publish a charm on Charmhub <publish-a-charm>`. At this stage, make sure to also review [](#charm-maturity) and [](#make-your-charm-discoverable).

There's plenty more to explore:

| If you're wondering... | visit...             |
|------------------------|----------------------|
| How do I...?           | {ref}`how-to-guides` |
| What is...?            | {ref}`reference`     |
| Why...? So what?       | {ref}`explanation`   |
