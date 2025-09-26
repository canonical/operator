(charm-relation-interfaces)=
# Charm-relation-interfaces

> See also: {ref}`manage-interfaces`

[`charm-relation-interfaces`](https://github.com/canonical/charm-relation-interfaces) is a repository containing specifications, databag schemas and interface tests for Juju relation interfaces. In other words, it is the source of truth for data and behavior of providers and requirers of relations.

The purpose of this project is to provide uniformity in the landscape of all possible relations and promote charm interoperability.

Juju interfaces are untyped, which means that for juju to think two charms can be integrated all it looks at is whether the interface names of the two endpoints you're trying to connect are the same string. But it might be that the two charms have different, incompatible implementations of two different relations that happen to have the same name.

In order to prevent two separate charms from rolling their own relation with the same name, and prevent a sprawl of many subtly different interfaces with similar semantics and similar purposes, we introduced `charm-relation-interfaces`.

## Using `charm-relation-interfaces`

If you have a charm that provides a service, you should search `charm-relation-interfaces` (or directly charmhub in the future) and see if it exists already, or perhaps a similar one exists that lacks the semantics you need and can be extended to support it.

Conversely, if the charm you are developing needs some service (a database, an ingress URL, an authentication endpoint...)  you should search `charm-relation-interfaces` to see if there is an interface you can use, and to find existing charms that provide it.

There are three actors in play:

* **the owner of the specification** of the interface, which also owns the tests that can be used to verify "does charm X 'really' support this interface?". This is the `charm-relation-interfaces` repo.
* **the owner of the implementation** of an interface. In practice, this often is the charm that owns the charm library with the reference implementation for an interface.
* **the interface user**: a charm that wants to use the interface (either as requirer or as provider).

The interface user needs the implementation (typically, the provider also happens to be the owner and so it already has the implementation). This is addressed by `charmcraft fetch-lib`.

The owner of the implementation needs the specification, to help check that the implementation is in fact compliant.

## Repository structure

For each interface, the charm-relation-interfaces repository hosts:
- the **specification**: a semi-formal definition of what the semantics of the interface is, and what its implementations are expected to do in terms of both the provider and the requirer
- a list of **reference charms**: these are the charms that implement this interface, typically, the owner of the charm library providing the original implementation.
- the **schema**: pydantic models unambiguously defining the accepted unit and application databag contents for provider and requirer.
- the **interface tests**: python tests that can be run to verify that a charm complies with the interface specification.


## Charm relation interfaces in Charmhub
Charmhub will, for all charms using the interface, verify that they implement it correctly (regardless of whether they use the 'official' implementation or they roll their own) in order to give the charm a happy checkmark on `charmhub.io`. In order to do that it will need to fetch the specification (from `charm-relation-interfaces`) *and* the charm repo, because we can't know what implementation they are using: we need the source code.
