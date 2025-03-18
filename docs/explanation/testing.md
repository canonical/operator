(testing)=
# Testing

```{note}

This page is currently being refactored.

```

Charms should have tests to verify that they are functioning correctly. This document describes some of the various types of testing you may want to consider -- their meaning, recommended coverage, and recommended tooling in the context of a charm.

## Unit testing

Charm unit tests isolate and validate individual code units (functions, methods, etc.) by mocking Juju APIs and workloads without external interactions. Unit tests are intended to be isolating and fast to complete. These are the tests you would run every time before committing code changes.

A charm acts like a function, taking event context (always present), configuration, relation data, and stored state as inputs. It then performs operations affecting its workload or other charms: system operations (e.g., file writes), cloud operations (e.g., VM launches), workload operations (often via Pebble for Kubernetes charms), and Juju operations (sharing data with related charms). Unit tests focus on mapping these inputs to expected outputs, such as verifying specific system calls, file content based on configuration, or relation data updates given specific events, configurations, and existing relation data.

Every unit test involves a mocked event context, as charms only execute in response to events. A charm doesn't do anything unless it's being run, and it is only run when an event occurs. So there is _always_ an event context to be mocked, and the starting point of a unit test is typically an event.

### The testing framework

Charm unit testing uses [`ops.testing`](ops_testing) framework for state-transition testing. `State` mocks inputs and outputs, while `Context` and `Container` offer a mock filesystem. Tests involve setup (charm, metadata, context, output mocks, Juju state), event simulation via `Context.run`, output retrieval, and assertions. `Context` and `State` are instantiated before the charm, allowing pre-event state setup (storage, relations, config). `Context` provides methods for simulating various Juju events like `config_changed`, `relation_created`, `relation_joined`, `relation_changed`, `relation_departed`, `storage_attached`, `storage_detached`, `pebble_ready`, and so on.

> See also: {ref}`write-legacy-unit-tests-for-a-charm`, {ref}`write-scenario-tests-for-a-charm`.

### Coverage

Unit testing a charm should cover:

- How relation data is modified as a result of an event.
- What pebble services are running as a result of an event.
- Which configuration files are written and their contents, as a result of an event.

### Tools

Unit testing a charm can be done using:

- [`pytest`](https://pytest.org/) and/or [`unittest`](https://docs.python.org/3/library/unittest.html) and
- [state transition testing](ops_testing), using the `ops` unit testing framework
- [`tox`](https://tox.wiki/en/latest/index.html) can be used to automate and standardize tests.

### Examples

- [https://github.com/canonical/prometheus-k8s-operator/blob/main/tests/unit/test_charm.py](https://github.com/canonical/prometheus-k8s-operator/blob/main/tests/unit/test_charm.py)

(interface-tests)=
## Interface testing

Interface tests validate charm library behavior against mock Juju APIs, ensuring compliance with an interface specification without requiring individual charm code.

Interface specifications, stored in {ref}`charm-relation-interfaces <charm-relation-interfaces>`, are contract definitions that mandate how a charm should behave when integrated with another charm over a registered interface. For information about how to create an interface, see {ref}`register-an-interface`.

> See also: {ref}`write-tests-for-an-interface`.

### Coverage

Interface tests enable Charmhub to validate the relations of a charm and verify that your charm supports the registered interface. For example, if your charm supports an interface called "ingress", interface tests enable Charmhub to verify that your charm supports the [registered `ingress` interface](https://github.com/canonical/charm-relation-interfaces/tree/main/interfaces/ingress/v2).

Interface tests also:
- Enable alternative implementations of an interface to validate themselves against the contractual specification stored in `charm-relation-interfaces`.
- Help verify compliance with multiple versions of an interface.

An interface test has the following pattern: 

1) **Given** - An initial state of the relation over the interface under test.
2) **When** - A specific relation event fires.
3) **Then** - The state of the databags is valid. For example, the state satisfies a [pydantic](https://docs.pydantic.dev/latest/) schema.

In addition to validity of the databag state, we could check for more elaborate conditions.

### Tools

- [`ops.testing`](ops_testing)
- A pytest plugin called [`pytest-interface-tester`](https://github.com/canonical/pytest-interface-tester)

### Examples

A typical interface test looks like:

```python
from interface_tester import Tester

def test_data_published_on_changed_remote_valid():
    """This test verifies that if the remote end has published valid data and we receive a db-relation-changed event, then the schema is satisfied."""
    # GIVEN that we have a relation over "db" and the remote end has published valid data
    relation = Relation(endpoint='db', interface='db',
                        remote_app_data={'model': '"bar"', 'port': '42', 'name': '"remote"', },
                        remote_units_data={0: {'host': '"0.0.0.42"', }})
    t = Tester(State(relations=[relation]))
    # WHEN the charm receives a db-relation-changed event
    state_out = t.run(relation.changed_event)
    # THEN the schema is valid
    t.assert_schema_valid()
```

This enables us to check whether our charm complies with the behavioural specification of the interface, independently from whichever charm is integrated with our charm.

(integration-testing)=
## Integration testing

Integration tests verify the interaction of multiple software components. In the context of a charm, they ensure the charm functions correctly when deployed in a test model in a real controller, checking for "blocked" or "error" states during typical operations. The goal of integration testing is to ensure the charm's operational logic performs as expected under diverse conditions.

Integration tests should be focused on a single charm. Sometimes an integration test requires multiple charms to be deployed for adequate testing, but ideally integration tests should not become end-to-end tests.

Integration tests typically take significantly longer to run than unit tests.

> See also: {ref}`write-integration-tests-for-a-charm`.

### Coverage

* Charm actions
* Charm relations
* Charm configurations
* That the workload is up and running, and responsive
* Upgrade sequence
  * Regression test: upgrade stable/candidate/beta/edge from charmhub with the locally-built charm.

```{caution}

When writing an integration test, it is not sufficient to simply check that Juju reports that running the action was successful; rather, additional checks need to be executed to ensure that whatever the action was intended to achieve worked.

```

### Tools

- [`pytest`](https://pytest.org/) and/or [`unittest`](https://docs.python.org/3/library/unittest.html) and
- [pytest-operator](https://github.com/charmed-kubernetes/pytest-operator) and/or [`zaza`](https://github.com/openstack-charmers/zaza)

Integration tests and unit tests should run using the minor version of Python that is shipped with the OS specified in `charmcraft.yaml` (the `base.run-on` key). For example, if Ubuntu 22.04 is specified in `charmcraft.yaml`, you can use the following tox configuration:

```ini
[testenv]
basepython = python3.10
```

(pytest-operator)=
### `pytest-operator`

`pytest-operator` is a Python library that provides Juju plugins for the generic Python library `pytest` to facilitate the {ref}`integration testing <integration-testing>` of charms.

> See more: [`pytest-operator`](https://github.com/charmed-kubernetes/pytest-operator)

It builds a fixture called `ops_test` that helps you interact with Juju through constructs that wrap around [`python-libjuju` ](https://pypi.org/project/juju/).

> See more: 
> - [`pytest-operator` > `ops_test`](https://github.com/charmed-kubernetes/pytest-operator/blob/main/docs/reference.md#ops_test) 
> - [`pytest` > Fixtures](https://docs.pytest.org/en/6.2.x/fixture.html)

It also provides convenient markers and command line parameters (e.g., the `@pytest.mark.skip_if_deployed` marker in combination with the `--no-deploy` configuration helps you skip, e.g., a deployment test in the case where you already have a deployment).

> See more:
> - [`pytest-operator` > Markers](https://github.com/charmed-kubernetes/pytest-operator/blob/main/docs/reference.md#markers)
> - [`pytest-operator` > Command line parameters](https://github.com/charmed-kubernetes/pytest-operator/blob/main/docs/reference.md#command-line-parameters)

### Examples

- [https://github.com/canonical/prometheus-k8s-operator/blob/main/tests/integration/test_charm.py](https://github.com/canonical/prometheus-k8s-operator/blob/main/tests/integration/test_charm.py)

## Continuous integration

Typically, you want the tests to be run automatically against any PR into your repository's main branch, and potentially trigger a new release whenever the tests succeed. Continuous deployment is out of scope for this page, but we will look at how to set up basic continuous integration.

Create a file called `.github/workflows/ci.yaml`. For example, to include a `lint` job that runs the `tox` `lint` environment:

```yaml
name: Tests
on:
  workflow_call:

jobs:
  lint:
    name: Lint
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v3
      - name: Install dependencies
        run: python3 -m pip install tox
      - name: Run linters
        run: tox -e lint
```

Other `tox` environments can be run similarly. For example, unit tests:

```yaml
  unit-test:
    name: Unit tests
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v3
      - name: Install dependencies
        run: python -m pip install tox
      - name: Run tests
        run: tox -e unit
```

Integration tests are a bit more complex, because these tests require a Juju controller and a cloud in which to deploy it. The following example uses the [`actions-operator`](https://github.com/charmed-kubernetes/actions-operator) workflow provided by `charmed-kubernetes` to set up `microk8s` and Juju:

```yaml
  integration-test-microk8s:
    name: Integration tests (microk8s)
    needs:
      - lint
      - unit-test
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v3
      - name: Setup operator environment
        uses: charmed-kubernetes/actions-operator@main
        with:
          provider: microk8s
      - name: Run integration tests
        # Set a predictable model name so it can be consumed by charm-logdump-action
        run: tox -e integration -- --model testing
      - name: Dump logs
        uses: canonical/charm-logdump-action@main
        if: failure()
        with:
          app: my-app-name
          model: testing
```

For more actions, documentation, and use cases, see [charming-actions](https://github.com/canonical/charming-actions).
