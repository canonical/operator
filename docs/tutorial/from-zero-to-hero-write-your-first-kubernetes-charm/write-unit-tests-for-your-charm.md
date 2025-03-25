(write-unit-tests-for-your-charm)=
# Write unit tests for your charm

> <small> {ref}`From Zero to Hero: Write your first Kubernetes charm <from-zero-to-hero-write-your-first-kubernetes-charm>` > Write unit tests for your charm</small>
> 
> **See previous: {ref}`Observe your charm with COS Lite <observe-your-charm-with-cos-lite>`**

````{important}

This document is part of a series, and we recommend you follow it in sequence. However, you can also jump straight in by checking out the code from the previous branches:

```text
git clone https://github.com/canonical/juju-sdk-tutorial-k8s.git
cd juju-sdk-tutorial-k8s
git checkout 05_cos_integration
git checkout -b 06_unit_testing
```

````

When you're writing a charm, you will want to ensure that it will behave reliably as intended.

For example, that the various components -- relation data, Pebble services, or configuration files -- all behave as expected in response to an event.

You can ensure all this by writing a rich battery of unit tests. In the context of a charm we recommended using [`pytest`](https://pytest.org/) (but [`unittest`](https://docs.python.org/3/library/unittest.html) can also be used) and especially the operator framework's built-in testing library --  [](ops_testing_harness). We will be using the Python testing tool [`tox`](https://tox.wiki/en/4.14.2/index.html) to automate our testing and set up our testing environment.

<!-- TODO

This chapter and the next should be removed and the content spread throughout
each of the previous chapters. Each time a feature is added, a unit and
integration test should also be added. At the end of each chapter, before
manually checking the feature works, the user should run the tests to make sure
that they pass.

-->

In this chapter you will write a scenario test to check that the `get_db_info` action that you defined in an earlier chapter behaves as expected.

## Prepare your test environment

Create a file called `tox.ini` in your charm project's root directory and add the following to configure your test environment:

```
[tox]
no_package = True
skip_missing_interpreters = True
min_version = 4.0.0
env_list = unit

[vars]
src_path = {tox_root}/src
tests_path = {tox_root}/tests

[testenv]
set_env =
    PYTHONPATH = {tox_root}/lib:{[vars]src_path}
    PYTHONBREAKPOINT=pdb.set_trace
    PY_COLORS=1
pass_env =
    PYTHONPATH
    CHARM_BUILD_DIR
    MODEL_SETTINGS

[testenv:unit]
description = Run unit tests
deps =
    pytest
    cosl
    coverage[toml]
    ops[testing]
    -r {tox_root}/requirements.txt
commands =
    coverage run --source={[vars]src_path} \
                 -m pytest \
                 --tb native \
                 -v \
                 -s \
                 {posargs} \
                 {[vars]tests_path}/unit
    coverage report
```
> Read more: [`tox.ini`](https://tox.wiki/en/latest/config.html#tox-ini)

## Prepare your test directory

In your project root, create a `tests/unit` directory:

```text
mkdir -p tests/unit
```

## Write your test

In your `tests/unit` directory, create a new file `test_charm.py` and add the test below. This test will check the behaviour of the `get_db_info` action that you set up in a previous chapter. It will first set up the test context by setting the appropriate metadata, then define the input state, then run the action and, finally, check if the results match the expected values.

```python
from unittest.mock import Mock
from pytest import MonkeyPatch

from ops import testing

from charm import FastAPIDemoCharm


def test_get_db_info_action(monkeypatch: MonkeyPatch):
    monkeypatch.setattr('charm.LogProxyConsumer', Mock())
    monkeypatch.setattr('charm.MetricsEndpointProvider', Mock())
    monkeypatch.setattr('charm.GrafanaDashboardProvider', Mock())

    # Use testing.Context to declare what charm we are testing.
    # Note that the test framework will automatically pick up the metadata from
    # your charmcraft.yaml file, so you typically could just do
    # `ctx = testing.Context(FastAPIDemoCharm)` here, but the full
    # version is included here as an example.
    ctx = testing.Context(
        FastAPIDemoCharm,
        meta={
            'name': 'demo-api-charm',
            'containers': {'demo-server': {}},
            'peers': {'fastapi-peer': {'interface': 'fastapi_demo_peers'}},
            'requires': {
                'database': {
                    'interface': 'postgresql_client',
                }
            },
        },
        config={
            'options': {
                'server-port': {
                    'default': 8000,
                }
            }
        },
        actions={
            'get-db-info': {'params': {'show-password': {'default': False, 'type': 'boolean'}}}
        },
    )

    # Declare the input state.
    state_in = testing.State(
        leader=True,
        relations={
            testing.Relation(
                endpoint='database',
                interface='postgresql_client',
                remote_app_name='postgresql-k8s',
                local_unit_data={},
                remote_app_data={
                    'endpoints': '127.0.0.1:5432',
                    'username': 'foo',
                    'password': 'bar',
                },
            ),
        },
        containers={
            testing.Container('demo-server', can_connect=True),
        },
    )

    # Run the action with the defined state and collect the output.
    ctx.run(ctx.on.action('get-db-info', params={'show-password': True}), state_in)

    assert ctx.action_results == {
        'db-host': '127.0.0.1',
        'db-port': '5432',
        'db-username': 'foo',
        'db-password': 'bar',
    }
```

> Read more: [](ops_testing_harness)

## Run the test

In your Multipass Ubuntu VM shell, run your test as below:

```text
ubuntu@charm-dev:~/fastapi-demo$ tox -e unit     
```

You should get an output similar to the one below:

```text                                             
unit: commands[0]> coverage run --source=/home/ubuntu/fastapi-demo/src -m pytest --tb native -v -s /home/ubuntu/fastapi-demo/tests/unit
======================================= test session starts ========================================
platform linux -- Python 3.11.9, pytest-8.3.3, pluggy-1.5.0 -- /home/ubuntu/fastapi-demo/.tox/unit/bin/python
cachedir: .tox/unit/.pytest_cache
rootdir: /home/ubuntu/fastapi-demo
plugins: anyio-4.6.0
collected 1 item                                                                                   

tests/unit/test_charm.py::test_get_db_info_action PASSED

======================================== 1 passed in 0.19s =========================================
unit: commands[1]> coverage report
Name           Stmts   Miss  Cover
----------------------------------
src/charm.py     129     57    56%
----------------------------------
TOTAL            129     57    56%
  unit: OK (6.89=setup[6.39]+cmd[0.44,0.06] seconds)
  congratulations :) (6.94 seconds)
```

Congratulations, you have written your first unit test!

```{caution}

As you can see in the output, the current tests cover 56% of the charm code. In a real-life scenario make sure to cover much more!
```

## Review the final code

For the full code see: [06_unit_testing](https://github.com/canonical/juju-sdk-tutorial-k8s/tree/06_unit_testing)

For a comparative view of the code before and after this doc see: [Comparison](https://github.com/canonical/juju-sdk-tutorial-k8s/compare/05_cos_integration...06_unit_testing)

> **See next: {ref}`Write integration tests for your charm <write-integration-tests-for-your-charm>`**
