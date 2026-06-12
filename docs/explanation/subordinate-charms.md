---
myst:
  html_meta:
    description: A subordinate charm runs alongside another charm, typically for managing hardware or system interactions.
---

(subordinate-charms)=
# Subordinate charms

A "subordinate" charm is a machine charm where each unit runs alongside a unit of another charm, called the "principal" charm. In this setup, the principal unit and corresponding subordinate unit always run on the same machine.

When you deploy a subordinate charm, Juju doesn't create any units of the application. Instead, Juju creates subordinate units when you integrate with a principal charm. See {external+juju:ref}`Juju | Subordinate charm <subordinate-charm>` and {external+juju:ref}`Juju | Subordinate relation <subordinate-relation>`.

## When to use a subordinate charm

A subordinate charm is appropriate if you need to monitor or configure the underlying hardware. For example, [`hardware-observer`](https://github.com/canonical/hardware-observer-operator).

A subordinate charm is also appropriate if you need to manage how a particular workload interacts with the system. For example, how data is backed up or how connections are pooled. See [`pgbouncer`](https://github.com/canonical/pgbouncer-operator).

## Declaring a subordinate charm

A subordinate charm is declared in `charmcraft.yaml`:

```yaml
subordinate: true
```

`charmcraft.yaml` doesn't specify a principal charm. A subordinate charm doesn't know which principal charm it will be deployed alongside.

Instead of specifying a principal charm, you define an endpoint with `scope: container`. The endpoint can use an application-specific interface or the generic `juju-info` interface. See {external+juju:ref}`Juju | The implicit juju-info relation endpoint <the-implicit-juju-info-relation-endpoint>`.

The Juju user is free to integrate a subordinate charm with any principal charm that supports the container-scoped endpoint. If you define a `juju-info` endpoint instead of an application-specific endpoint, this means that the subordinate charm can be integrated with any other charm as principal. The subordinate charm's code needs to determine whether it's running in the correct context.

When you document a subordinate charm, clearly state which charms your subordinate charm is intended to be used with and how they should be integrated.

## Runtime constraints

A subordinate charm can't control the Ubuntu base that its units run on. When you document which charms your subordinate charm is intended to be used with, mention any differences in supported bases.

A subordinate unit shouldn't assume it's the only unit trying to configure the hardware or system. Subordinate units should minimise side effects when writing configuration and installing/uninstalling packages. For general advice, see {ref}`run-workloads-with-a-charm-machines`.
