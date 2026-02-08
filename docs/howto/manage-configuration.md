(manage-configuration)=
# How to manage configuration
> See first: {external+juju:ref}`Juju | <application-configuration>`, {external+juju:ref}`Juju | Manage applications > Configure <configure-an-application>`, {external+charmcraft:ref}`Charmcraft | Manage the app configuration <manage-the-app-configuration>`


## Implement the feature

(define-a-configuration-option)=
### Define a configuration option

In the `charmcraft.yaml` file of the charm, under `config.options`, add a configuration definition, including a name, a description, the type, and the default value.

```{admonition} Best practice
:class: hint

Don't duplicate model-level configuration options that are controlled by {external+juju:ref}`juju model-config <command-juju-model-config>`.
```

The example below shows how to define two configuration options, one called `name` of type `string` and default value `Wiki`, and one called `skin` with type `string` and default value `vector`:

```yaml
config:
  options:
    name:
      default: Wiki
      description: The name, or Title of the Wiki
      type: string
    skin:
      default: vector
      description: skin for the Wiki
      type: string
```

In the `src/charm.py` file of the charm, add a class that mirrors the
configuration from `charmcraft.yaml`. This lets your static type checker and
IDE know what Python type the options should be, and provides a place to do
additional validation. Using the example from above:

```python
class WikiConfig(pydantic.BaseModel):
    name: str = pydantic.Field('Wiki')
    skin: str = pydantic.Field('vector')

    @pydantic.validator('name')
    def validate_name(cls, value):
        if len(value) < 4:
            raise ValueError('Name must be at least 4 characters long')
        if " " in value:
            raise ValueError('Name must not contain spaces')
        return value
```

### Observe the `config-changed` event and define the event handler

In the `src/charm.py` file of the charm project, in the `__init__` function of the charm, set up an observer for the config changed event and pair that with an event handler:

```python
self.framework.observe(self.on.config_changed, self._on_config_changed)
```

Also in the `__init__` function, load the config into the config class that you
defined. Pass `errors='blocked'` to have the charm exit after setting a blocked
status if the configuration doesn't validate against the class you defined. The
default is `errors='raise'`, which means that the charm is responsible for
catching any `ValueError` raised.

```python
self.typed_config = self.load_config(WikiConfig, errors='blocked')
```

Then, in the body of the charm definition, define the event handler.

```python
def _on_config_changed(self, event: ops.ConfigChangedEvent):
    name = self.typed_config.name
    existing_name = self.get_wiki_name()
    if name == existing_name:
        # Nothing to do.
        return
    logger.info('Changing wiki name to %s', name)
    self.set_wiki_name(name)
```

> See more: [](ops.CharmBase.load_config), [](ops.CharmBase.config)

```{caution}

 - Multiple configuration values can be changed at one time through Juju, resulting in only one `config_changed` event. Thus, your charm code must be able to process more than one config value changing at a time.
- If `juju config` is run with values the same as the current configuration, the  `config_changed` event will not run. Therefore, if you have a single config value, there is no point in tracking its previous value -- the event will only be triggered if the value changes.
- Configuration cannot be changed from within the charm code. Charms, by design, aren't able to mutate their own configuration by themselves (e.g., in order to ignore an admin-provided configuration), or to configure other applications. In Ops, one typically interacts with config via a read-only facade.
```

### Write unit tests

> See first: {ref}`write-unit-tests-for-a-charm`

To verify that the `config-changed` event validates the port, pass the new config to the `State`, and, after running the event, check the unit status. For example, in your `tests/unit/test_charm.py` file, add the following test function:

```python
from ops import testing

def test_short_wiki_name():
    ctx = testing.Context(MyCharm)

    state_out = ctx.run(ctx.on.config_changed(), testing.State(config={'name': 'ww'}))

    assert isinstance(state_out.unit_status, testing.BlockedStatus)
```

### Manually test

To verify that the configuration option works as intended, pack your charm, update it in the Juju model, and run `juju config` followed by the name of the application deployed by your charm and then your newly defined configuration option key set to some value. For example, given the `name` key defined above, you could try:

```text
juju config <name of application deployed by your charm> name=charming-wiki
```
