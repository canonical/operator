(manage-interfaces)=
# How to manage interfaces

(register-an-interface)=
## Register an interface


Suppose you have determined that you need to create a new relation interface called `my_fancy_database`.

Suppose that your interface specification has the following data model:
- the requirer app is supposed to forward a list of tables that it wants to be provisioned by the database provider
- the provider app (the database) at that point will reply with an API endpoint and, for each replica, it will provide a separate secret ID to authenticate the requests

These are the steps you need to take in order to register it in the [`charmlibs` monorepo](#charm-relation-interfaces).

### 1. Clone (a fork of) [the `charmlibs` repo](https://github.com/canonical/charmlibs) and create an interface package

```bash
git clone https://github.com/canonical/charmlibs
cd /path/to/charmlibs
```

### 2. Scaffold the interface

From the repository root, run `just init --interface` and answer the prompts. The project name should be the canonical interface name, as it appears in `charmcraft.yaml` files -- for example `my_fancy_database`. You'll also be asked for the minimum Python version and the PyPI author field; press enter to accept the defaults shown in brackets.

```bash
just init --interface
```

This creates a new package under `interfaces/<your_interface>/`.

At this point you should see a directory structure similar to:

```
# tree ./interfaces/my_fancy_database
./interfaces/my_fancy_database
├── interface
│   └── v0
│       ├── README.md
│       ├── interface.yaml
│       ├── schema.py
│       └── tests
└── ruff.toml
```

(The package also includes packaging files such as `pyproject.toml`, `CHANGELOG.md`, and a `src/` tree for the library implementation; those are not relevant to registering the interface specification itself.)

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

To verify that the schema is valid, run it the same way `charmlibs` CI does, from the `charmlibs` root:

```bash
uv run --no-project --with-requirements schema-requirements.txt \
  interfaces/my_fancy_database/interface/v0/schema.py
```

The command exits successfully if the module imports and the pydantic models are well formed. If it fails, there is something wrong with the models.

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

### 6. Add interface tests

See more: {ref}`write-tests-for-an-interface`

### 7. Open a PR to [the `charmlibs` repo](https://github.com/canonical/charmlibs)

Finally, open a pull request to the `charmlibs` repo and drive it to completion, addressing any feedback or concerns that the maintainers may have.

## Example

For an example of a registered interface, see [`ingress`](https://github.com/canonical/charmlibs/tree/main/interfaces/ingress/interface/v1):
   - As you can see from the [`interface.yaml`](https://github.com/canonical/charmlibs/blob/main/interfaces/ingress/interface/v1/interface.yaml) file, the [`canonical/traefik-k8s-operator` charm](https://github.com/canonical/traefik-k8s-operator) plays the provider role in the interface.
   - The schema of this interface is defined in [`schema.py`](https://github.com/canonical/charmlibs/blob/main/interfaces/ingress/interface/v1/schema.py).
   - You can find out more information about this interface in the [README](https://github.com/canonical/charmlibs/blob/main/interfaces/ingress/interface/v1/README.md).

(write-tests-for-an-interface)=
## Write tests for an interface

See also: {ref}`interface-tests`

Suppose you have an interface specification in the [`charmlibs` monorepo](#charm-relation-interfaces), or you are working on one, and you want to add interface tests. These are the steps you need to take.

We will continue from the running example from {ref}`register-an-interface`. Your starting setup should look like this:

```text
$ tree ./interfaces/my_fancy_database/interface
./interfaces/my_fancy_database/interface
└── v0
    ├── interface.yaml
    ├── README.md
    ├── schema.py
    └── tests

2 directories, 3 files
```


### Create the test module

Add a file to the `tests` directory called `test_provider.py`.

```bash
touch ./interfaces/my_fancy_database/interface/v0/tests/test_provider.py
```

### Write a test for the 'negative' path

Write to `test_provider.py` the code below:

```python
from interface_tester import Tester
from scenario import State, Relation


def test_nothing_happens_if_remote_empty():
    # GIVEN that the remote end has not published any tables
    t = Tester(
        State(
            leader=True,
            relations={
                Relation(
                    endpoint='my-fancy-database',  # the name doesn't matter
                    interface='my_fancy_database',
                )
            },
        )
    )
    # WHEN the database charm receives a relation-joined event
    state_out = t.run('my-fancy-database-relation-joined')
    # THEN no data is published to the (local) databags
    t.assert_relation_data_empty()
```

This test verifies part of a 'negative' path: it verifies that if the remote end did not (yet) comply with its part of the contract, then our side did not either.

### Write a test for the 'positive' path

Append to `test_provider.py` the code below:

```python
import json

from interface_tester import Tester
from scenario import State, Relation


def test_contract_happy_path():
    # GIVEN that the remote end has requested tables in the right format
    tables_json = json.dumps(['users', 'passwords'])
    t = Tester(
        State(
            leader=True,
            relations=[
                Relation(
                    endpoint='my-fancy-database',  # the name doesn't matter
                    interface='my_fancy_database',
                    remote_app_data={'tables': tables_json},
                )
            ],
        )
    )
    # WHEN the database charm receives a relation-changed event
    state_out = t.run('my-fancy-database-relation-changed')
    # THEN the schema is satisfied (the database charm published all required fields)
    t.assert_schema_valid()
```

This test verifies that the databags of the 'my-fancy-database' relation are valid according to the pydantic schema you have specified in `schema.py`.

These tests are collected and run from the charm side, so the way to check that they work is to run them against a charm that implements the interface, as described in {ref}`prepare-the-charm`.

Similarly, you can add tests for requirer in `./interfaces/my_fancy_database/interface/v0/tests/test_requirer.py`. Don't forget to [edit the `interface.yaml`](#edit-interface-yaml) file in the "requirers" section to add the name of the charm and the URL.

### Merge in `charmlibs`

You are ready to merge these files in the `charmlibs` repository. Open a PR and drive it to completion.

(prepare-the-charm)=
#### Prepare the charm

In order to be testable from `charmlibs`, the charm needs to expose and configure a fixture.

```{note}

This is because the `fancy-database` interface specification is only supported if the charm is well-configured and has leadership, since it will need to publish data to the application databag.
Also, interface tests are Scenario tests and as such they are mock-based: there is no cloud substrate running, no Juju, no real charm unit in the background. So you need to patch out all calls that cannot be mocked by Scenario, as well as provide enough mocks through State so that the charm is 'ready' to support the interface you are testing.

```

Go to the Fancy Database charm repository root.

```text
cd path/to/my-fancy-database-operator
```

Install the interface tester:

```shell
pip install pytest-interface-tester
```

Create a `conftest.py` file under `tests/interface`:

```shell
mkdir ./tests/interface
touch ./tests/interface/conftest.py
```

Write in `conftest.py`:

```python
import pytest
from charm import MyFancyDatabaseCharm
from interface_tester import InterfaceTester
from scenario.state import State


@pytest.fixture
def interface_tester(interface_tester: InterfaceTester):
    interface_tester.configure(
        charm_type=MyFancyDatabaseCharm,
        # `pytest-interface-tester` still defaults to the archived
        # `charm-relation-interfaces` repo and its layout, so point it at `charmlibs`.
        repo='https://github.com/canonical/charmlibs',
        base_path='interfaces',
        interface_subdir='interface',
        tests_dir='tests',
        state_template=State(
            leader=True,  # we need leadership
        ),
    )
    # this fixture needs to yield (NOT RETURN!) interface_tester again
    yield interface_tester
```

```{note}

This fixture overrides a homonym pytest fixture that comes with `pytest-interface-tester`.

```


````{note}

You can configure the fixture name, as well as its location, but that needs to happen in the `charmlibs` repo. Example:
```
providers:
  - name: my-fancy-database-provider
    url: YOUR_REPO_URL
    test_setup:
      location: tests/interface/conftest.py
      identifier: database_tester
```

````


#### Verifying the `interface_tester` configuration

To verify that the fixture is good enough to pass the interface tests, run them from the charm repository. Add a test that drives the fixture:

```python
# ./tests/interface/test_interfaces.py
from interface_tester import InterfaceTester


def test_my_fancy_database_interface(interface_tester: InterfaceTester):
    interface_tester.configure(
        interface_name='my_fancy_database',
        interface_version=0,
    )
    interface_tester.run()
```

Then run it:

```bash
cd path/to/my-fancy-database-operator
pytest ./tests/interface
```

The tester clones `charmlibs` and collects the tests and schema for the interface, so unless you have already merged your interface tests, point it at your own branch by adding `branch='my-fancy-database'` to the `configure()` call in `conftest.py`.

### Troubleshooting and debugging the tests

#### Your charm is missing some configuration or mocks

Solution to this is to add the missing mocks/patches to the `interface_tester` fixture in `conftest.py`.
Essentially, you need to make it so that the charm runtime 'thinks' that everything is normal and ready to process and accept the interface you are testing.
This may mean mocking the presence and connectivity of a container, system calls, substrate API calls, and more.
If you have unit tests in your codebase, you most likely already have all the necessary patches scattered around and it's a matter of collecting them.

Remember that if you run the tests locally, in your troubleshooting you need to point `interface.yaml` to the branch where you committed your changes, because the test runner clones the charm repositories in order to run the charms:

```text
requirers:
  - name: my-fancy-database-operator
    url: https://my-fancy-database-operator-repo
    branch: branch-with-my-conftest-changes
```
Remember, however, to merge the changes first in the operator repository before merging the pull request to `charmlibs`.

See more:

- [`test_provider.py`](https://github.com/canonical/charmlibs/blob/main/interfaces/ingress/interface/v1/tests/test_provider.py) for the `ingress` interface defined in the `charmlibs` monorepo.
- [`conftest.py`](https://github.com/canonical/traefik-k8s-operator/blob/main/tests/interface/conftest.py) for the [`traefik-k8s-operator`](https://github.com/canonical/traefik-k8s-operator) charm.
