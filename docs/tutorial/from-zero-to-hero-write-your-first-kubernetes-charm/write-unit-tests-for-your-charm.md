(write-unit-tests-for-your-charm)=
# Write unit tests for your charm

> <small> {ref}`From Zero to Hero: Write your first Kubernetes charm <from-zero-to-hero-write-your-first-kubernetes-charm>` > Write a unit test for your charm</small>
> 
> **See previous: {ref}`Observe your charm with COS Lite <observe-your-charm-with-cos-lite>`**

````{important}

This document is part of a series, and we recommend you follow it in sequence. However, you can also jump straight in by checking out the code from the previous branches:

```bash
git clone https://github.com/canonical/juju-sdk-tutorial-k8s.git
cd juju-sdk-tutorial-k8s
git checkout 07_cos_integration
git checkout -b 08_unit_testing
```

````

When you're writing a charm, you will want to ensure that it will behave reliably as intended.

For example, that the various components -- relation data, pebble services, or configuration files -- all behave as expected in response to an event.

You can ensure all this by writing a rich battery of units tests. In the context of a charm we recommended using [`pytest`](https://pytest.org/) (but [`unittest`](https://docs.python.org/3/library/unittest.html) can also be used) and especially the operator framework's built-in testing library --  [](ops_testing_harness). We will be using the Python testing tool [`tox`](https://tox.wiki/en/4.14.2/index.html) to automate our testing and set up our testing environment.

In this chapter you will write a simple unit test to check that your workload container is initialised correctly.


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

```bash
mkdir -p tests/unit
```

### Write your unit test

In your `tests/unit` directory, create a file called `test_charm.py`.

In this file, do all of the following:

First, add the necessary imports:

```python
import ops
import ops.testing
import pytest

from charm import FastAPIDemoCharm
```

Then, add a test [fixture](https://docs.pytest.org/en/7.1.x/how-to/fixtures.html) that sets up the testing harness and makes sure that it will be cleaned up after each test:

```python
@pytest.fixture
def harness():
    harness = ops.testing.Harness(FastAPIDemoCharm)
    harness.begin()
    yield harness
    harness.cleanup()

```

Finally, add a first test case as a function, as below. As you can see, this test case is used to verify that the deployment of the `fastapi-service` within the `demo-server` container is configured correctly and that the service is started and running as expected when the container is marked as `pebble-ready`. It also checks that the unit's status is set to active without any error messages. Note that we mock some methods of the charm because they do external calls that are not represented in the state of this unit test.

```python
def test_pebble_layer(
    monkeypatch: pytest.MonkeyPatch, harness: ops.testing.Harness[FastAPIDemoCharm]
):
    monkeypatch.setattr(FastAPIDemoCharm, 'version', '1.0.0')
    # Expected plan after Pebble ready with default config
    expected_plan = {
        'services': {
            'fastapi-service': {
                'override': 'replace',
                'summary': 'fastapi demo',
                'command': 'uvicorn api_demo_server.app:app --host=0.0.0.0 --port=8000',
                'startup': 'enabled',
                # Since the environment is empty, Layer.to_dict() will not
                # include it.
            }
        }
    }

    # Simulate the container coming up and emission of pebble-ready event
    harness.container_pebble_ready('demo-server')
    harness.evaluate_status()

    # Get the plan now we've run PebbleReady
    updated_plan = harness.get_container_pebble_plan('demo-server').to_dict()
    service = harness.model.unit.get_container('demo-server').get_service('fastapi-service')
    # Check that we have the plan we expected:
    assert updated_plan == expected_plan
    # Check the service was started:
    assert service.is_running()
    # Ensure we set a BlockedStatus with appropriate message:
    assert isinstance(harness.model.unit.status, ops.BlockedStatus)
    assert 'Waiting for database' in harness.model.unit.status.message
```


> Read more: [](ops_testing_harness)

## Run the test

In your Multipass Ubuntu VM shell, run your unit test as below:

```bash
ubuntu@charm-dev:~/fastapi-demo$ tox -e unit
```

You should get an output similar to the one below:

```bash
unit: commands[0]> coverage run --source=/home/ubuntu/fastapi-demo/src -m pytest --tb native -v -s /home/ubuntu/fastapi-demo/tests/unit
=============================================================================================================================================================================== test session starts ===============================================================================================================================================================================
platform linux -- Python 3.10.13, pytest-8.0.2, pluggy-1.4.0 -- /home/ubuntu/fastapi-demo/.tox/unit/bin/python
cachedir: .tox/unit/.pytest_cache
rootdir: /home/ubuntu/fastapi-demo
collected 1 item                                                                                                                                                                                                                                                                                                                                                                  

tests/unit/test_charm.py::test_pebble_layer PASSED

================================================================================================================================================================================ 1 passed in 0.30s ================================================================================================================================================================================
unit: commands[1]> coverage report
Name           Stmts   Miss  Cover
----------------------------------
src/charm.py     118     49    58%
----------------------------------
TOTAL            118     49    58%
  unit: OK (0.99=setup[0.04]+cmd[0.78,0.16] seconds)
  congratulations :) (1.02 seconds)
```

Congratulations, you have now successfully implemented your first unit test!

```{caution}

As you can see in the output, the current tests cover 58% of the charm code. In a real-life scenario make sure to cover much more!

```

## Review the final code

For the full code see: [08_unit_testing](https://github.com/canonical/juju-sdk-tutorial-k8s/tree/08_unit_testing)

For a comparative view of the code before and after this doc see: [Comparison](https://github.com/canonical/juju-sdk-tutorial-k8s/compare/07_cos_integration...08_unit_testing)

> **See next: {ref}`Write scenario tests for your charm <write-scenario-tests-for-your-charm>`**




