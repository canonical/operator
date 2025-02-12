(open-a-kubernetes-port-in-your-charm)=
# Open a Kubernetes port in your charm

> <small> {ref}`From Zero to Hero: Write your first Kubernetes charm <from-zero-to-hero-write-your-first-kubernetes-charm>` > Open a Kubernetes port in your charm</small>
> 
> **See previous: {ref}`Write integration tests for your charm <write-integration-tests-for-your-charm>`**

````{important}

This document is part of a series, and we recommend you follow it in sequence. However, you can also jump straight in by checking out the code from the previous branches:

```bash
git clone https://github.com/canonical/juju-sdk-tutorial-k8s.git
cd juju-sdk-tutorial-k8s
git checkout 10_integration_testing
git checkout -b 11_open_port_k8s_service
```

````

A deployed charm should be consistently accessible via a stable URL on a cloud.

However, our charm is currently accessible only at the IP pod address and, if the pod gets recycled, the IP address will change as well. 

> See earlier chapter: {ref}`Make your charm configurable <make-your-charm-configurable>` 

In Kubernetes you can make a service permanently reachable under a stable URL on the cluster by exposing a service port via the `ClusterIP`. In Juju 3.1+, you can take advantage of this by using the `Unit.set_ports()` method.

> Read more: [ClusterIP](https://kubernetes.io/docs/concepts/services-networking/service/#type-clusterip)

In this chapter of the tutorial you will extend the existing `server-port` configuration option to use Juju `open-port` functionality to expose a Kubernetes service port. Building on your experience from the previous testing chapters, you will also write tests to check that the new feature you've added works as intended.


## Add a Kubernetes service port to your charm

In your `src/charm.py` file, do all of the following:

In the `_on_config_changed` method, add a new method:

```python
self._handle_ports()
```

Then, in the definition of the `FastAPIDemoCharm` class, define the method:

```python
def _handle_ports(self) -> None:
    port = cast(int, self.config['server-port'])
    self.unit.set_ports(port)
```

> See more: [](ops.Unit.set_ports)


## Test the new feature


### Write a unit test


```{important}

**If you've skipped straight to this chapter:** <br> Note that it builds on the earlier unit testing chapter. To catch up, see: {ref}`Write unit tests for your charm <write-unit-tests-for-your-charm>`.

```

Let's write a unit test to verify that the port is opened. Open `tests/unit/test_charm.py` and add the following test function to the file.

```python
@pytest.mark.parametrize(
    'port,expected_status',
    [
        (22, ops.BlockedStatus('Invalid port number, 22 is reserved for SSH')),
        (1234, ops.BlockedStatus('Waiting for database relation')),
    ],
)
def test_port_configuration(
    monkeypatch, harness: ops.testing.Harness[FastAPIDemoCharm], port, expected_status
):
    # Given
    monkeypatch.setattr(FastAPIDemoCharm, 'version', '1.0.1')
    harness.container_pebble_ready('demo-server')
    # When
    harness.update_config({'server-port': port})
    harness.evaluate_status()
    currently_opened_ports = harness.model.unit.opened_ports()
    port_numbers = {port.port for port in currently_opened_ports}
    server_port_config = harness.model.config.get('server-port')
    unit_status = harness.model.unit.status
    # Then
    if port == 22:
        assert server_port_config not in port_numbers
    else:
        assert server_port_config in port_numbers
    assert unit_status == expected_status
```

```{important}

**Tests parametrisation** <br> Note that we used the `parametrize` decorator to run a single test against multiple sets of arguments.  Adding a new test case, like making sure that the error message is informative given a negative or too big port number, would be as simple as extending the list in the decorator call.
See [How to parametrize fixtures and test functions](https://docs.pytest.org/en/8.0.x/how-to/parametrize.html).

```

Time to run the tests!

In your Multipass Ubuntu VM shell, run the unit test:

```
ubuntu@charm-dev:~/fastapi-demo$ tox -re unit
```

If successful, you should get an output similar to the one below:

```bash 
$ tox -re unit
unit: remove tox env folder /home/ubuntu/fastapi-demo/.tox/unit
unit: install_deps> python -I -m pip install cosl 'coverage[toml]' pytest -r /home/ubuntu/fastapi-demo/requirements.txt
unit: commands[0]> coverage run --source=/home/ubuntu/fastapi-demo/src -m pytest --tb native -v -s /home/ubuntu/fastapi-demo/tests/unit
========================================= test session starts =========================================
platform linux -- Python 3.10.13, pytest-8.0.2, pluggy-1.4.0-- /home/ubuntu/fastapi-demo/.tox/unit/bin/python
cachedir: .tox/unit/.pytest_cache
rootdir: /home/ubuntu/fastapi-demo
collected 3 items                                                                                      

tests/unit/test_charm.py::test_pebble_layer PASSED
tests/unit/test_charm.py::test_port_configuration[22-expected_status0] PASSED
tests/unit/test_charm.py::test_port_configuration[1234-expected_status1] PASSED

========================================== 3 passed in 0.21s ==========================================
unit: commands[1]> coverage report
Name           Stmts   Miss  Cover
----------------------------------
src/charm.py     122     43    65%
----------------------------------
TOTAL            122     43    65%
  unit: OK (6.00=setup[5.43]+cmd[0.49,0.09] seconds)
  congratulations :) (6.04 seconds)
```

### Write a scenario test

Let's also write a scenario test! Add this test to your `tests/scenario/test_charm.py` file:

```python
def test_open_port(monkeypatch: MonkeyPatch):
    monkeypatch.setattr('charm.LogProxyConsumer', Mock())
    monkeypatch.setattr('charm.MetricsEndpointProvider', Mock())
    monkeypatch.setattr('charm.GrafanaDashboardProvider', Mock())

    # Use scenario.Context to declare what charm we are testing.
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
    state_in = scenario.State(
        leader=True,
        relations=[
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
            scenario.PeerRelation(
                endpoint='fastapi-peer',
                peers_data={'unit_stats': {'started_counter': '0'}},
            ),
        ],
        containers=[
            scenario.Container(name='demo-server', can_connect=True),
        ],
    )
    state1 = ctx.run('config_changed', state_in)
    assert len(state1.opened_ports) == 1
    assert state1.opened_ports[0].port == 8000
    assert state1.opened_ports[0].protocol == 'tcp'
```

In your Multipass Ubuntu VM shell, run your scenario test as below:

```bash
ubuntu@charm-dev:~/fastapi-demo$ tox -re scenario     
```

If successful, this should yield:

```bash
scenario: remove tox env folder /home/ubuntu/fastapi-demo/.tox/scenario
scenario: install_deps> python -I -m pip install cosl 'coverage[toml]' ops-scenario pytest -r /home/ubuntu/fastapi-demo/requirements.txt
scenario: commands[0]> coverage run --source=/home/ubuntu/fastapi-demo/src -m pytest --tb native -v -s /home/ubuntu/fastapi-demo/tests/scenario
========================================= test session starts =========================================
platform linux -- Python 3.10.13, pytest-8.0.2, pluggy-1.4.0 -- /home/ubuntu/fastapi-demo/.tox/scenario/bin/python
cachedir: .tox/scenario/.pytest_cache
rootdir: /home/ubuntu/fastapi-demo
collected 2 items                                                                                     

tests/scenario/test_charm.py::test_get_db_info_action PASSED
tests/scenario/test_charm.py::test_open_port PASSED

========================================== 2 passed in 0.31s ==========================================
scenario: commands[1]> coverage report
Name           Stmts   Miss  Cover
----------------------------------
src/charm.py     122     22    82%
----------------------------------
TOTAL            122     22    82%
  scenario: OK (6.66=setup[5.98]+cmd[0.59,0.09] seconds)
  congratulations :) (6.69 seconds)
```

### Write an integration test

In your `tests/integration` directory, create a `helpers.py` file with the following contents:

```python
import socket
from pytest_operator.plugin import OpsTest


async def get_address(ops_test: OpsTest, app_name: str, unit_num: int = 0) -> str:
    """Get the address for a the k8s service for an app."""
    status = await ops_test.model.get_status()
    k8s_service_address = status['applications'][app_name].public_address
    return k8s_service_address


def is_port_open(host: str, port: int) -> bool:
    """check if a port is opened in a particular host"""
    try:
        with socket.create_connection((host, port), timeout=5):
            return True  # If connection succeeds, the port is open
    except (ConnectionRefusedError, TimeoutError):
        return False  # If connection fails, the port is closed
```

In your existing `tests/integration/test_charm.py` file, import the methods defined in `helpers.py`:

```python
from helpers import is_port_open, get_address
```

Now add the test case that will cover open ports:

```python
@pytest.mark.abort_on_fail
async def test_open_ports(ops_test: OpsTest):
    """Verify that setting the server-port in charm's config correctly adjust k8s service

    Assert blocked status in case of port 22 and active status for others
    """
    app = ops_test.model.applications.get('demo-api-charm')

    # Get the k8s service address of the app
    address = await get_address(ops_test=ops_test, app_name=APP_NAME)
    # Validate that initial port is opened
    assert is_port_open(address, 8000)

    # Set Port to 22 and validate app going to blocked status with port not opened
    await app.set_config({'server-port': '22'})
    (await ops_test.model.wait_for_idle(apps=[APP_NAME], status='blocked', timeout=120),)
    assert not is_port_open(address, 22)

    # Set Port to 6789 "Dummy port" and validate app going to active status with port opened
    await app.set_config({'server-port': '6789'})
    (await ops_test.model.wait_for_idle(apps=[APP_NAME], status='active', timeout=120),)
    assert is_port_open(address, 6789)
```
In your Multipass Ubuntu VM shell, run the test as below:

```bash
ubuntu@charm-dev:~/fastapi-demo$ tox -re integration     
```

This test will take longer as a new model needs to be created. If successful, it should yield something similar to the output below:

```bash
==================================== 3 passed in 234.15s (0:03:54) ====================================
  integration: OK (254.77=setup[19.55]+cmd[235.22] seconds)
  congratulations :) (254.80 seconds)
```

## Validate your charm

Congratulations, you've added a new feature to your charm, and also written tests to ensure that it will work properly. Time to give this feature a test drive!

In your Multipass VM, repack and refresh your charm as below:

```bash
ubuntu@charm-dev:~/fastapi-demo$ charmcraft pack
juju refresh \
  --path="./demo-api-charm_ubuntu-22.04-amd64.charm" \
  demo-api-charm --force-units --resource \
  demo-server-image=ghcr.io/canonical/api_demo_server:1.0.1
```

Watch your charm deployment status change until deployment settles down:

```
juju status --watch 1s
```

Use `kubectl` to list the available services and verify that `demo-api-charm` service exposes the `ClusterIP` on the expected port:


```bash
$ kubectl get services -n charm-model
NAME                            TYPE        CLUSTER-IP       EXTERNAL-IP   PORT(S)              AGE
modeloperator                   ClusterIP   10.152.183.231   <none>        17071/TCP            34m
demo-api-charm-endpoints        ClusterIP   None             <none>        <none>               19m
demo-api-charm                  ClusterIP   10.152.183.92    <none>        65535/TCP,8000/TCP   19m
postgresql-k8s-endpoints        ClusterIP   None             <none>        <none>               18m
postgresql-k8s                  ClusterIP   10.152.183.162   <none>        5432/TCP,8008/TCP    18m
postgresql-k8s-primary          ClusterIP   10.152.183.109   <none>        8008/TCP,5432/TCP    18m
postgresql-k8s-replicas         ClusterIP   10.152.183.29    <none>        8008/TCP,5432/TCP    18m
patroni-postgresql-k8s-config   ClusterIP   None             <none>        <none>               17m
```

Finally, `curl` the `ClusterIP` to verify that the `version` endpoint responds on the expected port:

```bash
$ curl 10.152.183.92:8000/version
{"version":"1.0.1"}
```

Congratulations, your service now exposes an external port that is independent of any pod / node restarts!

## Review the final code

For the full code see: [11_open_port_k8s_service](https://github.com/canonical/juju-sdk-tutorial-k8s/tree/11_open_port_k8s_service)

For a comparative view of the code before and after this doc see: [Comparison](https://github.com/canonical/juju-sdk-tutorial-k8s/compare/10_integration_testing...11_open_port_k8s_service)

> **See next: {ref}`Publish your charm on Charmhub <publish-your-charm-on-charmhub>`**

