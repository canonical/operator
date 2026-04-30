---
myst:
  html_meta:
    description: A subordinate charm runs alongside another charm, typically for managing hardware or system interactions.
---

(subordinate-charms)=
# Subordinate charms

A "subordinate" charm is a machine charm where each unit runs alongside a unit of another charm, called the "principal" charm. In this setup, the principal unit and corresponding subordinate unit always run on the same machine.

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

`charmcraft.yaml` doesn't specify a principal charm. A subordinate charm doesn't know which principal charm it will be deployed alongside. A Juju user is free to deploy a subordinate charm alongside any principal charm; your subordinate charm's code needs to determine whether it's running in the correct context.

When you document a subordinate charm, clearly state the intended principal charm.

## Runtime constraints

A subordinate charm can't control the Ubuntu base that its units run on. If the principal charm supports multiple bases, consider publishing a separate revision of the subordinate charm for each base.

A subordinate unit shouldn't assume it's the only unit trying to configure the hardware or system. Subordinate units should minimise side effects when writing configuration and installing/uninstalling packages. For general advice, see {ref}`run-workloads-with-a-charm-machines`.
