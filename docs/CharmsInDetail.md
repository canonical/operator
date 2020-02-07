# Charms in detail
## Table of contents

[Best practices](##Best%20practice)

[Charm writing in detail](Charm%20Writing%20in%20detail)

[Example Charms](##Example%20Charms)

## Best practices

### Repoository Naming

Naming follows the convention of charm-<charm_name> for example `charm-percona-cluster`.

The rationale behind this is quick and easy searching of the 1000s of github projects along with other reasons.


## Charm Writing in detail

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

### The charm __init__ method

The charm __init__ method has the following signature:

```
def __init__(self, framework, key)
         ^^^^  ^^^^^^^^^  ^^^
         ||||  |||||||||  ||||

   1. Obvious! |||||||||  ||||
   2.      A reference to the framework
                          ||||
   3.                    wtf is this? (todo)

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


## New to charms?

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