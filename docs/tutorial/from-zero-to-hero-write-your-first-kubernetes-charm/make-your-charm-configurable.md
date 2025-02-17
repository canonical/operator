(make-your-charm-configurable)=
# Make your charm configurable

> <small> {ref}`From Zero to Hero: Write your first Kubernetes charm <from-zero-to-hero-write-your-first-kubernetes-charm>` > Make your charm configurable</small>
>
> **See previous: {ref}`Create a minimal Kubernetes charm <create-a-minimal-kubernetes-charm>`** 

````{important}

This document is part of a  series, and we recommend you follow it in sequence.  However, you can also jump straight in by checking out the code from the previous branches:

```text
git clone https://github.com/canonical/juju-sdk-tutorial-k8s.git
cd juju-sdk-tutorial-k8s
git checkout 01_create_minimal_charm
git checkout -b 02_make_your_charm_configurable 
```

````

A charm might have a specific configuration that the charm developer might want to expose to the charm user so that the latter can change specific settings during runtime. 

As a charm developer, it is thus important to know how to make your charm configurable. 

This can be done by defining a charm configuration in a file called `charmcraft.yaml` and then adding configuration event handlers ('hooks') in the `src/charm.py` file. 

In this part of the tutorial you will update your charm to make it possible for a charm user to change the port on which the workload application is available.

## Define the configuration options

To begin with, let's define the options that will be available for configuration. 

In the `charmcraft.yaml` file you created earlier, define a configuration option, as below. The name of your configurable option is going to be `server-port`.  The `default` value is `8000` -- this is the value you're trying to allow a charm user to configure.

```yaml
config:
  options:
    server-port:
      default: 8000
      description: Default port on which FastAPI is available
      type: int
```

## Define the configuration event handlers

Open your `src/charm.py` file.

In the `__init__` function, add an observer for the `config_changed` event and pair it with an `_on_config_changed` handler:

```python
framework.observe(self.on.config_changed, self._on_config_changed)
```

Now, define the handler, as below. First, read the `self.config` attribute to get the new value of the setting. Then, validate that this value is allowed (or block the charm otherwise). Next, let's log the value to the logger. Finally, since configuring something like a port affects the way we call our workload application, we also need to update our Pebble configuration, which we will do via a newly created method `_update_layer_and_restart` that we will define shortly.

```python
def _on_config_changed(self, event: ops.ConfigChangedEvent) -> None:
    port = self.config['server-port']  # See charmcraft.yaml

    if port == 22:
        self.unit.status = ops.BlockedStatus('invalid port number, 22 is reserved for SSH')
        return
    
    logger.debug('New application port is requested: %s', port)
    self._update_layer_and_restart()
```

```{caution}

A charm does not know which configuration option has been changed. Thus, make sure to validate all the values. This is especially important since multiple values can be changed in one call.
```

In the `__init__` function, add a new attribute to define a container object for your workload:

```python
# see 'containers' in charmcraft.yaml
self.container = self.unit.get_container('demo-server')
```

Create a new method, as below. This method will get the current Pebble layer configuration and compare the new and the existing service definitions -- if they differ, it will update the layer and restart the service.

```python
def _update_layer_and_restart(self) -> None:
    """Define and start a workload using the Pebble API.

    You'll need to specify the right entrypoint and environment
    configuration for your specific workload. Tip: you can see the
    standard entrypoint of an existing container using docker inspect
    Learn more about interacting with Pebble at https://juju.is/docs/sdk/pebble
    Learn more about Pebble layers at
        https://canonical-pebble.readthedocs-hosted.com/en/latest/reference/layers
    """

    # Learn more about statuses at:
    # https://canonical-juju.readthedocs-hosted.com/en/latest/user/reference/status/
    self.unit.status = ops.MaintenanceStatus('Assembling Pebble layers')
    try:
        self.container.add_layer('fastapi_demo', self._pebble_layer, combine=True)
        logger.info("Added updated layer 'fastapi_demo' to Pebble plan")

        # Tell Pebble to incorporate the changes, including restarting the
        # service if required.
        self.container.replan()
        logger.info(f"Replanned with '{self.pebble_service_name}' service")

        self.unit.status = ops.ActiveStatus()
    except ops.pebble.APIError:
        self.unit.status = ops.MaintenanceStatus('Waiting for Pebble in workload container')
```

Now, crucially, update the `_pebble_layer` property to make the layer definition dynamic, as shown below. This will replace the static port `8000` with `f"--port={self.config['server-port']}"`.

```python
command = ' '.join(
    [
        'uvicorn',
        'api_demo_server.app:app',
        '--host=0.0.0.0',
        f"--port={self.config['server-port']}",
    ]
)
```

As you may have noticed, the new `_update_layer_and_restart` method looks like a more advanced variant of the existing `_on_demo_server_pebble_ready` method. Remove the body of the `_on_demo_server_pebble_ready` method and replace it a call to `_update_layer_and_restart` like this:

```python
def _on_demo_server_pebble_ready(self, event: ops.PebbleReadyEvent) -> None:
    self._update_layer_and_restart()
```

## Validate your charm

First, repack and refresh your charm:

```text
charmcraft pack
juju refresh \
  --path="./demo-api-charm_ubuntu-22.04-amd64.charm" \
  demo-api-charm --force-units --resource \
  demo-server-image=ghcr.io/canonical/api_demo_server:1.0.1
```

Now, check the available configuration options:

```text
juju config demo-api-charm
```

Our newly defined `server-port` option is there. Let's try to configure it to something else, e.g., `5000`:

```text
juju config demo-api-charm server-port=5000
```

Now, let's validate that the app is actually running and reachable on the new port by sending the HTTP  request below, where `10.1.157.74` is the IP of our pod and `5000` is the new application port:

```text
curl 10.1.157.74:5000/version
```
 
You should see JSON string with the version of the application: `{"version":"1.0.0"}`

Let's also verify that our invalid port number check works by setting the port to `22` and then running `juju status`:

```text
juju config demo-api-charm server-port=22
juju status
```

As expected, the application is indeed in the `blocked` state: 

```text
Model        Controller           Cloud/Region        Version  SLA          Timestamp
charm-model  tutorial-controller  microk8s/localhost  3.0.0    unsupported  18:19:24+01:00

App             Version  Status   Scale  Charm           Channel  Rev  Address         Exposed  Message
demo-api-charm           blocked      1  demo-api-charm             2  10.152.183.215  no       invalid port number, 22 is reserved for SSH

Unit               Workload  Agent  Address      Ports  Message
demo-api-charm/0*  blocked   idle   10.1.157.74         invalid port number, 22 is reserved for SSH
```

Congratulations, you now know how to make your charm configurable!

## Review the final code

For the full code see: [02_make_your_charm_configurable](https://github.com/canonical/juju-sdk-tutorial-k8s/tree/02_make_your_charm_configurable)

For a comparative view of the code before and after this doc see: [Comparison](https://github.com/canonical/juju-sdk-tutorial-k8s/compare/01_create_minimal_charm...02_make_your_charm_configurable)

> **See next: {ref}`Integrate your charm with PostgreSQL <integrate-your-charm-with-postgresql>`**
