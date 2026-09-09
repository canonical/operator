(manage-resources)=
# How to manage resources

See also:

- {external+juju:ref}`Juju | Charm resource <charm-resource>`
- {external+juju:ref}`Juju | Manage charm resources <manage-charm-resources>`
- {external+charmcraft:ref}`Charmcraft | Manage resources <manage-resources>`

## Implement the feature

A charm can require file or oci-image resources, defined in charmcraft.yaml. You'll upload the resources to Charmhub as one of the charm publishing steps. Then when a user deploys your charm from Charmhub, the resources will be available to your charm code.

For example, suppose your `charmcraft.yaml` file contains this simple resource definition:

```yaml
resources:
  my-resource:
    type: file
    filename: somefile.txt
    description: test resource
```

In your charm's `src/charm.py` you can now use [`Model.resources.fetch(<resource_name>)`](ops.Resources.fetch) to get the path to the resource, then manipulate it as needed. For example:

```python
import logging

import ops

logger = logging.getLogger(__name__)


class MyCharm(ops.CharmBase):
    def _on_config_changed(self, event: ops.ConfigChangedEvent):
        # Get the path to the file resource named 'my-resource'.
        try:
            resource_path = self.model.resources.fetch('my-resource')
        except NameError:
            logger.exception('Resource my-resource is not declared.')
            self.unit.status = ops.BlockedStatus(
                "Resource 'my-resource' not found; did you forget to "
                'declare it in charmcraft.yaml?'
            )
            return
        except ops.ModelError:
            logger.exception('Could not claim resource my-resource.')
            self.unit.status = ops.BlockedStatus(
                "Could not claim resource 'my-resource'; run "
                '`juju debug-log` for more information'
            )
            return

        with resource_path.open() as f:
            content = f.read()
        # Do something with the content.
```

[`fetch()`](ops.Resources.fetch) raises [`NameError`](https://docs.python.org/3/library/exceptions.html#NameError) if the resource isn't declared in `charmcraft.yaml`, and [`ops.ModelError`](ops.ModelError) if it is declared but Juju can't provide it. Otherwise it returns a [`pathlib.Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path) pointing at the resource.

During development it's often useful to specify the resource at deploy time, so that you can test a change without publishing a new charm or resource for every minor fix. In the snippet below, we create a file with some text content and pass it to the Juju controller to use in place of any published `my-resource` resource:

```text
echo "TEST" > /tmp/somefile.txt
charmcraft pack
juju deploy ./my-charm.charm --resource my-resource=/tmp/somefile.txt
```

## Test the feature

### Write unit tests

See first: {ref}`write-unit-tests-for-a-charm`

If your charm needs access to a resource, make it available with [`ops.testing.State.resources`](ops.testing.State.resources), passing an [`ops.testing.Resource`](ops.testing.Resource) for each one. For example, to make the `my-resource` file resource available:

```python
import pathlib

from ops import testing

ctx = testing.Context(
    MyCharm,
    meta={
        'name': 'julie',
        'resources': {'my-resource': {'type': 'file'}},
    },
)
resource = testing.Resource(name='my-resource', path='/path/to/somefile.txt')
with ctx(ctx.on.start(), testing.State(resources={resource})) as mgr:
    path = mgr.charm.model.resources.fetch('my-resource')
    assert path == pathlib.Path('/path/to/somefile.txt')
```

(manage-resources-integration-tests)=
### Write integration tests

See first: {ref}`write-integration-tests-for-a-charm`

During development and testing, it's useful to specify resource locations when deploying the charm.

The conventional place to specify resource locations for testing is the `upstream-source` field in `charmcraft.yaml`'s `resources` section:

```{include} /reuse/manage-resources-integration-test-example.md
```

See also: [](jubilant.Juju.deploy)

Examples: [`valkey-operator`](https://github.com/canonical/valkey-operator/blob/9/edge/tests/integration/test_charm.py), [`kafka-k8s-operator`](https://github.com/canonical/kafka-k8s-operator/blob/main/tests/integration/test_balancer.py)

We recommend including the `charm` fixture (even though it's not used) so that the test fails immediately if a `.charm` file isn't available.
