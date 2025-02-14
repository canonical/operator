(manage-configurations)=
# Manage configurations
> See first: {external+juju:ref}`Juju | <application-configuration>`, {external+juju:ref}`Juju | Manage applications > Configure <configure-an-application>`, {external+charmcraft:ref}`Charmcraft | Manage configurations <manage-configurations>`


## Implement the feature

### Define a configuration option

In the `charmcraft.yaml` file of the charm, under `config.options`, add a configuration definition, including a name, a description, the type, and the default value. The example below shows how to define two configuration options, one called `name` of type `string` and default value `Wiki`, and one called `skin` with type `string` and default value `vector`:

```text
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

### Observe the `config-changed` event and define the event handler

In the `src/charm.py` file of the charm project, in the `__init__` function of the charm, set up an observer for the config changed event and pair that with an event handler:

```python
self.framework.observe(self.on.config_changed, self._on_config_changed)
```

Then, in the body of the charm definition, define the event handler. Here you may want to read the current configuration value, validate it (Juju only checks that the *type* is valid), and log it, among other things. Sample code for an option called `server-port`, with type `int`, and default value `8000`:

 ```python
def _on_config_changed(self, event):
    port = self.config["server-port"] 

    if port == 22:
        self.unit.status = ops.BlockedStatus("invalid port number, 22 is reserved for SSH")
        return
    
    logger.debug("New application port is requested: %s", port)
    self._update_layer_and_restart(None)
```

> See more: [](ops.CharmBase.config)

```{caution}

 - Multiple configuration values can be changed at one time through Juju, resulting in only one `config_changed` event. Thus, your charm code must be able to process more than one config value changing at a time.
- If `juju config` is run with values the same as the current configuration, the  `config_changed` event will not run. Therefore, if you have a single config value, there is no point in tracking its previous value -- the event will only be triggered if the value changes.
- Configuration cannot be changed from within the charm code. Charms, by design, aren't able to mutate their own configuration by themselves (e.g., in order to ignore an admin-provided configuration), or to configure other applications. In Ops, one typically interacts with config via a read-only facade.
```

### (If applicable) Update and restart the Pebble layer

**If your charm is a Kubernetes charm and the config affects the workload:** Update the Pebble layer to fetch the current configuration value and then restart the Pebble layer. 

<!--Example: The _update_layer_and_restart bit in the charm constructor and then in the body of the charm definition
https://github.com/canonical/juju-sdk-tutorial-k8s/compare/01_create_minimal_charm...02_make_your_charm_configurable
-->

## Test the feature

> See first: {ref}`get-started-with-charm-testing`

### Write unit tests

> See first: {ref}`write-unit-tests-for-a-charm`

To verify that the `config-changed` event validates the port, pass the new config to the `State`, and, after running the event, check the unit status. For example, in your `tests/unit/test_charm.py` file, add the following test function:

```python
from ops import testing

def test_open_port():
    ctx = testing.Context(MyCharm)

    state_out = ctx.run(ctx.on.config_changed(), testing.State(config={"server-port": 22}))

    assert isinstance(state_out.unit_status, testingZ.BlockedStatus)
```

### Manually test

To verify that the configuration option works as intended, pack your charm, update it in the Juju model, and run `juju config` followed by the name of the application deployed by your charm and then your newly defined configuration option key set to some value. For example, given the `server-port` key defined above, you could try:

```text
juju config <name of application deployed by your charm> server-port=4000
```
