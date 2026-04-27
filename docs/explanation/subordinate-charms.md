---
myst:
  html_meta:
    description: A subordinate charm runs alongside another charm, typically for managing hardware or system interactions.
---

(subordinate-charms)=
# Subordinate charms

A "subordinate" charm is a machine charm where each unit runs alongside a unit of another charm, called the "principal" charm. In this setup, the principal unit and corresponding subordinate unit always run on the same machine.

A subordinate charm typically communicates with the principal charm out of band. There isn't a dedicated Juju relation between a principal unit and the corresponding subordinate unit.

Subordinate charms aren't always appropriate. If possible, instead of writing a subordinate charm, write a regular charm that communicates over relations.

## When to use a subordinate charm

A subordinate charm is appropriate if you need to monitor or configure the underlying hardware. For example, [`hardware-observer`](https://github.com/canonical/hardware-observer-operator).

A subordinate charm is also appropriate if you need to manage how a particular workload interacts with the system. For example, how data is backed up or how connections are pooled. See [`pgbouncer`](https://github.com/canonical/pgbouncer-operator).

In general, a subordinate charm should be lighter weight than its intended principal charm.

## Declaring a subordinate charm

A subordinate charm is declared in `charmcraft.yaml`:

```yaml
subordinate: true
```

`charmcraft.yaml` doesn't specify a principal charm. A subordinate charm doesn't know which principal charm it will be deployed alongside. A Juju user is free to deploy a subordinate charm alongside any principal charm; your subordinate charm's code needs to decide whether it's running in the correct context.

When you document a subordinate charm, clearly state the intended principal charm.

```{important}
A subordinate charm can't control the Ubuntu base that its units run on. If the principal charm supports multiple bases, consider publishing a separate revision of the subordinate charm for each base.
```

## After deployment

TODO: What actually gets put on the machine? If I have two regular applications in my model, do I automatically get a unit of the subordinate for each unit of each regular application? So there isn't really a notion of "the" principal charm?

TODO: Watch out - other subordinate charms might be configuring the same machine.

TODO: What data can subordinate units see? Is there a peer relation with other units of the same subordinate charm? Review the relation how-to in Ops - "Note however that subordinate units cannot see each other's peer data".
