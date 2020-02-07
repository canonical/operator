# Charms in detail
## Table of contents

[Best practices](##Best%20practice)

[Charm writing in detail](##Charm%20Writing%20in%20detail)

[New to charms?](##New%20to%20charms?)

[Example Charms](##Example%20Charms)

## Best practices

### Repoository Naming

Naming follows the convention of charm-<charm_name> for example `charm-percona-cluster`.

The rationale behind this is quick and easy searching of the 1000s of github projects along with other reasons.


## Charm Writing in detail

## New to charms?

> Here are some completely reasonable questions to be asking right now

### Why charms?

Charms have a noble goal: take the complication of managing 100s potentially 1000s of configuration files and abstract them as python modules. Thus by abstraction creating a true insfrastructure as code.

But charms are not just limited to setting up configuration, they also handle the installation of charms, and can implement actions thus providing not just configuration, but day zero to day three operations support.

One of the ways that charms achieves this goal is through what are called relations, you can think about this much like the Database relation charts you might have seen in previous roles, or at university, the concept is much the same.

Here's an example from the Juju GUI:

![Openstack relations layout](./diagrams/juju_gui.jpg)

What you are looking at here is a Kubernetes, rendered, using Juju and charms. Each of the circles represents an application, each of the lines represents what we call a relation.

### How do relations work?

Relations between charms at a high level work through what are called interfaces, interfaces are the glue that sticks two or more charms together and allows them to communicate.

#### Some history

In the old framework (reactive) charms were found on github, and used the naming convention of `interface-<interface-name>`. This stays with the new framework.

The major change is the removal of `requires.py` and `provides.py` these are now replaced by a simplied `interface_<interface_name>.py`.

Here's the picture you might have in when you think of charm relations:

![conception of charm relations](./diagrams/conception_of_charm_relations.jpg)

The problem with this conception is what is I want to create a new charm to use somecharm:relation, well then not only do I have to create a new charm, and program the relation into it, I ALSO have to adapt my original charm to work for my new charm. The two components are too closely coupled.

So the charm framework deals with this by decoupling the relations, this is where we move onto the next section.

#### What (tf) are Interfaces?

To decouple the charms from each other and provide abstract, easy to use relations, we have what are called Interfaces.

With the new charm framework we introduce the new interfaces, but continuing with the previous theme, lets see how interfaces **used** to work in the old reactive framework.

![Old interfaces](./diagrams/charm_interfaces_drawing.jpg)

## Charm writing

### Add interface dependences

Operator charms use Interfaces (Provide link?) as dependencies.

These dependencies are pulled in as git submodules, and should be added to the `.gitmodules` file, an example file looks like this:

```

[submodule "mod/operator"]
	path = mod/operator
	url = https://github.com/canonical/operator
[submodule "mod/interface-mysql"]
	path = mod/interface-mysql
	url = git@github.com:johnsca/interface-mysql.git
[submodule "mod/interface-http"]
	path = mod/interface-http
	url = git@github.com:johnsca/interface-http.git
[submodule "mod/resource-oci-image"]
	path = mod/resource-oci-image
	url = git@github.com:johnsca/resource-oci-image.git
```

You can then pull in those dependencies with the following commands:

```
git submodule init
git submodule update
```

These commands will pull in the dependencies to mod, although we will be referencing from the `lib` directory. To fix this you will need to create symbolic references.

```
ln -s ./mod/interface-mysql/interface_mysql.py ./lib/interface_mysql.py
```

For all of the required submodules.

### The charm `__init__` method

The charm __init__ method has the following signature:

```
def __init__(self, framework, key)
             ^^^^  ^^^^^^^^^  ^^^
             ||||  |||||||||  ||||

 1. Obvious! |||||||||  ||||
 2.      A reference to the framework
                              ||||
 3.                          (todo)

```

this is followed by a call to super, looking like this:

```
    def __init__(self, framework, key):
        super.__init__(framework, key)
```

We can then follow up the rest of the method with calls to set our state and our required interfaces for example:

```
        self.state.set_defaults(is_started=False)
        self.mysql = MySQLClient(self, 'mysql')
```

### The charm model

This is the central place to get all relevant charm information so that you can configure your charm.

The charm model has the following properties:

- unit
- app
- relations - A relation mapping
- config - The charm configuration
- resources
- pod - the Kubernetes pod
- storages - The charm storage (A PVC?)

Charm metadata is retrieved from the meta framework attribute:

```
meta = self.framework.meta
```

The same can be done for the charm configuration data too:

```
config = self.framework.config
```

The charm operator framework is imported by adding the framework in the 'lib' diretory and as a submodule:

```
git submodule add https://github.com/canonical/operator mod/operator
ln -s ../mod/operator/ops lib/ops
```

This system path change must be applied before any framework features can be utilised.

```
sys.path.append('lib')
```

## Migrating from the old (reactive) framework




# Useful links

[Writing Kubernetes Charms](https://discourse.jujucharms.com/t/writing-a-kubernetes-charm/159)

## Example Charms

[Gitlab charm](https://github.com/johnsca/charm-gitlab-k8s)

[Cockroachdb (Example Charm)](https://github.com/dshcherb/charm-cockroachdb)

[Charm Kine](https://github.com/tvansteenburgh/charm-kine)

[Test Charm (From the Operator Framework)](https://github.com/canonical/operator/tree/master/test/charms/test_main)

[MSSQL Charm](https://github.com/camille-rodriguez/mssql)