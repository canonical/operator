(testing)=
# Testing

Charms should have tests to verify that they are functioning correctly. This document describes some of the various types of testing you may want to consider -- their meaning, recommended coverage, and recommended tooling in the context of a charm.

<!--
These tests should cover the behaviour of the charm both in isolation (unit tests) and when used with other charms (integration tests). Charm authors should use [tox](https://tox.wiki/en/latest/index.html) to run these automated tests.

The unit and integration tests should be run on the same minor Python version as is shipped with the OS as configured under the charmcraft.yaml bases.run-on key. With tox, for Ubuntu 22.04, this can be done using:

{ref}`testenv]

basepython = python3.10
-->


## Unit testing

> See also: {ref}`write-unit-tests-for-a-charm`, {ref}`write-scenario-tests-for-a-charm`

A **unit test** is a test that targets an individual unit of code (function, method, class, etc.) independently. In the context of a charm, it refers to testing charm code against mock Juju APIs and mocked-out workloads as a way to validate isolated behaviour without external interactions.

Unit tests are intended to be isolating and fast to complete. These are the tests you would run every time before committing code changes.

**Coverage.** Unit testing a charm should cover:

- how relation data is modified as a result of an event
- what pebble services are running as a result of an event
- which configuration files are written and their contents, as a result of an event

**Tools.** Unit testing a charm can be done using:

- [`pytest`](https://pytest.org/) and/or [`unittest`](https://docs.python.org/3/library/unittest.html) and
- [state transition testing](https://ops.readthedocs.io/en/latest/reference/ops-testing.html), using the `ops` unit testing framework

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
* Charm integrations
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


