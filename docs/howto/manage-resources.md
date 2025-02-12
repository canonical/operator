(manage-resources)=
# How to manage resources

> See also: {external+juju:ref}`Juju | Charm resource <charm-resource>`, {external+juju:ref}`Juju | Manage charm resources <manage-charm-resources>`, {external+charmcraft:ref}`Charmcraft | Manage resources <manage-resources>`

## Implement the feature

<!--COMMENT: MOVE TO HOW TO UPLOAD 
Because resources are defined in a charm’s `charmcraft.yaml`, they are intrinsically linked to a charm. As such, there is no need to register them separately in Charmhub. Other charms may have resources with the same name, but this is not a problem; references to resources always contain the charm name and resource name.
-->

In your charm's `src/charm.py` file, use `ops` to fetch the path to the resource and then manipulate it as needed.

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
        resource_path = self.model.resources.fetch("my-resource")
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
            "Resource 'my-resource' not found; "
            "did you forget to declare it in charmcraft.yaml?"
        )
        logger.error(e)
        return

    # Open the file and read it
    with open(resource_path, "r") as f:
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
