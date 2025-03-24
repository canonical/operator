(write-integration-tests-for-your-charm)=
# Write integration tests for your charm

> <small> {ref}`From Zero to Hero: Write your first Kubernetes charm <from-zero-to-hero-write-your-first-kubernetes-charm>` > Write integration tests for your charm</small>
> 
> **See previous: {ref}`Write unit tests for your charm <write-unit-tests-for-your-charm>`**

````{important}

This document is part of a series, and we recommend you follow it in sequence. However, you can also jump straight in by checking out the code from the previous branches:

```text
git clone https://github.com/canonical/juju-sdk-tutorial-k8s.git
cd juju-sdk-tutorial-k8s
git checkout 06_unit_testing
git checkout -b 07_integration_testing
```

````

A charm should function correctly not just in a mocked environment but also in a real deployment.

For example, it should be able to pack, deploy, and integrate without throwing exceptions or getting stuck in a `waiting` or a `blocked` status -- that is, it should correctly reach a status of `active` or `idle`.

You can ensure this by writing integration tests for your charm. In the charming world, these are usually written with the [`pytest-operator`](https://github.com/charmed-kubernetes/pytest-operator) library.

In this chapter you will write two small integration tests -- one to check that the charm packs and deploys correctly and one to check that the charm integrates successfully with the PostgreSQL database.

## Prepare your test environment

In your `tox.ini` file, add the following new environment:

```
[testenv:integration]
description = Run integration tests
deps =
    pytest
    juju
    pytest-operator
    -r {tox_root}/requirements.txt
commands =
    pytest -v \
           -s \
           --tb native \
           --log-cli-level=INFO \
           {posargs} \
           {[vars]tests_path}/integration
```

## Prepare your test directory

Create  a  `tests/integration` directory:

```text
mkdir ~/fastapi-demo/tests/integration
```

## Write and run a pack-and-deploy integration test

Let's begin with the simplest possible integration test, a [smoke test](https://en.wikipedia.org/wiki/Smoke_testing_(software)). This test will build and deploy the charm and verify that the installation hooks finish without any error. 

In your `tests/integration` directory, create a file `test_charm.py` and add the following test case:

```python
import asyncio
import logging
from pathlib import Path

import pytest
import yaml
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path('./charmcraft.yaml').read_text())
APP_NAME = METADATA['name']


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest):
    """Build the charm-under-test and deploy it.

    Assert on the unit status before any relations/configurations take place.
    """
    # Build and deploy charm from local source folder
    charm = await ops_test.build_charm('.')
    resources = {
        'demo-server-image': METADATA['resources']['demo-server-image']['upstream-source']
    }

    # Deploy the charm and wait for blocked/idle status
    # The app will not be in active status as this requires a database relation
    await asyncio.gather(
        ops_test.model.deploy(charm, resources=resources, application_name=APP_NAME),
        ops_test.model.wait_for_idle(
            apps=[APP_NAME], status='blocked', raise_on_blocked=False, timeout=120
        ),
    )
```

In your Multipass Ubuntu VM, run the test:

```bash
tox -e integration
```

The test takes some time to run as the `pytest-operator` running in the background will add a new model to an existing cluster (whose presence it assumes). If successful, it'll verify that your charm can pack and deploy as expected.

## Write and run an integrate-with-database integration test

The charm requires a database to be functional. Let's verify that this behaviour works as intended. For that, we need to deploy a database to the test cluster and integrate both applications. Finally, we should check that the charm reports an active status.

In your `tests/integration/test_charm.py` file add the following test case:

```python
@pytest.mark.abort_on_fail
async def test_database_integration(ops_test: OpsTest):
    """Verify that the charm integrates with the database.

    Assert that the charm is active if the integration is established.
    """
    await ops_test.model.deploy(
        application_name='postgresql-k8s',
        entity_url='postgresql-k8s',
        channel='14/stable',
    )
    await ops_test.model.integrate(f'{APP_NAME}', 'postgresql-k8s')
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME], status='active', raise_on_blocked=False, timeout=120
    )
```

```{important}

But if you run the one and then the other (as separate `pytest ...` invocations, then two separate models will be created unless you pass `--model=some-existing-model` to inform pytest-operator to use a model you provide.
```

In your Multipass Ubuntu VM, run the test again:

```text
ubuntu@charm-dev:~/fastapi-demo$ tox -e integration
```

The test may again take some time to run.

```{tip}

**Pro tip:** To make things faster, use the `--model=<existing model name>` to inform `pytest-operator` to use the model it has created for the first test. Otherwise, charmers often have a way to cache their pack or deploy results; an example is [spellbook](https://github.com/canonical/spellbook).
```

When it's done, the output should show two passing tests:

```text
...
  demo-api-charm/0 [idle] waiting: Waiting for database relation
INFO     juju.model:model.py:2759 Waiting for model:
  demo-api-charm/0 [idle] active: 
PASSED
-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- live log teardown --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
INFO     pytest_operator.plugin:plugin.py:783 Model status:

Model            Controller       Cloud/Region        Version  SLA          Timestamp
test-charm-2ara  main-controller  microk8s/localhost  3.1.5    unsupported  09:45:56+02:00

App             Version  Status  Scale  Charm           Channel    Rev  Address        Exposed  Message
demo-api-charm  1.0.1    active      1  demo-api-charm               0  10.152.183.99  no       
postgresql-k8s  14.7     active      1  postgresql-k8s  14/stable   73  10.152.183.50  no       

Unit               Workload  Agent  Address       Ports  Message
demo-api-charm/0*  active    idle   10.1.208.77          
postgresql-k8s/0*  active    idle   10.1.208.107         

INFO     pytest_operator.plugin:plugin.py:789 Juju error logs:


INFO     pytest_operator.plugin:plugin.py:877 Resetting model test-charm-2ara...
INFO     pytest_operator.plugin:plugin.py:866    Destroying applications demo-api-charm
INFO     pytest_operator.plugin:plugin.py:866    Destroying applications postgresql-k8s
INFO     pytest_operator.plugin:plugin.py:882 Not waiting on reset to complete.
INFO     pytest_operator.plugin:plugin.py:855 Forgetting main...


========================================================================================================================================================================== 2 passed in 290.23s (0:04:50) ==========================================================================================================================================================================
  integration: OK (291.01=setup[0.04]+cmd[290.97] seconds)
  congratulations :) (291.05 seconds)
```

Congratulations, with this integration test you have verified that your charms relation to PostgreSQL works as well!

## Review the final code

For the full code see: [07_integration_testing](https://github.com/canonical/juju-sdk-tutorial-k8s/tree/07_integration_testing)

For a comparative view of the code before and after this doc see: [Comparison](https://github.com/canonical/juju-sdk-tutorial-k8s/compare/06_unit_testing...07_integration_testing)
