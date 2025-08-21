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

> See more: [](ops.StartEvent)

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

> See more: [](ops.Unit.set_workload_version)

> Examples: [`jenkins-k8s` sets the workload version after getting it from the Jenkins package](https://github.com/canonical/jenkins-k8s-operator/blob/29e9b652714bd8314198965c41a60f5755dd381c/src/charm.py#L115), [`discourse-k8s` sets the workload version after getting it via an exec call](https://github.com/canonical/discourse-k8s-operator/blob/f523b29f909c69da7b9510b581dfcc2309698222/src/charm.py#L581), [`synapse` sets the workload version after getting it via an API call](https://github.com/canonical/synapse-operator/blob/778bcd414644c922373d542a304be14866835516/src/charm.py#L265)

### Write unit tests

> See first: {ref}`write-unit-tests-for-a-charm`

To verify the workload version is set in a unit test, retrieve the workload
version from the `State`. In your `tests/unit/test_charm.py` file, add a
new test that verifies the workload version is set. For example:

```python
from ops import testing

def test_workload_version_is_set():
    ctx = testing.Context(MyCharm)
    # Suppose that the charm gets the workload version by running the command
    # `/bin/server --version` in the container. Firstly, we mock that out:
    container = testing.Container(
        "webserver",
        execs={testing.Exec(["/bin/server", "--version"], stdout="1.2\n")},
    )
    out = ctx.run(ctx.on.start(), testing.State(containers={container}))
    assert out.workload_version == "1.2"
```

### Write integration tests

> See first: {ref}`write-integration-tests-for-a-charm`

To verify that setting the workload version works correctly in an integration test, get the status
of the model, and check the `workload_version` attribute of the unit. In your
`tests/integration/test_charm.py` file, replace the `test_build_and_deploy` test
that `charmcraft init` provides, and add a new test that verifies the workload
version is set. For example:

```python
def test_build_and_deploy(charm: Path, juju: jubilant.Juju):
    """Build the charm-under-test and deploy it."""
    juju.deploy(f'./{charm}')
    juju.wait(jubilant.all_active)


def test_workload_version_is_set(juju: jubilant.Juju):
    # Verify that the workload version has been set.
    version = juju.status().apps["your-app"].units["your-app/0"].workload_status.version
    # We'll need to update this version every time we upgrade to a new workload
    # version. If the workload has an API or some other way of getting the
    # version, the test should get it from there and use that to compare to the
    # unit setting.
    assert version == "3.14"
```

> See more: [](jubilant.Juju.status)
