(write-scenario-tests-for-your-charm)=
# Write scenario tests for your charm

> <small> {ref}`From Zero to Hero: Write your first Kubernetes charm <from-zero-to-hero-write-your-first-kubernetes-charm>` > Write scenario tests for your charm</small>
> 
> **See previous: {ref}`Write unit tests for your charm <write-unit-tests-for-your-charm>`**

````{important}

This document is part of a series, and we recommend you follow it in sequence. However, you can also jump straight in by checking out the code from the previous branches:

```
git clone https://github.com/canonical/juju-sdk-tutorial-k8s.git
cd juju-sdk-tutorial-k8s
git checkout 08_unit_testing
git checkout -b 09_scenario_testing
```

````

In the previous chapter we checked the basic functionality of our charm by writing unit tests.

However, there is one more type of test to cover, namely: state transition tests. 

In the charming world the current recommendation is to write state transition tests with the 'scenario' model popularised by the {ref}``ops-scenario` <scenario>` library.

```{note}
 Scenario is a state-transition testing SDK for operator framework charms. 
```

In this chapter you will write a scenario test to check that the `get_db_info` action that you defined in an earlier chapter behaves as expected.


## Prepare your test environment

Install `ops-scenario`:

```bash
pip install ops-scenario
```
In your project root's existing `tox.ini` file, add the following:

```
...

[testenv:scenario]
description = Run scenario tests
deps =
    pytest
    cosl
    ops-scenario ~= 7.0
    coverage[toml]
    -r {tox_root}/requirements.txt
commands =
    coverage run --source={[vars]src_path} \
                 -m pytest \
                 --tb native \
                 -v \
                 -s \
                 {posargs} \
                 {[vars]tests_path}/scenario
    coverage report
```

And adjust the `env_list` so that the Scenario tests will run with a plain `tox` command:

```
env_list = unit, scenario
```

## Prepare your test directory

By convention, scenario tests are kept in a separate directory, `tests/scenario`. Create it as below:

```
mkdir -p tests/scenario
cd tests/scenario
```


## Write your scenario test

In your `tests/scenario` directory, create a new file `test_charm.py` and add the test below. This test will check the behaviour of the `get_db_info` action that you set up in a previous chapter. It will first set up the test context by setting the appropriate metadata, then define the input state, then run the action and, finally, check if the results match the expected values.

```python
from unittest.mock import Mock

import scenario
from pytest import MonkeyPatch

from charm import FastAPIDemoCharm


def test_get_db_info_action(monkeypatch: MonkeyPatch):
    monkeypatch.setattr('charm.LogProxyConsumer', Mock())
    monkeypatch.setattr('charm.MetricsEndpointProvider', Mock())
    monkeypatch.setattr('charm.GrafanaDashboardProvider', Mock())

    # Use scenario.Context to declare what charm we are testing.
    # Note that Scenario will automatically pick up the metadata from
    # your charmcraft.yaml file, so you typically could just do
    # `ctx = scenario.Context(FastAPIDemoCharm)` here, but the full
    # version is included here as an example.
    ctx = scenario.Context(
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
    state_in = scenario.State(
        leader=True,
        relations={
            scenario.Relation(
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
            scenario.Container('demo-server', can_connect=True),
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


## Run the test

In your Multipass Ubuntu VM shell, run your scenario test as below:

```bash
ubuntu@charm-dev:~/juju-sdk-tutorial-k8s$ tox -e scenario     
```

You should get an output similar to the one below:

```bash                                             
scenario: commands[0]> coverage run --source=/home/tameyer/code/juju-sdk-tutorial-k8s/src -m pytest --tb native -v -s /home/tameyer/code/juju-sdk-tutorial-k8s/tests/scenario
======================================= test session starts ========================================
platform linux -- Python 3.11.9, pytest-8.3.3, pluggy-1.5.0 -- /home/tameyer/code/juju-sdk-tutorial-k8s/.tox/scenario/bin/python
cachedir: .tox/scenario/.pytest_cache
rootdir: /home/tameyer/code/juju-sdk-tutorial-k8s
plugins: anyio-4.6.0
collected 1 item                                                                                   

tests/scenario/test_charm.py::test_get_db_info_action PASSED

======================================== 1 passed in 0.19s =========================================
scenario: commands[1]> coverage report
Name           Stmts   Miss  Cover
----------------------------------
src/charm.py     129     57    56%
----------------------------------
TOTAL            129     57    56%
  scenario: OK (6.89=setup[6.39]+cmd[0.44,0.06] seconds)
  congratulations :) (6.94 seconds)
```

Congratulations, you have written your first scenario test!

## Review the final code


For the full code see: [09_scenario_testing](https://github.com/canonical/juju-sdk-tutorial-k8s/tree/09_scenario_test)

For a comparative view of the code before and after this doc see: [Comparison](https://github.com/canonical/juju-sdk-tutorial-k8s/compare/08_unit_testing...09_scenario_test)

> **See next: {ref}`Write integration tests for your charm <write-integration-tests-for-your-charm>`**


