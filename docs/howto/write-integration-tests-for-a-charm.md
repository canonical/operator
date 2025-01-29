(write-integration-tests-for-a-charm)=
# How to write integration tests for a charm

> See also: {ref}`testing`

This document shows how to write integration tests for a charm.

```{important}

Integration testing is only one part of a comprehensive testing strategy. See {ref}`How to test a charm <write-unit-tests-for-a-charm>` for unit testing and {ref}`How to write a functional test <write-scenario-tests-for-a-charm>`  for functional tests.

```

The instructions all use the Juju `python-libjuju` client, either through the `pytest-operator` library or directly.

> See more: [`python-libjuju`](https://pythonlibjuju.readthedocs.io/en/latest/), {ref}`pytest-operator`

## Prepare your environment

In order to run integrations tests you will need to have your environment set up with `tox` installed.

<!-- UPDATE LINKS
> See more: {ref}`How to set up your development environment <set-up-your-development-environment>`
-->

## Prepare the `tox.ini` configuration file

Check that the next information is in your `tox.ini` file. If you initialised the charm with `charmcraft init` it should already be there.

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

## Create a test file

By convention, integration tests are kept in the charm’s source tree, in a directory called `tests/integration`.

If you initialised the charm with `charmcraft init`, your charm directory should already contain a  `tests/integration/test_charm.py` file. Otherwise, create this directory structure manually (the test file can be called whatever you wish) and, inside the `.py` file, import `pytest` and, from the `pytest_operator.plugin`, the  `OpsTest` class provided by the `ops_test` fixture:

```
import pytest
from pytest_operator.plugin import OpsTest
```

The `ops_test` fixture is your entry point to the `pytest-operator` library, and the preferred way of interacting with Juju in integration tests. This fixture will create a model for each test file -- if you write two tests that should not share a model, make sure to place them in different files.

## Build your tests

```{note}

Use `pytest` custom markers to toggle which types of tests are being run so you can skip the destructive parts and focus on the business logic tests. See more: [Discourse | Pasotti: Classify tests with pytest custom markers for quick integration testing iterations](https://discourse.charmhub.io/t/classify-tests-with-pytest-custom-markers-for-quick-integration-testing-iterations/14006).

```

### Test build and deploy

To build and deploy the current charm, in your integration test file, add the function below:

```python
@pytest.mark.skip_if_deployed
@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest):
    charm = await ops_test.build_charm(".")
    app = await ops_test.model.deploy(charm)

    await ops_test.model.wait_for_idle(status="active",  timeout=60)
```

Tests run sequentially in the order they are written in the file. It can be useful to put tests that build and deploy applications in the top of the file as the applications can be used by other tests. For that reason, adding extra checks or `asserts` in this test is not recommended.

The decorator `@pytest.mark.abort_on_fail` abort all next tests if something goes wrong. With the decorator `@pytest.mark.skip_if_deployed` you can skip that test if a `--model` is passed as a command line parameter (see {ref}`run-your-tests` for more information).

`ops_test.build_charm` builds the charm with charmcraft. `ops_test.model` is an instance of `python-libjuju` 's [Model](https://pythonlibjuju.readthedocs.io/en/latest/api/juju.model.html#juju.model.Model) class that reference the active model tracked by `pytest-operator` for the current module.

As an alternative to `wait_for_idle`, you can explicitly block until the application status is `active` or `error` and then assert that it is `active`.

```
    await ops_test.model.block_until(lambda: app.status in ("active", "error"), timeout=60,)
    assert app.status, "active"
```

> Example implementations: [charm-coredns](https://github.com/charmed-kubernetes/charm-coredns/blob/b1d83b6a31200924fefcd288336bc1f9323c6a72/tests/integration/test_integration.py#L21), [charm-calico](https://github.com/charmed-kubernetes/charm-calico/blob/e1dfdda92fefdba90b7b7e5247fbc861c34ad146/tests/integration/test_calico_integration.py#L18)

> See more: 
> - [`pytest-operator` | `ops_test.build_charm`](https://github.com/charmed-kubernetes/pytest-operator/blob/ab50fc20320d3ea3d8a37495f92a004531a4023f/pytest_operator/plugin.py#L1020)
> - [`python-libjuju` | `model.deploy `](https://github.com/juju/python-libjuju/blob/2581b0ced1df6201c6b7fd8cc0b20dcfa9d97c51/juju/model.py#L1658)

### Deploy your charm with resources

> See first: `manage-resources`

A charm can require `file` or `oci-image` `resources` to work, that can be provided to `ops_test.model.deploy`. In Charmhub, resources have revision numbers. For file resources already stored in Charmhub, you can use `ops_test.download_resources`:

```python
async def test_build_and_deploy(ops_test: OpsTest):
    charm = await ops_test.build_charm(".")
    arch_resources = ops_test.arch_specific_resources(charm)
    resources = await ops_test.download_resources(charm, resources=arch_resources)
    app = await ops_test.model.deploy(charm, resources=resources)
    await ops_test.model.wait_for_idle(status="active",  timeout=60)
```

You can also reference a file resource on the filesystem. You can also use [`ops_test.build_resources`](https://github.com/charmed-kubernetes/pytest-operator/blob/ab50fc20320d3ea3d8a37495f92a004531a4023f/pytest_operator/plugin.py#L1073) to build file resources from a build script.

For `oci-images` you can reference an image registry.
```
    ...
    resources = {"resource_name": "localhost:32000/image_name:latest"}
    app = await ops_test.model.deploy(charm, resources=resources)
    ...
```

> Example implementations: [kubernetes-control-plane](https://github.com/charmed-kubernetes/charm-kubernetes-control-plane/blob/8769db394bf377a03ce94066307ecf831b88ad17/tests/integration/test_kubernetes_control_plane_integration.py#L41), [synapse-operator](https://github.com/canonical/synapse-operator/blob/eb44f4959a00040f08b98470f8b17cae4cc616da/tests/integration/conftest.py#L119), [prometheus-k8s](https://github.com/canonical/prometheus-k8s-operator/blob/d29f323343a1e4906a8c71104fcd1de817b2c2e6/tests/integration/test_remote_write_with_zinc.py#L27)

>
> See more: 
> - [`pytest-operator` | `build_resources`](https://github.com/charmed-kubernetes/pytest-operator/blob/ab50fc20320d3ea3d8a37495f92a004531a4023f/pytest_operator/plugin.py#L1073)
> - [`pytest-operator` |  `download_resources`](https://github.com/charmed-kubernetes/pytest-operator/blob/ab50fc20320d3ea3d8a37495f92a004531a4023f/pytest_operator/plugin.py#L1101)
> - [`python-libjuju` | `model.deploy`](https://github.com/juju/python-libjuju/blob/2581b0ced1df6201c6b7fd8cc0b20dcfa9d97c51/juju/model.py#L1658)


### Test a relation

To test an integration between two applications, you can just integrate them through
the model. Both applications have to be deployed beforehand.

``` 
    ...
async def test_my_integration(ops_test: OpsTest):
        # both application_1 and application_2 have to be deployed
        # in the current test or a previous one.
        await ops_test.model.integrate("application_1:relation_name_1", "application_2:relation_name_2")
        await ops_test.model.wait_for_idle(status="active", timeout=60)
        # check any assertion here
    ....
```

> Example implementations: [slurmd-operator](https://github.com/canonical/slurmd-operator/blob/ffb24b05bec1b10cc512c060a4739358bfea0df0/tests/integration/test_charm.py#L89)

> See more: [`python-libjuju` | `model.integrate`](https://github.com/juju/python-libjuju/blob/2581b0ced1df6201c6b7fd8cc0b20dcfa9d97c51/juju/model.py#L1476)

### Test a configuration

> See first: {ref}`manage-configurations`

You can set a configuration option in your application and check its results. 

``` 
async def test_config_changed(ops_test: OpsTest):
    ...
        await ops_test.model.applications["synapse"].set_config({"server_name": "invalid_name"})
        # In this case, when setting server_name to "invalid_name" 
        # we could for example expect a blocked status.
        await ops_test.model.wait_for_idle(status="blocked",  timeout=60)
    ....
```
> See also: https://discourse.charmhub.io/t/how-to-add-a-configuration-option-to-a-charm/4458
>
> See also: [python-libjuju | application.set_config](https://github.com/juju/python-libjuju/blob/2581b0ced1df6201c6b7fd8cc0b20dcfa9d97c51/juju/application.py#L591)



### Test an action

<!-- UPDATE LINKS
> See also: [Action]()
-->

You can execute an action on a unit and get its results. 

```text
async def test_run_action(ops_test: OpsTest):
    action_register_user = await ops_test.model.applications["myapp"].units[0].run_action("register-user", username="ubuntu")
    await action_register_user.wait()
    assert action_register_user.status == "completed"
    password = action_register_user.results["user-password"]
    # We could for example check here that we can login with the new user
```

> See also: [python-libjuju | unit.run_action](https://github.com/juju/python-libjuju/blob/2581b0ced1df6201c6b7fd8cc0b20dcfa9d97c51/juju/unit.py#L274)

### Interact with the workload

To interact with the workload, you need to have access to it. This is dependent on many aspects of your application, environment and network topology.

You can get information from your application or unit addresses using `await ops_test.model.get_status`. That way, if your application exposes a public address you can reference it. You can also try to connect to a unit address or public address.

```text
async def test_workload_connectivity(ops_test: OpsTest):
    status = await ops_test.model.get_status()
    address = status.applications['my_app'].public_address
    # Or you can try to connect to a concrete unit
    # address = status.applications['my_app'].units['my_app/0'].public_address
    # address = status.applications['my_app'].units['my_app/0'].address
    appurl = f"http://{address}/"
    r = requests.get(appurl)
    assert r.status_code == 200
```

How you can connect to a private or public address is dependent on your configuration, so you may need a different approach.

> Example implementations: [mongodb-k8s-operator](https://github.com/canonical/mongodb-k8s-operator/blob/8b9ebbee3f225ca98175c25781f1936dc4a62a7d/tests/integration/metrics_tests/test_metrics.py#L33), [tempo-k8s-operator](https://github.com/canonical/tempo-k8s-operator/blob/78a1143d99af99a1a56fe9ff82b1a3563e4fd2f7/tests/integration/test_integration.py#L69), [synapse](https://github.com/canonical/synapse-operator/blob/eb44f4959a00040f08b98470f8b17cae4cc616da/tests/integration/conftest.py#L170)

<!-- UPDATE LINKS:
> See more: 
> - [Charm development best practices > Fetching network information]()
> - [`juju` CLI commands > juju expose]()
-->

### Run a subprocess command within Juju context

You can run a command within the Juju context with:

```text
    ...
    command = ["microk8s", "version"]
    returncode, stdout, stderr = await ops_test.run(*command, check=True)
   ...
```

You can similarly invoke the Juju CLI. This can be useful for cases where `python-libjuju` sees things differently than the Juju CLI. By default the environment variable `JUJU_MODEL` is set,
so you don't need to include the `-m` parameter.

```
    ....
    command = ["secrets"]
    returncode, stdout, stderr = await ops_test.juju(*command, check=True)
    ....
```

> Example implementations: [prometheus-k8s-operator](https://github.com/canonical/prometheus-k8s-operator/blob/d29f323343a1e4906a8c71104fcd1de817b2c2e6/tests/integration/conftest.py#L86), [hardware-observer-operator](https://github.com/canonical/hardware-observer-operator/blob/08c50798ca1c133a5d8ba5c889e0bcb09771300b/tests/functional/conftest.py#L14)


> See more: 
> - [`pytest-operator` | `run`](https://github.com/charmed-kubernetes/pytest-operator/blob/ab50fc20320d3ea3d8a37495f92a004531a4023f/pytest_operator/plugin.py#L576)
> - [`pytest-operator` | `juju`](https://github.com/charmed-kubernetes/pytest-operator/blob/ab50fc20320d3ea3d8a37495f92a004531a4023f/pytest_operator/plugin.py#L624)

### Use several models

You can use `pytest-operator` with several models, in the same cloud or in 
different clouds. This way you can, for example, integrate machine charms
with Kubernetes charms easily.

You can track a new model with:

```
    new_model = await ops_test.track_model("model_alias",
                                           cloud_name="cloud_name",
                                           credential_name="credentials")
```

`track_model` will track a model with alias `model_alias` (not the real model name). It maybe necessary to use `credential_name` if you do not use the same cloud that the controller.

Using the new alias, you can switch context to the new created model, similar to `juju switch` command:

```
    with ops_test.model_context("model_alias"):
        # Here ops_test.model relates to the model referred by <model_alias>
        # You can now use ops_test.model and it will apply to the model in the context
```

`pytest-operator` will handle the new created model by default. If you want to, you can remove it from the controller at any point:

```
    await ops_test.forget_model("model_alias")
```

> Example implementations: [`charm-kubernetes-autoscaler`](https://github.com/charmed-kubernetes/charm-kubernetes-autoscaler/blob/8f4ddf5d66802ade73ed3aab2bb8d09fd9e4d63a/tests/integration/test_kubernetes_autoscaler.py#L31)

<!-- UPDATE LINKS:
> See more: 
> - [Juju offers]()
> - [How to manage clouds]()
> - [pytest-operator | track_model](https://github.com/charmed-kubernetes/pytest-operator/blob/ab50fc20320d3ea3d8a37495f92a004531a4023f/pytest_operator/plugin.py#L720)
> - [pytest-operator | model_context](https://github.com/charmed-kubernetes/pytest-operator/blob/ab50fc20320d3ea3d8a37495f92a004531a4023f/pytest_operator/plugin.py#L480)
> - [pytest-operator | forget_model](https://github.com/charmed-kubernetes/pytest-operator/blob/ab50fc20320d3ea3d8a37495f92a004531a4023f/pytest_operator/plugin.py#L812)
-->


### Deploy a bundle

```{note}

It is not recommended to use `ops_test.build_bundle` and `ops_test.deploy_bundle` until this [issue](https://github.com/charmed-kubernetes/pytest-operator/issues/98) is closed, as it uses `juju-bundle` which is outdated. You can deploy bundles using `ops_test.model.deploy` or `ops_test.juju`.

```


### Render bundles and charms

`pytest-operator` has utilities to template your charms and bundles using Jinja2.

To render a kubernetes bundle with your current charm, create the file `./test/integration/bundle.yaml.j2` with this content:
```
bundle: kubernetes
applications:
  my-app:
    charm: {{ charm }}
    scale: {{ scale }}
```

You can now add the next integration test that will build an deploy the bundle with the current charm:
```
async def test_build_and_deploy_bundle(ops_test: OpsTest):
    charm = await ops_test.build_charm(".")

    bundle = ops_test.render_bundle(
        'tests/integration/bundle.yaml.j2',
        charm=charm,
        scale=1,
    )
    juju_cmd = ["deploy", str(bundle)]
    rc, stdout, stderr = await ops_test.juju(*juju_cmd)
```


> Example implementations: [`hardware-observer-operator`](https://github.com/canonical/hardware-observer-operator/blob/47a79eb2872f6222099e7f48b8daafe8d20aa946/tests/functional/test_charm.py#L57)



### Speed up `update_status`  with `fast_forward`

If your charm code depends on the `update_status` event, you can speed up its
firing rate with `fast_forward`. Inside the new async context you can put any code that will benefit  from the new refresh rate so your test may execute faster.

``` 
    ...
    app = await ops_test.model.deploy(charm)

    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(status="active",  timeout=120)
    ....
```

> Example implementations [`postgresql-k8s-operator`](https://github.com/canonical/postgresql-k8s-operator/blob/69b2c138fa6b974883aa6d3d15a3315189d321d8/tests/integration/ha_tests/test_upgrade.py#L58), [`synapse-operator`](https://github.com/canonical/synapse-operator/blob/05c00bb7666197d04f1c025c36d8339b10b64a1a/tests/integration/test_charm.py#L249)

 
> See more:
> - [`pytest-operator` | `fast_forward`](https://github.com/charmed-kubernetes/pytest-operator/blob/ab50fc20320d3ea3d8a37495f92a004531a4023f/pytest_operator/plugin.py#L1400)

(run-your-tests)=
## Run your tests

By default you can run all your tests with:

```
tox -e integration
```

These tests will use the context of the current controller in Juju, and by default will create a new model per module, that will be destroyed when the test is finished. The cloud, controller and model name can be specified with the parameters `--cloud`, `--controller` and `--model` parameters. 

If you specify the model name and do not delete the model on test tear down with the parameter `--keep-models`, you can reuse a model from a previous test run, as in the next example:
```
# in the initial execution, the new model will be created
tox -e integration -- --keep-models --model test-example-model
# in the next execution it will reuse the model created previously:
tox -e integration -- --keep-models --model test-example-model --no-deploy
```

The parameter `--no-deploy` will skip tests decorated with `@pytest.mark.skip_if_deployed`. That way you can iterate faster on integration tests, as applications can be deployed only once.

There are different ways of specifying a subset of tests to run using `pytest`. With the `-k` option you can specify different expressions. For example, the next command will run all tests in the `test_charm.py` file except `test_one` function.
```
tox -e integration -- tests/integration/test_charm.py -k "not test_one"
```

<!-- UPDATE LINKS:
> Example implementations: [`mysql-k8s-operator`]()
-->

> See more: 
> - [`pytest-operator` | `skip_if_deployed`](https://github.com/charmed-kubernetes/pytest-operator/blob/ab50fc20320d3ea3d8a37495f92a004531a4023f/pytest_operator/plugin.py#L139)
> - [`pytest | How to invoke pytest`](https://docs.pytest.org/en/7.1.x/how-to/usage.html)

## Generate crash dumps

To generate crash dumps, you need the `juju-crashdump` tool .


You can install it with `sudo snap install --classic juju-crashdump`.

By default, when tests are run, a crash dump file will be created in the current directory if a test fails and if `--keep-models` is `false`. This crash dump file will include the current configuration and also Juju logs.

You can disable crash dump generation with `--crash-dump=never`. To always create a crash dump file (even when tests do not fail) to a specific location run:

```
tox -e integration -- --crash-dump=always --crash-dump-output=/tmp
```

> See more: 
> - [`juju-crashdump`](https://github.com/juju/juju-crashdump)
> - [`pytest-operator` | `--crash-dump`](https://github.com/charmed-kubernetes/pytest-operator/blob/ab50fc20320d3ea3d8a37495f92a004531a4023f/pytest_operator/plugin.py#L97)
