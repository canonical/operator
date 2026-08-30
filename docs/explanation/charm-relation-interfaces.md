(charm-relation-interfaces)=
# Interface definitions

See also: {ref}`manage-interfaces`

Interface definitions live in the [`interfaces` directory of the `charmlibs` monorepo](https://github.com/canonical/charmlibs/tree/main/interfaces). For each interface they record specifications, databag schemas, and interface tests for Juju relation interfaces. In other words, they are the source of truth for the data and behaviour of providers and requirers of relations.

```{note}

Interface definitions used to live in a standalone repository, `canonical/charm-relation-interfaces`, which was archived in November 2025. All interfaces have been migrated into the [`charmlibs` monorepo](https://github.com/canonical/charmlibs), where new interfaces and updates should now be contributed. See https://canonical.com/juju/docs/charmlibs/ for more information.
```

The purpose of consolidating interface definitions is to provide and promote charm interoperability.

Juju interfaces are untyped, which means that for Juju to think two charms can be integrated all that is required is for the interface names of the two endpoints you're trying to connect to be the same string. But it might be that the two charms have different, incompatible implementations of two different relations that happen to have the same name.

In order to prevent two separate charms from rolling their own relation with the same name, and prevent a sprawl of many subtly different interfaces with similar semantics and similar purposes, interface definitions are kept in a single, canonical location.

## Using interface definitions

If you have a charm that provides a service, you should search the [`interfaces` directory in `charmlibs`](https://github.com/canonical/charmlibs/tree/main/interfaces) (or directly Charmhub in the future) and see if an interface exists already, or perhaps a similar one exists that lacks the semantics you need and can be extended to support it.

Conversely, if the charm you are developing needs some service (a database, an ingress URL, an authentication endpoint...)  you should search the interface definitions to see if there is an interface you can use, and to find existing charms that provide it.

There are three actors in play:

* **the owner of the specification** of the interface, which also owns the tests that can be used to verify "does charm X 'really' support this interface?". This is the relevant interface directory in the [`charmlibs` monorepo](https://github.com/canonical/charmlibs).
* **the owner of the implementation** of an interface. In practice, this often is the team whose charm provides a workload implementing one side of the interface.
* **the interface user**: a charm that wants to use the interface (either as requirer or as provider).

The interface user needs the implementation (typically, the provider also happens to be the owner and so it already has the implementation). Interface libraries are published on PyPI as `charmlibs-interfaces-<interface name>` and can be imported as `charmlibs.interfaces.<interface name>`.

The owner of the implementation needs the specification, to help check that the implementation is in fact compliant.

## Repository structure

For each interface, the [`interfaces` directory in `charmlibs`](https://github.com/canonical/charmlibs/tree/main/interfaces) hosts a per-interface folder (for example, `interfaces/ingress/`), with the per-version specification under `interface/v<N>/`:

- the **specification**: a semi-formal definition of the interface's semantics and what its implementations are expected to do, in terms of both the provider and the requirer (`interface/v<N>/README.md`).
- a list of **reference charms**: the charms that implement this interface, typically the owner of the charm library providing the original implementation (`interface/v<N>/interface.yaml`).
- the **schema**: pydantic models unambiguously defining the accepted unit and application databag contents for provider and requirer (`interface/v<N>/schema.py`).
- the **interface tests**: Python tests that can be run to verify that a charm complies with the interface specification (`interface/v<N>/tests/`).


