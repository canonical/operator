# The `ops` library

![CI Status](https://github.com/canonical/operator/actions/workflows/framework-tests.yaml/badge.svg)

The `ops` library is a Python framework for developing and testing Kubernetes and machine [charms](https://charmhub.io/). While charms can be written in any language, `ops` defines the latest standard, and charmers are encouraged to use Python with `ops` for all charms. The library is an official component of the Charm SDK, itself a part of [the Juju universe](https://juju.is/).

> - `ops` is  [available on PyPI](https://pypi.org/project/ops/).
> - The latest version of `ops` requires Python 3.10 or above.
> - Read our [docs](https://documentation.ubuntu.com/ops/latest/) for tutorials, how-to guides, the library reference, and more.

## Give it a try

Let's use `ops` to build a Kubernetes charm:

### Set up

> See [Juju | Set things up](https://documentation.ubuntu.com/juju/3.6/howto/manage-your-juju-deployment/set-up-your-juju-deployment/). <br> Choose the automatic track and MicroK8s.


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

        Learn more about interacting with Pebble at
            https://documentation.ubuntu.com/ops/latest/reference/pebble/
        """
        # Get a reference the container attribute on the PebbleReadyEvent
        container = event.workload
        # Add initial Pebble config layer using the Pebble API
        container.add_layer("httpbin", self._pebble_layer, combine=True)
        # Make Pebble reevaluate its plan, ensuring any services are started if enabled.
        container.replan()
        # Learn more about statuses at
        # https://documentation.ubuntu.com/juju/3.6/reference/status/
        self.unit.status = ops.ActiveStatus()
```

> See more: [`ops.PebbleReadyEvent`](https://documentation.ubuntu.com/ops/latest/reference/ops/#ops.PebbleReadyEvent)

- The `tests/unit/test_charm.py` file imports `ops.testing` and uses it to set up a unit test:

```python
import ops
from ops import testing

from charm import OpsExampleCharm


def test_httpbin_pebble_ready():
    # Arrange:
    ctx = testing.Context(OpsExampleCharm)
    container = testing.Container("httpbin", can_connect=True)
    state_in = testing.State(containers={container})

    # Act:
    state_out = ctx.run(ctx.on.pebble_ready(container), state_in)

    # Assert:
    updated_plan = state_out.get_container(container.name).plan
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
    assert expected_plan == updated_plan
    assert (
        state_out.get_container(container.name).service_statuses["httpbin"]
        == ops.pebble.ServiceStatus.ACTIVE
    )
    assert state_out.unit_status == testing.ActiveStatus()
```

> See more: [`ops.testing`](https://documentation.ubuntu.com/ops/latest/reference/ops-testing/)


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

> See [Juju | Tear things down](https://documentation.ubuntu.com/juju/3.6/howto/manage-your-juju-deployment/tear-down-your-juju-deployment-local-testing-and-development/). <br> Choose the automatic track.

## Next steps

- Read the [docs](https://documentation.ubuntu.com/ops/latest/).
- Read our [Code of conduct](https://ubuntu.com/community/code-of-conduct) and join our [chat](https://matrix.to/#/#charmhub-ops:ubuntu.com) and [forum](https://discourse.charmhub.io/) or [open an issue](https://github.com/canonical/operator/issues).
- Read our [CONTRIBUTING guide](https://github.com/canonical/operator/blob/main/HACKING.md) and contribute!
