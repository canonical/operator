(how-to-set-the-workload-version)=
# How to set the workload version

## Implement the feature

Applications modelled by charms have their own version; each application
will have its own versioning scheme, and its own way of accessing that
information. To make things easier for Juju admins, the charm should expose the
workload version through Juju - it will be visible in `juju status` (in the
default tabular view, in the application table, in the "Version" column; in the
JSON or YAML format, under `applications.<app name>.version`).

```{note}

If the charm has not set the workload version, then the field will not be
present in JSON or YAML format, and if the version string is too long or
contains particular characters then it will not be displayed in the tabular
format.

```

For Kubernetes charms, the workload is typically started in the
`<container>-pebble-ready` event, and the version can be retrieved and passed
to Juju at that point. If the workload cannot immediately provide a version
string, then your charm will need to do this in a later event instead.

For machine charms, the workload should be available in the `start` event, so
you can retrieve the version from it and pass it to Juju in a `start` event
handler. In this case, if you don't already have a `start` handler, in the
`src/charm.py` file, in the `__init__` function of your charm, set up an
observer for the `start` event and pair that with an event handler. For example:

```python
self.framework.observe(self.on.start, self._on_start)
```

> See more: [`ops.StartEvent`](https://ops.readthedocs.io/en/latest/#ops.StartEvent)

Now, in the body of the charm definition, define the event handler. Typically,
the workload version is retrieved from the workload itself, with a subprocess
(machine charms) or Pebble exec (Kubernetes charms) call or HTTP request. For
example:

```python
def _on_start(self, event: ops.StartEvent):
    # The workload exposes the version via HTTP at /version
    version = requests.get("http://localhost:8000/version").text
    self.unit.set_workload_version(version)
```

> See more: [`ops.Unit.set_workload_version`](https://ops.readthedocs.io/en/latest/#ops.Unit.set_workload_version)

> Examples: [`jenkins-k8s` sets the workload version after getting it from the Jenkins package](https://github.com/canonical/jenkins-k8s-operator/blob/29e9b652714bd8314198965c41a60f5755dd381c/src/charm.py#L115), [`discourse-k8s` sets the workload version after getting it via an exec call](https://github.com/canonical/discourse-k8s-operator/blob/f523b29f909c69da7b9510b581dfcc2309698222/src/charm.py#L581), [`synapse` sets the workload version after getting it via an API call](https://github.com/canonical/synapse-operator/blob/778bcd414644c922373d542a304be14866835516/src/charm.py#L265)

## Test the feature

> See first: [Get started with charm testing](https://juju.is/docs/sdk/get-started-with-charm-testing)

You'll want to add three levels of tests, unit, scenario, and integration.


### Write unit tests

> See first: {ref}`write-unit-tests-for-a-charm`

To verify the workload version is set in a unit test, use the
`ops.testing.Harness.get_workload_version()` method to
get the version that the charm set. In your `tests/unit/test_charm.py` file,
add a new test to verify the workload version is set; for example:

```python
# You may already have this fixture to use in other tests.
@pytest.fixture()
def harness():
    yield ops.testing.Harness(MyCharm)
    harness.cleanup()

def test_start(harness):
    # Suppose that the charm gets the workload version by running the command
    # `/bin/server --version` in the container. Firstly, we mock that out:
    harness.handle_exec("webserver", ["/bin/server", "--version"], result="1.2\n")
    # begin_with_initial_hooks will trigger the 'start' event, and we expect
    # the charm's 'start' handler to set the workload version.
    harness.begin_with_initial_hooks()
    assert harness.get_workload_version() == "1.2"
```

> See more: [`ops.testing.Harness.get_workload_version`](https://ops.readthedocs.io/en/latest/harness.html#ops.testing.Harness.get_workload_version)

> Examples: [grafana-k8s checking the workload version](https://github.com/canonical/grafana-k8s-operator/blob/1c80f746f8edeae6fd23ddf31eed45f5b88c06b4/tests/unit/test_charm.py#L283) (and the [earlier mocking](https://github.com/canonical/grafana-k8s-operator/blob/1c80f746f8edeae6fd23ddf31eed45f5b88c06b4/tests/unit/test_charm.py#L127)), [sdcore-webui checks both that the version is set when it is available, and not set when not](https://github.com/canonical/sdcore-webui-k8s-operator/blob/1a66ad3f623d665657d04ad556139439f4733a28/tests/unit/test_charm.py#L447)


### Write scenario tests

> See first: {ref}`write-scenario-tests-for-a-charm`

To verify the workload version is set using Scenario, retrieve the workload
version from the `State`. In your `tests/scenario/test_charm.py` file, add a
new test that verifies the workload version is set. For example:

```python
def test_workload_version_is_set():
    ctx = scenario.Context(MyCharm, meta={"name": "foo"})
    # Suppose that the charm gets the workload version by running the command
    # `/bin/server --version` in the container. Firstly, we mock that out:
    container = scenario.Container(
        "webserver",
        exec_mock={("/bin/server", "--version"): scenario.ExecOutput(stdout="1.2\n")},
    )
    out = ctx.run('start', scenario.State(containers={ref}`container]))
    assert out.workload_version == "1.2"
```

### Write integration tests

> See first: {ref}`write-integration-tests-for-a-charm`

To verify that setting the workload version works correctly in an integration test, get the status
of the model, and check the `workload_version` attribute of the unit. In your
`tests/integration/test_charm.py` file, after the `test_build_and_deploy` test
that `charmcraft init` provides, add a new test that verifies the workload
version is set. For example:

```python
# `charmcraft init` will provide you with this test.
async def test_build_and_deploy(ops_test: OpsTest):
    # Build and deploy charm from local source folder
    charm = await ops_test.build_charm(".")

    # Deploy the charm and wait for active/idle status
    await asyncio.gather(
        ops_test.model.deploy(charm, application_name=APP_NAME),
        ops_test.model.wait_for_idle(
            apps=[APP_NAME], status="active", raise_on_blocked=True, timeout=1000
        ),
    )

async def test_workload_version_is_set(ops_test: OpsTest):
    # Verify that the workload version has been set.
    status = await ops_test.model.get_status()
    version = status.applications[APP_NAME].units[f"{APP_NAME}/0"].workload_version
    # We'll need to update this version every time we upgrade to a new workload
    # version. If the workload has an API or some other way of getting the
    # version, the test should get it from there and use that to compare to the
    # unit setting.
    assert version == "3.14"
```

<!---
No "see more" link: this is not currently documented in the pylibjuju docs.
-->

> Examples: [synapse checking that the unit's workload version matches the one reported by the server](https://github.com/canonical/synapse-operator/blob/778bcd414644c922373d542a304be14866835516/tests/integration/test_charm.py#L139)

