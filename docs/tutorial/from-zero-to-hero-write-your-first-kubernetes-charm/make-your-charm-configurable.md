(make-your-charm-configurable)=
# Make your charm configurable

> <small> {ref}`From Zero to Hero: Write your first Kubernetes charm <from-zero-to-hero-write-your-first-kubernetes-charm>` > Make your charm configurable</small>
>
> **See previous: {ref}`Create a minimal Kubernetes charm <create-a-minimal-kubernetes-charm>`**

````{important}

This document is part of a  series, and we recommend you follow it in sequence.  However, you can also jump straight in by checking out the code from the previous chapter:

```text
git clone https://github.com/canonical/operator.git
cd operator/examples/k8s-1-minimal
```

````

A charm might have a specific configuration that the charm developer might want to expose to the charm user so that the latter can change specific settings during runtime.

As a charm developer, it is thus important to know how to make your charm configurable.

This can be done by defining a charm configuration in a file called `charmcraft.yaml` and then adding configuration event handlers ('hooks') in the `src/charm.py` file.

In this part of the tutorial you will update your charm to make it possible for a charm user to change the port on which the workload application is available.

## Define the configuration option

To begin with, let's define the option that will be available for configuration.

In `charmcraft.yaml`, replace the `config` block with:

```{literalinclude} ../../../examples/k8s-2-configurable/charmcraft.yaml
:language: yaml
:start-at: 'config:'
:end-at: 'type: int'
```

This defines a configuration option called `server-port`. The `default` value is `8000` -- this is the value you're trying to allow a charm user to configure.

## Define a configuration class

Open your `src/charm.py` file, and add a configuration class that matches the configuration you added in `charmcraft.yaml`:

```{literalinclude} ../../../examples/k8s-2-configurable/src/charm.py
:language: python
:pyobject: FastAPIConfig
```

Then, still in `src/charm.py`, add `import dataclasses` in the imports at the top of the file.

We'll use [](CharmBase.load_config) to create an instance of your config class from the Juju config data. This allows IDEs to provide hints when we are accessing the configuration, and static type checkers are able to validate that we are using the config option correctly.

## Define the configuration event handlers

Open your `src/charm.py` file.

In the `__init__` function, add an observer for the `config_changed` event and pair it with an `_on_config_changed` handler:

```{literalinclude} ../../../examples/k8s-2-configurable/src/charm.py
:language: python
:start-at: framework.observe(self.on.config_changed
:end-at: framework.observe(self.on.config_changed
:dedent:
```

Now, define the handler, as below. Since configuring something like a port affects the way we call our workload application, we need to update our Pebble configuration.

```{literalinclude} ../../../examples/k8s-2-configurable/src/charm.py
:language: python
:pyobject: FastAPIDemoCharm._on_config_changed
:dedent:
```

We'll define `_replan_workload` shortly.

```{caution}

A charm does not know which configuration option has been changed. Thus, make sure to validate all the values. This is especially important since multiple values can be changed in one call. Using a config class simplifies this, as all validation should be done when the config object is created.
```

In the `__init__` function, add a new attribute to define a container object for your workload:

```{literalinclude} ../../../examples/k8s-2-configurable/src/charm.py
:language: python
:start-at: "# See 'containers' in charmcraft.yaml."
:end-at: self.container = self.unit.get_container("demo-server")
:dedent:
```

Create a new method, as below. This method will get the current Pebble layer configuration and compare the new and the existing service definitions -- if they differ, it will update the layer and restart the service.

```{literalinclude} ../../../examples/k8s-2-configurable/src/charm.py
:language: python
:pyobject: FastAPIDemoCharm._replan_workload
:dedent:
```

When the config is loaded as part of creating the Pebble layer, if the config is invalid (in our case, if the port is set to 22), then a `ValueError` will be raised. The `_replan_workload` method handles that by logging the error and setting the status of the unit to blocked, letting the Juju user know that they need to take action.

Now, crucially, update the `_get_pebble_layer` method to make the layer definition dynamic, as shown below. This will replace the static port `8000` with the port passed to the method.

```{literalinclude} ../../../examples/k8s-2-configurable/src/charm.py
:language: python
:pyobject: FastAPIDemoCharm._get_pebble_layer
:dedent:
```

As you may have noticed, the new `_replan_workload` method looks like a more advanced variant of the existing `_on_demo_server_pebble_ready` method. Remove the body of the `_on_demo_server_pebble_ready` method and replace it a call to `_replan_workload` like this:

```{literalinclude} ../../../examples/k8s-2-configurable/src/charm.py
:language: python
:pyobject: FastAPIDemoCharm._on_demo_server_pebble_ready
:dedent:
```

## Validate your charm

First, repack and refresh your charm:

```text
charmcraft pack
juju refresh fastapi-demo --force-units \
  --path ./fastapi-demo_amd64.charm \
  --resource demo-server-image=ghcr.io/canonical/api_demo_server:1.0.4
```

```{tip}
`--force-units` ensures that the refresh succeeds even if the application is in an error state. This option is useful during development, when your charm code might be the cause of the error. You should avoid using `--force-units` when refreshing applications in production.
```

Now, check the available configuration options:

```text
juju config fastapi-demo
```

Our newly defined `server-port` option is there. Let's try to configure it to something else, e.g., `5000`:

```text
juju config fastapi-demo server-port=5000
```

Now, let's validate that the app is actually running and reachable on the new port by sending the HTTP  request below, where `10.1.157.74` is the IP of our pod and `5000` is the new application port:

```text
curl 10.1.157.74:5000/version
```

You should see JSON string with the version of the application: `{"version":"1.0.4"}`

Let's also verify that our invalid port number check works by setting the port to `22` and then running `juju status`:

```text
juju config fastapi-demo server-port=22
juju status
```

As expected, the application is indeed in the `blocked` state:

```text
Model    Controller     Cloud/Region  Version  SLA          Timestamp
testing  concierge-k8s  k8s           3.6.13   unsupported  18:19:24+01:00

App           Version  Status   Scale  Charm         Channel  Rev  Address         Exposed  Message
fastapi-demo           blocked      1  fastapi-demo             1  10.152.183.215  no       Invalid port number, 22 is reserved for SSH

Unit             Workload  Agent  Address      Ports  Message
fastapi-demo/0*  blocked   idle   10.1.157.74         Invalid port number, 22 is reserved for SSH
```

Congratulations, you now know how to make your charm configurable!

Before continuing, reset the port to `8000` and check that the application is in `active` status:

```text
juju config fastapi-demo server-port=8000
juju status
```

## Write unit tests

Since we added a new feature to configure `server-port` and use it in the Pebble layer dynamically, we should write tests for the feature.

First, we'll add a test that sets the port in the input state and asserts that the port is used in the service's command in the container layer:

```{literalinclude} ../../../examples/k8s-2-configurable/tests/unit/test_charm.py
:language: python
:pyobject: test_config_changed
```

In `_on_config_changed`, we specifically don't allow port 22 to be used. If port 22 is configured, we set the unit status to `blocked`. So, we can add a test to cover this behaviour by setting the port to 22 in the input state and asserting that the unit status is blocked:

```{literalinclude} ../../../examples/k8s-2-configurable/tests/unit/test_charm.py
:language: python
:pyobject: test_config_changed_invalid_port
```

Run `tox -e unit` to check that all tests pass.

## Review the final code

For the full code, see [our example charm for this chapter](https://github.com/canonical/operator/tree/main/examples/k8s-2-configurable).

> **See next: {ref}`Integrate your charm with PostgreSQL <integrate-your-charm-with-postgresql>`**
