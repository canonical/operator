(charm-relation-interfaces)=
# Interface definitions

See also: {ref}`manage-interfaces`

An interface definition records what a Juju relation interface means. It describes what providers and requirers of the interface are expected to do, and the data they exchange. It is the source of truth for the data and behaviour of both sides of a relation.

Juju interfaces are untyped. For Juju to consider two charms compatible, the interface names of the two endpoints only need to be the same string. Two charms could have incompatible implementations of two different relations that happen to share a name. Keeping interface definitions in a single, shared location prevents this, and avoids a sprawl of subtly different interfaces with the same purpose.

Interface definitions are part of {external+charmlibs:doc}`Charmlibs <index>`. To browse the interfaces that already exist, see [Interfaces on Charmhub](https://charmhub.io/interfaces) or the {external+charmlibs:doc}`interface specifications <reference/interfaces>` in the Charmlibs documentation.

```{note}
Interface definitions used to live in the `canonical/charm-relation-interfaces` repository, which is now archived. Contribute new interfaces and updates to `charmlibs` instead.
```

## Using interfaces

If your charm provides a service, check whether an interface for it already exists. A similar interface might also exist that can be extended to support what you need. If your charm needs a service, such as a database, an ingress URL, or an authentication endpoint, check whether there is an interface you can use and which charms provide it.

Every interface should have an official library that implements it, and every charm that provides or requires the interface should use that library. The same people maintain an interface's library and its definition.

Interface libraries are published on PyPI as `charmlibs-interfaces-<interface name>`, and you import them as `charmlibs.interfaces.<interface name>`. For more information, see {external+charmlibs:ref}`charm-libs-interface` and the {external+charmlibs:ref}`list of interface libraries <interface-libs-listing>`.
