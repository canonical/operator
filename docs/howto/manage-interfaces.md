(manage-interfaces)=
# How to manage interfaces

(register-an-interface)=
## Register an interface


Suppose you have determined that you need to create a new relation interface called `my_fancy_database`.

Suppose that your interface specification has the following data model:
- the requirer app is supposed to forward a list of tables that it wants to be provisioned by the database provider
- the provider app (the database) at that point will reply with an API endpoint and, for each replica, it will provide a separate secret ID to authenticate the requests

These are the steps you need to take in order to register it in the [`charmlibs` monorepo](#charm-relation-interfaces).

### 1. Clone (a fork of) [the `charmlibs` repo](https://github.com/canonical/charmlibs)

```bash
git clone https://github.com/canonical/charmlibs
cd /path/to/charmlibs
```

### 2. Create the interface directory

Registering an interface means adding its definition to `charmlibs`; you don't need to publish a Python package to do that. Create a directory for the interface under `interfaces/`, named with the canonical interface name as it appears in `charmcraft.yaml` files -- for example `my_fancy_database` -- and add the three files that make up the definition:

```bash
mkdir -p ./interfaces/my_fancy_database
touch ./interfaces/my_fancy_database/{README.md,interface.yaml,schema.py}
```

```{note}

If you also want to ship a charm library implementing the interface, run `just init --interface` from the repository root instead, and answer the prompts. That scaffolds a full `charmlibs.interfaces.<name>` package, which is published to PyPI. See the [`charmlibs` documentation](https://canonical.com/juju/docs/charmlibs/) for how to develop and release one.
```

(edit-interface-yaml)=
### 3. Edit `interface.yaml`

Add to `interface.yaml` the charm that owns the reference implementation of the `my_fancy_database` interface. Assuming your `my_fancy_database_charm` plays the `provider` role in the interface, your `interface.yaml` will look like this:

```yaml
# interface.yaml
providers:
  - name: my-fancy-database-operator  # same as metadata.yaml's .name
    url: https://github.com/your-github-slug/my-fancy-database-operator
```

### 4. Edit `schema.py`

Edit `schema.py` to contain:

```python
# schema.py

from interface_tester.schema_base import DataBagSchema
from pydantic import BaseModel, AnyHttpUrl, Field, Json
import typing


class ProviderUnitData(BaseModel):
    secret_id: str = Field(
        description='Secret ID for the key you need in order to query this unit.',
        title='Query key secret ID',
        examples=['secret:12312323112313123213'],
    )


class ProviderAppData(BaseModel):
    api_endpoint: AnyHttpUrl = Field(
        description="URL to the database's endpoint.",
        title='Endpoint API address',
        examples=['https://example.com/v1/query'],
    )


class ProviderSchema(DataBagSchema):
    app: ProviderAppData
    unit: ProviderUnitData


class RequirerAppData(BaseModel):
    tables: Json[typing.List[str]] = Field(
        description='Tables that the requirer application needs.',
        title='Requested tables.',
        examples=[['users', 'passwords']],
    )


class RequirerSchema(DataBagSchema):
    app: RequirerAppData
    # we can omit `unit` because the requirer makes no use of the unit databags
```

`DataBagSchema` currently comes from `pytest-interface-tester`; `charmlibs` intends to replace it, so check the schemas of existing interfaces for the current base class before you write yours.

### 5. Edit `README.md`

Edit the `README.md` file to contain:

```markdown
# `my_fancy_database`

## Overview
This relation interface describes the expected behavior between of any charm claiming to be able to interface with a Fancy Database and the Fancy Database itself.
Other Fancy Database-compatible providers can be used interchangeably as well.

## Usage

Typically, you can use the implementation of this interface from [this charm library](https://github.com/your_org/my_fancy_database_operator/blob/main/lib/charms/my_fancy_database/v0/fancy.py), although charm developers are free to provide alternative libraries as long as they comply with this interface specification.

## Direction
The `my_fancy_database` interface implements a provider/requirer pattern.
The requirer is a charm that wishes to act as a Fancy Database Service consumer, and the provider is a charm exposing a Fancy Database (-compatible API).

/```mermaid
flowchart TD
    Requirer -- tables --> Provider
    Provider -- endpoint, access_keys --> Requirer
/```

## Behavior

The requirer and the provider must adhere to a certain set of criteria to be considered compatible with the interface.

### Requirer

- Is expected to publish a list of tables in the application databag


### Provide

- Is expected to publish an endpoint URL in the application databag
- Is expected to create and grant a Juju Secret containing the access key for each shard and publish its secret ID in the unit databags.

## Relation Data

See the {ref}`\[Pydantic Schema\] <12689md>`


### Requirer

The requirer publishes a list of tables to be created, as a json-encoded list of strings.

#### Example
\```yaml
application_data: {
   "tables": "{ref}`'users', 'passwords']"
}
\```

### Provider

The provider publishes an endpoint url and access keys for each shard.

#### Example
\```
application_data: {
   "api_endpoint": "https://foo.com/query"
},
units_data : {
  "my_fancy_unit/0": {
     "secret_id": "secret:12312321321312312332312323"
  },
  "my_fancy_unit/1": {
     "secret_id": "secret:45646545645645645646545456"
  }
}
\```
```

### 6. Open a PR to [the `charmlibs` repo](https://github.com/canonical/charmlibs)

Finally, open a pull request to the `charmlibs` repo and drive it to completion, addressing any feedback or concerns that the maintainers may have.

## Example

For an example of a registered interface, see [`ingress`](https://github.com/canonical/charmlibs/tree/main/interfaces/ingress):
   - As you can see from its `interface.yaml` file, the [`canonical/traefik-k8s-operator` charm](https://github.com/canonical/traefik-k8s-operator) plays the provider role in the interface.
   - The schema of this interface is defined in `schema.py`.
   - You can find out more information about this interface in its `README.md`.
