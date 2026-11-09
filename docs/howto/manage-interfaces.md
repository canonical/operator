(manage-interfaces)=
# How to manage interfaces

See also: {ref}`charm-relation-interfaces`

## Find an existing interface

Before you create a new interface, check whether one already exists that does what you need. Browse [Interfaces on Charmhub](https://charmhub.io/interfaces), or the {external+charmlibs:doc}`interface specifications <reference/interfaces>` in the Charmlibs documentation. Each interface's page describes the data that the provider and requirer exchange, and lists the charms that implement it.

If an existing interface is close to what you need, consider extending it rather than creating a new one.

(register-an-interface)=
## Register an interface

To register a new interface, add its definition to the `interfaces` directory of the [`charmlibs` monorepo](https://github.com/canonical/charmlibs) and open a pull request. The definition records:

* The specification. This describes what charms on each side of the interface are expected to do.
* The reference charms. These are the charms that implement the interface.
* The schema. This defines the relation data that each side exchanges.

You can register an interface before its library is ready. A directory that contains only the interface definition is enough to start with. Follow the layout of an existing interface in the `interfaces` directory.

To publish the library that implements the interface, run `just init --interface` in your `charmlibs` checkout. For more information, see {external+charmlibs:doc}`how-to/python-package`.

Before you write the schema, read {external+charmlibs:doc}`how-to/design-relation-interfaces`. It explains how to design relation data that can change without breaking charms that are already deployed.

The `charmlibs` maintainers review the pull request. Address their feedback until the pull request is merged.
