(testing)=
# Testing

Charms should have tests to verify that they are functioning correctly. This page describes the types of testing that you should consider.

## Unit testing

Unit tests isolate and validate individual code units (functions, methods, and so on) by mocking Juju APIs and workloads without external interactions. Unit tests are intended to be isolated and fast to complete. These are the tests you would run before committing any code changes.

Every unit test involves a mocked event context, as charms only execute in response to events. A charm doesn't do anything unless it's being run, and it is only run when an event occurs. So there is _always_ an event context to be mocked, and the starting point of a unit test is typically an event.

A charm acts like a function, taking event context (always present), configuration, relation data, and stored state as inputs. It then performs operations affecting its workload or other charms:

- System operations such as writing files.
- Cloud operations such as launching virtual machines.
- Workload operations, using Pebble in the case of a Kubernetes charm.
- Juju operations such as sharing data with related charms.

Unit tests focus on mapping these inputs to expected outputs. For example, a unit test could verify a system call, the contents of a file, or the contents of a relation databag.

> See also: {ref}`write-unit-tests-for-a-charm`.

### Coverage

Unit testing a charm should cover at least:

- How relation data is modified as a result of an event.
- What pebble services are running as a result of an event.
- Which configuration files are written and their contents, as a result of an event.

### Tools

- [`ops.testing`](ops_testing), the framework for state-transition testing in Ops
- [`pytest`](https://pytest.org/) or [`unittest`](https://docs.python.org/3/library/unittest.html)
- [`tox`](https://tox.wiki/en/latest/index.html) for automating and standardizing tests

The `ops.testing` framework provides `State`, which mocks inputs and outputs. The framework also provides `Context` and `Container`, which offer mock filesystems. Tests involve:

1. Setting up the charm, metadata, context, output mocks, and Juju state.
2. Simulating events using `Context.run`. For example, `config_changed`, `relation_changed`, `storage_attached`, `pebble_ready`, and so on.
3. Retrieving and asserting the output.

`Context` and `State` are instantiated before the charm. This enables you to prepare the state of config, relations, and storage before simulating an event.

### Examples

- [Ubuntu manpages charm unit tests](https://github.com/canonical/ubuntu-manpages-operator/blob/main/tests/unit/test_charm.py)

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

In addition to checking that the databag state is valid, we could check for more elaborate conditions.

### Tools

- [`ops.testing`](ops_testing)
- A pytest plugin called [`pytest-interface-tester`](https://github.com/canonical/pytest-interface-tester)

### Examples

- [Ingress interface tests](https://github.com/canonical/charm-relation-interfaces/blob/main/interfaces/ingress/v2/interface_tests/test_provider.py)

Interface tests enable us to check whether our charm complies with the behavioural specification of the interface, independently from whichever charm is integrated with our charm.

(integration-testing)=
## Integration testing

Integration tests verify the interaction of multiple software components. In the context of a charm, they ensure the charm functions correctly when deployed in a test model in a real controller, checking for "blocked" or "error" states during typical operations. The goal of integration testing is to ensure the charm's operational logic performs as expected under diverse conditions.

Integration tests should be focused on a single charm. Sometimes an integration test requires multiple charms to be deployed for adequate testing, but ideally integration tests should not become end-to-end tests.

Integration tests typically take significantly longer to run than unit tests.

> See also: {ref}`write-integration-tests-for-a-charm`.

### Coverage

* Packing and deploying the charm
* Charm actions
* Charm relations
* Charm configuration
* That the workload is up and running, and responsive
* Upgrade sequence
  * Regression test: upgrade stable/candidate/beta/edge from charmhub with the locally-built charm.

```{caution}

When writing an integration test, it is not sufficient to simply check that Juju reports that running the action was successful; rather, additional checks need to be executed to ensure that whatever the action was intended to achieve worked.

```

### Tools

- [`pytest`](https://pytest.org/) or [`unittest`](https://docs.python.org/3/library/unittest.html) and
- [Jubilant](https://documentation.ubuntu.com/jubilant/)

Integration tests and unit tests should run using the minor version of Python that is shipped with the OS specified in `charmcraft.yaml` (the `base.run-on` key). For example, if Ubuntu 22.04 is specified in `charmcraft.yaml`, you can use the following tox configuration:

```ini
[testenv]
basepython = python3.10
```

### Examples

- [Tempo worker integration tests](https://github.com/canonical/tempo-operators/blob/main/worker/tests/integration/test_deploy.py)

## Continuous integration

Typically, you want the tests to be run automatically against any PR into your repository's main branch, and potentially trigger a new release whenever the tests succeed. Continuous deployment is out of scope for this page, but we will look at how to set up basic continuous integration.

Create a file called `.github/workflows/ci.yaml`. For example, to include a `lint` job that runs the `tox` `unit` environment:

```yaml
name: Tests
on:
  push:
    branches:
      - main
  pull_request:

  unit-test:
    name: Unit tests
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v6
      - name: Set up uv
        uses: astral-sh/setup-uv@7
      - name: Set up tox and tox-uv
        run: uv tool install tox --with tox-uv
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
        uses: actions/checkout@v6
      - name: Setup operator environment
        uses: charmed-kubernetes/actions-operator@main
        with:
          provider: microk8s
          channel: 1.32-strict/stable
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
