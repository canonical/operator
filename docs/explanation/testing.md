(testing)=
# Testing

```{note}

This page is currently being refactored.

```

Charms should have tests to verify that they are functioning correctly. This document describes some of the various types of testing you may want to consider -- their meaning, recommended coverage, and recommended tooling in the context of a charm.

<!--
These tests should cover the behaviour of the charm both in isolation (unit tests) and when used with other charms (integration tests). Charm authors should use [tox](https://tox.wiki/en/latest/index.html) to run these automated tests.

The unit and integration tests should be run on the same minor Python version as is shipped with the OS as configured under the charmcraft.yaml bases.run-on key. With tox, for Ubuntu 22.04, this can be done using:

{ref}`testenv]

basepython = python3.10
-->


## Unit testing

> See also: {ref}`write-legacy-unit-tests-for-a-charm`, {ref}`write-scenario-tests-for-a-charm`

A **unit test** is a test that targets an individual unit of code (function, method, class, etc.) independently. In the context of a charm, it refers to testing charm code against mock Juju APIs and mocked-out workloads as a way to validate isolated behaviour without external interactions.

Unit tests are intended to be isolating and fast to complete. These are the tests you would run every time before committing code changes.

**Coverage.** Unit testing a charm should cover:

- how relation data is modified as a result of an event
- what pebble services are running as a result of an event
- which configuration files are written and their contents, as a result of an event

**Tools.** Unit testing a charm can be done using:

- [`pytest`](https://pytest.org/) and/or [`unittest`](https://docs.python.org/3/library/unittest.html) and
- [state transition testing](ops_testing), using the `ops` unit testing framework

**Examples.**

- [https://github.com/canonical/prometheus-k8s-operator/blob/main/tests/unit/test_charm.py](https://github.com/canonical/prometheus-k8s-operator/blob/main/tests/unit/test_charm.py)

## Interface testing

In the context of a charm, interface tests help validate charm library behavior without individual charm code against mock Juju APIs. 

> See more: {ref}`interface-tests`



(integration-testing)=
## Integration testing
> See also: {ref}`write-integration-tests-for-a-charm`

An **integration test** is a test that targets multiple software components in interaction. In the context of a charm, it checks that the charm operates as expected when Juju-deployed by a user in a test model in a real controller.

Integration tests should be focused on a single charm. Sometimes an integration test requires multiple charms to be deployed for adequate testing, but ideally integration tests should not become end-to-end tests.

Integration tests typically take significantly longer to run than unit tests.

**Coverage.**

* Charm actions
* Charm relations
* Charm configurations
* That the workload is up and running, and responsive
* Upgrade sequence
  * Regression test: upgrade stable/candidate/beta/edge from charmhub with the locally-built charm.


```{caution}

When writing an integration test, it is not sufficient to simply check that Juju reports that running the action was successful; rather, additional checks need to be executed to ensure that whatever the action was intended to achieve worked.

```

**Tools.**

- [`pytest`](https://pytest.org/) and/or [`unittest`](https://docs.python.org/3/library/unittest.html) and
- [pytest-operator](https://github.com/charmed-kubernetes/pytest-operator) and/or [`zaza`](https://github.com/openstack-charmers/zaza)


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



**Examples.**

- [https://github.com/canonical/prometheus-k8s-operator/blob/main/tests/integration/test_charm.py](https://github.com/canonical/prometheus-k8s-operator/blob/main/tests/integration/test_charm.py)

---

(interface-tests)=
## Interface tests
> See also: {ref}`manage-interfaces`

Interface tests are tests that verify the compliance of a charm with an interface specification.
Interface specifications, stored in {ref}`charm-relation-interfaces <charm-relation-interfaces>`, are contract definitions that mandate how a charm should behave when integrated with another charm over a registered interface.

Interface tests will allow `charmhub` to validate the relations of a charm and verify that your charm indeed supports "the" `ingress` interface and not just an interface called "ingress", which happens to be the same name as "the official `ingress` interface v2" as registered in charm-relation-interfaces (see [here](https://github.com/canonical/charm-relation-interfaces/tree/main/interfaces/ingress/v2)).

Also, they allow alternative implementations of an interface to validate themselves against the contractual specification stored in charm-relation-interfaces, and they help verify compliance with multiple versions of an interface.

An interface test is a contract test powered by [`ops.testing`](ops_testing) and a pytest plugin called [`pytest-interface-tester`](https://github.com/canonical/pytest-interface-tester). An interface test has the following pattern: 
1) **GIVEN** an initial state of the relation over the interface under test
2) **WHEN** a specific relation event fires
3) **THEN** the state of the databags is valid (e.g. it satisfies an expected pydantic schema)

On top of databag state validity, one can check for more elaborate conditions.

A typical interface test will look like:

```python
from interface_tester import Tester

def test_data_published_on_changed_remote_valid():
    """This test verifies that if the remote end has published  valid data and we receive a db-relation-changed event, then the schema is satisfied."""
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

This allows us to, independently from what charm we are testing, determine if the behavioural specification of this interface is complied with.
