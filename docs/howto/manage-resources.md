(manage-resources)=
# How to manage resources

> See also: {external+juju:ref}`Juju | Charm resource <charm-resource>`, {external+juju:ref}`Juju | Manage charm resources <manage-charm-resources>`, {external+charmcraft:ref}`Charmcraft | Manage resources <manage-resources>`

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
# ...
import logging
import ops

# ...
logger = logging.getLogger(__name__)


def _on_config_changed(self, event):
    # Get the path to the file resource named 'my-resource'
    try:
        resource_path = self.model.resources.fetch('my-resource')
    except ops.ModelError as e:
        self.unit.status = ops.BlockedStatus(
            "Something went wrong when claiming resource 'my-resource; "
            "run `juju debug-log` for more info'"
        )
        # might actually be worth it to just reraise this exception and let the charm error out;
        # depends on whether we can recover from this.
        logger.error(e)
        return
    except NameError as e:
        self.unit.status = ops.BlockedStatus(
            "Resource 'my-resource' not found; did you forget to declare it in charmcraft.yaml?"
        )
        logger.error(e)
        return

    # Open the file and read it
    with open(resource_path, 'r') as f:
        content = f.read()
    # do something
```

The [`fetch()`](ops.Resources.fetch) method will raise a [`NameError`](https://docs.python.org/3/library/exceptions.html#NameError) if the resource does not exist, and returns a Python [`Path`](https://docs.python.org/3/library/pathlib.html#pathlib.Path) object to the resource if it does.

Note: During development, it may be useful to specify the resource at deploy time to facilitate faster testing without the need to publish a new charm/resource in between minor fixes. In the below snippet, we create a simple file with some text content, and pass it to the Juju controller to use in place of any published `my-resource` resource:

```text
echo "TEST" > /tmp/somefile.txt
charmcraft pack
juju deploy ./my-charm.charm --resource my-resource=/tmp/somefile.txt
```

## Test the feature

### Write unit tests

> See first: {ref}`write-unit-tests-for-a-charm`

If your charm requires access to resources, you can make them available to it
through ``State.resources``. For example, to make a ``foo`` resource that is a
path to an OCI image available:

```python
import pathlib

from ops import testing

ctx = testing.Context(
    MyCharm, meta={'name': 'julie', 'resources': {'foo': {'type': 'oci-image'}}}
)
resource = testing.Resource(name='foo', path='/path/to/resource.tar')
with ctx(ctx.on.start(), testing.State(resources={resource})) as mgr:
    path = mgr.charm.model.resources.fetch('foo')
    assert path == pathlib.Path('/path/to/resource.tar')
```

(manage-resources-integration-tests)=
### Write integration tests

> See first: {ref}`write-integration-tests-for-a-charm`

During development and testing, it's useful to specify resource locations when deploying the charm.

The conventional place to specify resource locations for testing is the `upstream-source` field in `charmcraft.yaml`'s `resources` section:

```{include} /reuse/manage-resources-integration-test-example.md
```

See also: [](jubilant.Juju.deploy)

Examples: [`valkey-operator`](https://github.com/canonical/valkey-operator/blob/9/edge/tests/integration/test_charm.py), [`kafka-k8s-operator`](https://github.com/canonical/kafka-k8s-operator/blob/main/tests/integration/test_balancer.py)

We recommend including the `charm` fixture (even though it's not used) so that the test fails immediately if a `.charm` file isn't available.
