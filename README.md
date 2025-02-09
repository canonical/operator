# The `ops` library

![CI Status](https://github.com/canonical/operator/actions/workflows/framework-tests.yaml/badge.svg)

The `ops` library is a Python framework for developing and testing Kubernetes and machine [charms](https://juju.is/docs/sdk/charmed-operators). While charms can be written in any language, `ops` defines the latest standard, and charmers are encouraged to use Python with `ops` for all charms. The library is an official component of the Charm SDK, itself a part of [the Juju universe](https://juju.is/).

> - `ops` is  [available on PyPI](https://pypi.org/project/ops/).
> - The latest version of `ops` requires Python 3.8 or above.

## Give it a try

Let's use `ops` to build a Kubernetes charm:

### Set up

> See [Juju | Set things up](https://canonical-juju.readthedocs-hosted.com/en/latest/user/howto/manage-your-deployment/manage-your-deployment-environment/#set-things-up). <br> Choose the automatic track and MicroK8s.


### Write your charm

On your Multipass VM, create a charm directory and use Charmcraft to initialise your charm file structure:

```shell-script
mkdir ops-example
cd ops-example
charmcraft init
```
This has created a standard charm directory structure:

```shell-script
$ ls -R
.:
CONTRIBUTING.md  README.md        pyproject.toml    src    tox.ini
LICENSE          charmcraft.yaml  requirements.txt  tests

./src:
charm.py

./tests:
integration  unit

./tests/integration:
test_charm.py

./tests/unit:
test_charm.py
```

Things to note:

- The `charmcraft.yaml` file shows that what we have is an example charm called `ops-example`, which uses an OCI image resource `httpbin` from `kennethreitz/httpbin`.

- The `requirements.txt` file lists the version of `ops` to use.

- The `src/charm.py` file imports `ops` and uses `ops` constructs to create a charm class `OpsExampleCharm`, observe Juju events, and pair them to event handlers:

```python
import ops

class OpsExampleCharm(ops.CharmBase):
    """Charm the service."""

    def __init__(self, *args):
        super().__init__(*args)
        self.framework.observe(self.on['httpbin'].pebble_ready, self._on_httpbin_pebble_ready)
        self.framework.observe(self.on.config_changed, self._on_config_changed)

    def _on_httpbin_pebble_ready(self, event: ops.PebbleReadyEvent):
        """Define and start a workload using the Pebble API.

        Change this example to suit your needs. You'll need to specify the right entrypoint and
        environment configuration for your specific workload.

        Learn more about interacting with Pebble at at https://juju.is/docs/sdk/pebble.
        """
        # Get a reference the container attribute on the PebbleReadyEvent
        container = event.workload
        # Add initial Pebble config layer using the Pebble API
        container.add_layer("httpbin", self._pebble_layer, combine=True)
        # Make Pebble reevaluate its plan, ensuring any services are started if enabled.
        container.replan()
        # Learn more about statuses in the SDK docs:
        # https://juju.is/docs/sdk/constructs#heading--statuses
        self.unit.status = ops.ActiveStatus()
```

> See more: [`ops.PebbleReadyEvent`](https://ops.readthedocs.io/en/latest/index.html#ops.PebbleReadyEvent)

- The `tests/unit/test_charm.py` file imports `ops.testing` and uses it to set up a testing harness:

```python
import ops.testing

class TestCharm(unittest.TestCase):
    def setUp(self):
        self.harness = ops.testing.Harness(OpsExampleCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()

    def test_httpbin_pebble_ready(self):
        # Expected plan after Pebble ready with default config
        expected_plan = {
            "services": {
                "httpbin": {
                    "override": "replace",
                    "summary": "httpbin",
                    "command": "gunicorn -b 0.0.0.0:80 httpbin:app -k gevent",
                    "startup": "enabled",
                    "environment": {"GUNICORN_CMD_ARGS": "--log-level info"},
                }
            },
        }
        # Simulate the container coming up and emission of pebble-ready event
        self.harness.container_pebble_ready("httpbin")
        # Get the plan now we've run PebbleReady
        updated_plan = self.harness.get_container_pebble_plan("httpbin").to_dict()
        # Check we've got the plan we expected
        self.assertEqual(expected_plan, updated_plan)
        # Check the service was started
        service = self.harness.model.unit.get_container("httpbin").get_service("httpbin")
        self.assertTrue(service.is_running())
        # Ensure we set an ActiveStatus with no message
        self.assertEqual(self.harness.model.unit.status, ops.ActiveStatus())
```

> See more: [`ops.testing.Harness`](https://ops.readthedocs.io/en/latest/#ops.testing.Harness)


Explore further, start editing the files, or skip ahead and pack the charm:

```shell-script
charmcraft pack
```

If you didn't take any wrong turn or simply left the charm exactly as it was, this has created a file called `ops-example_ubuntu-22.04-amd64.charm` (the architecture bit may be different depending on your system's architecture). Use this name and the resource from the `metadata.yaml` to deploy your example charm to your local MicroK8s cloud:

```shell-script
juju deploy ./ops-example_ubuntu-22.04-amd64.charm --resource httpbin-image=kennethreitz/httpbin
```

Congratulations, you’ve just built your first Kubernetes charm using `ops`!

### Clean up

> See [Juju | Tear things down](https://canonical-juju.readthedocs-hosted.com/en/latest/user/howto/manage-your-deployment/manage-your-deployment-environment/#tear-things-down). <br> Choose the automatic track.

## Next steps

- Read the [docs](https://ops.readthedocs.io/en/latest/).
- Read our [Code of conduct](https://ubuntu.com/community/code-of-conduct) and join our [chat](https://matrix.to/#/#charmhub-ops:ubuntu.com) and [forum](https://discourse.charmhub.io/) or [open an issue](https://github.com/canonical/operator/issues).
- Read our [CONTRIBUTING guide](https://github.com/canonical/operator/blob/main/HACKING.md) and contribute!
