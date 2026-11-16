(manage-resources)=
# How to manage resources

See first:

- {external+juju:ref}`Juju | Charm resource <charm-resource>`
- {external+juju:ref}`Juju | Manage charm resources <manage-charm-resources>`
- {external+charmcraft:ref}`Charmcraft | Manage resources <manage-resources>`

A resource is a file or an OCI image that Juju provides to your charm, separately from the charm itself. You and your charm's users can change a resource without releasing a new revision of the charm.

Use a file resource for content that's large, or that changes on a different schedule from the charm. For example, a workload binary or a data set. Kubernetes charms use an OCI image resource for each workload container.

## Declare a resource

Declare each resource under the `resources` key in your charm's `charmcraft.yaml` file. Give each resource a name, a type, and a description.

See more: {external+charmcraft:ref}`Charmcraft | charmcraft.yaml > resources <charmcraft-yaml-key-resources>`

### Declare a file resource

A file resource also needs a `filename`. Juju saves the resource on the unit with this filename. The filename can't contain `/`. For example:

```yaml
resources:
  my-resource:
    type: file
    filename: config.tar.gz
    description: Configuration bundle for the workload.
```

### Declare an OCI image resource

In a Kubernetes charm, declare an `oci-image` resource for each workload container, and refer to it from the container's `resource` key. For example:

```yaml
containers:
  webserver:
    resource: webserver-image

resources:
  webserver-image:
    type: oci-image
    description: OCI image for the web server.
    upstream-source: docker.io/library/nginx:1.29
```

Charmcraft and Juju ignore `upstream-source`. It's a convention that records where the image comes from. The integration tests that `charmcraft init` creates for a Kubernetes charm read it to deploy the charm.

See more: {ref}`workload-containers`

## Use a file resource

In your charm code, call [`self.model.resources.fetch()`](ops.Resources.fetch) with the name of the resource. The first time a unit fetches a resource, Juju downloads it from the controller, so a large resource can take some time. `fetch()` returns a [`pathlib.Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path) to a file on the unit with the name that you set in `filename`.

If Juju can't provide the resource, `fetch()` raises [`ops.ModelError`](ops.ModelError). This happens if a user deploys a local charm without providing the resource. Handle the error by setting a blocked status that tells the user what to do. For example, in your `src/charm.py` file:

```python
import logging
import pathlib

import ops

logger = logging.getLogger(__name__)


class MyCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on.install, self._reconcile)
        framework.observe(self.on.upgrade_charm, self._reconcile)
        framework.observe(self.on.config_changed, self._reconcile)

    def _reconcile(self, event: ops.EventBase):
        try:
            resource_path = self.model.resources.fetch('my-resource')
        except ops.ModelError:
            logger.exception("Could not fetch resource 'my-resource'.")
            self.unit.status = ops.BlockedStatus(
                "Resource 'my-resource' is missing; attach it with "
                '`juju attach-resource`'
            )
            return
        self._install_config(resource_path)
        self.unit.status = ops.ActiveStatus()

    def _install_config(self, path: pathlib.Path):
        # Unpack the configuration bundle for the workload.
        ...
```

`fetch()` raises [`NameError`](https://docs.python.org/3/library/exceptions.html#NameError) if the name isn't declared in `charmcraft.yaml`. That's a bug in the charm, so don't catch it. Your unit tests will find it.

In this example, `_reconcile` is a holistic event handler. To learn more about the different approaches to handling events, see {ref}`holistic-vs-delta-charms`.

## Use an OCI image resource

Your charm doesn't fetch an OCI image resource. Juju creates each workload container from the image in the container's resource. Your charm then manages the workload in the container with Pebble.

See more: {ref}`workload-containers`

## Respond when a resource changes

When a user attaches a resource with new content, Juju triggers an [`upgrade-charm`](ops.UpgradeCharmEvent) event on each unit. Juju triggers the same event when a user refreshes the charm. Observe `upgrade_charm` and fetch the resource again, as `_reconcile` does in the example above.

If the new content is the same as the current content, Juju doesn't trigger an event.

## Provide resources when you deploy

When a user deploys your charm from Charmhub, Juju uses the resource revisions that are released with the charm in that channel. When you deploy a local charm file, provide each resource yourself with `--resource`.

### Deploy a local charm

For a file resource, provide a path to a local file. For an OCI image resource, provide an image reference, or a path to a JSON or YAML file with the image reference and registry credentials. For example:

```text
charmcraft pack
juju deploy ./my-charm_amd64.charm \
    --resource my-resource=./config.tar.gz \
    --resource webserver-image=docker.io/library/nginx:1.29
```

On a Kubernetes model, `juju deploy` fails for a local charm unless you provide every OCI image resource. Juju doesn't check file resources at deploy time. If you leave out a file resource, the charm gets `ops.ModelError` when it fetches the resource.

See more: {external+juju:ref}`Juju | juju deploy <command-juju-deploy>`

### Change a resource after deploying

To give a deployed application a new file, or a different image, use `juju attach-resource`:

```text
juju attach-resource my-charm my-resource=./config.tar.gz
```

For an application deployed from Charmhub, use `juju refresh` with a revision number to switch to a different resource revision:

```text
juju refresh my-charm --resource my-resource=3
```

`juju refresh` also accepts a path or an image reference, in the same way as `juju deploy`.

See more:

- {external+juju:ref}`Juju | juju attach-resource <command-juju-attach-resource>`
- {external+juju:ref}`Juju | juju refresh <command-juju-refresh>`

### Check which resources an application uses

```text
juju resources my-charm
```

For a resource from Charmhub, the output shows the revision number. For a resource that a user provided, the output shows when it was uploaded. To see the resources that each unit is using, add `--details`.

See more: {external+juju:ref}`Juju | juju resources <command-juju-resources>`

## Publish resources on Charmhub

Upload your charm to Charmhub before you upload its resources. Charmhub accepts a resource only if it's declared in a charm revision that you've already uploaded.

Upload a file resource with `--filepath`, and an OCI image resource with `--image`. Each upload creates a new revision of the resource. For example:

```text
charmcraft upload-resource my-charm my-resource --filepath=./config.tar.gz
charmcraft upload-resource my-charm webserver-image \
    --image=docker://docker.io/library/nginx:1.29
```

`--image` also accepts a local OCI archive file, such as a rock.

Then release the charm revision together with the resource revisions that it should use:

```text
charmcraft release my-charm --revision=14 --channel=edge \
    --resource=my-resource:2 --resource=webserver-image:5
```

To see the resources and resource revisions on Charmhub, use `charmcraft resources` and `charmcraft resource-revisions`.

See more:

- {external+charmcraft:ref}`Charmcraft | Publish a resource on Charmhub <publish-a-resource>`
- {external+charmcraft:ref}`Charmcraft | upload-resource <ref_commands_upload-resource>`
- {ref}`publish-your-charm`

## Test the feature

### Write unit tests

See first: {ref}`write-unit-tests-for-a-charm`

To give your charm a resource, pass an [`ops.testing.Resource`](ops.testing.Resource) in [`State.resources`](ops.testing.State.resources). The path is a file on your machine that your charm receives from `fetch()`. For example, in your `tests/unit/test_charm.py` file:

```python
import pathlib

from ops import testing

from charm import MyCharm


def test_resource_attached(tmp_path: pathlib.Path):
    config = tmp_path / 'config.tar.gz'
    config.write_bytes(b'')
    ctx = testing.Context(MyCharm)
    resource = testing.Resource(name='my-resource', path=config)
    state_in = testing.State(resources={resource})

    state_out = ctx.run(ctx.on.install(), state_in)

    assert state_out.unit_status == testing.ActiveStatus()
```

If you leave a declared resource out of `State.resources`, `ops.testing` treats the state as inconsistent and raises an error. It doesn't raise `ops.ModelError`. To test how your charm handles a missing resource, patch `fetch()` to raise `ops.ModelError`. For example:

```python
import ops
import pytest
from ops import testing

from charm import MyCharm


def test_resource_missing(monkeypatch: pytest.MonkeyPatch):
    def fetch(self: ops.Resources, name: str):
        raise ops.ModelError(f'could not download resource: {name}')

    monkeypatch.setattr(ops.Resources, 'fetch', fetch)
    ctx = testing.Context(MyCharm)

    state_out = ctx.run(ctx.on.install(), testing.State())

    assert isinstance(state_out.unit_status, testing.BlockedStatus)
```

(manage-resources-integration-tests)=
### Write integration tests

See first: {ref}`write-integration-tests-for-a-charm`

Pass resources to [`Juju.deploy`](jubilant.Juju.deploy) with the `resources` argument. Each value is a path, an image reference, or a revision number, as with `juju deploy --resource`.

For a Kubernetes charm, the conventional place for the test image is the `upstream-source` field of each OCI image resource. For example:

```{include} /reuse/manage-resources-integration-test-example.md
```

For a file resource, keep a test file with your tests. For example:

```python
import pathlib

import jubilant
import pytest

RESOURCE = pathlib.Path(__file__).parent / 'config.tar.gz'


@pytest.mark.juju_setup
def test_deploy(charm: pathlib.Path, juju: jubilant.Juju):
    juju.deploy(charm, resources={'my-resource': str(RESOURCE)})
    juju.wait(jubilant.all_active)
```

To test how your charm responds when the resource changes, pass new resources to [`Juju.refresh`](jubilant.Juju.refresh). Use `path` to refresh with the same charm file:

```python
def test_resource_changed(charm: pathlib.Path, juju: jubilant.Juju):
    new_resource = pathlib.Path(__file__).parent / 'new-config.tar.gz'
    juju.refresh(
        'my-charm', path=charm, resources={'my-resource': str(new_resource)}
    )
    juju.wait(jubilant.all_active)
```

We recommend including the `charm` fixture in each test that deploys, so that the test fails immediately if a `.charm` file isn't available.

Examples: [`valkey-operator`](https://github.com/canonical/valkey-operator/blob/9/edge/tests/integration/test_charm.py), [`kafka-k8s-operator`](https://github.com/canonical/kafka-k8s-operator/blob/main/tests/integration/test_balancer.py)
