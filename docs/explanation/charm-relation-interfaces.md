(charm-relation-interfaces)=
# Interface definitions

See also: {ref}`manage-interfaces`

An interface definition records what a Juju relation interface means. It describes what providers and requirers of the interface are expected to do, and the data they exchange. It is the source of truth for the data and behaviour of both sides of a relation.

Juju interfaces are untyped. For Juju to consider two charms compatible, the interface names of the two endpoints only need to be the same string. Two charms could have incompatible implementations of two different relations that happen to share a name. Keeping interface definitions in a single, shared location prevents this, and avoids a sprawl of subtly different interfaces with the same purpose.

Interface definitions are maintained in the [`charmlibs` monorepo](https://github.com/canonical/charmlibs). To browse the interfaces that already exist, see [Interfaces on Charmhub](https://charmhub.io/interfaces) or the {external+charmlibs:doc}`interface specifications <reference/interfaces>` in the Charmlibs documentation.

```{note}
Interface definitions used to live in the `canonical/charm-relation-interfaces` repository, which is now archived. Contribute new interfaces and updates to `charmlibs` instead.
```

## Using interface definitions

If your charm provides a service, check whether an interface for it already exists. A similar interface might also exist that can be extended to support what you need. If your charm needs a service, such as a database, an ingress URL, or an authentication endpoint, check whether there is an interface you can use and which charms provide it.

There are three actors in play:

* **The owner of the specification.** This is the interface definition in `charmlibs`.
* **The owner of the implementation.** This is often the team whose charm provides a workload that implements one side of the interface.
* **The interface user.** This is a charm that wants to use the interface, as either the requirer or the provider.

The interface user needs an implementation of the interface. Interface libraries are published on PyPI as `charmlibs-interfaces-<interface name>` and imported as `charmlibs.interfaces.<interface name>`.

The owner of the implementation needs the specification, to check that the implementation complies with it.
