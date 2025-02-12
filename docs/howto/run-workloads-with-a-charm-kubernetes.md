(run-workloads-with-a-charm-kubernetes)=
# How to run workloads with a charm - Kubernetes

The recommended way to create charms for Kubernetes is using the sidecar pattern with the workload container running Pebble.

Pebble is a lightweight, API-driven process supervisor designed for use with charms. If you specify the `containers` field in a charm's `charmcraft.yaml`, Juju will deploy the charm code in a sidecar container, with Pebble running as the workload container's `ENTRYPOINT`.

When the workload container starts up, Juju fires a [`PebbleReadyEvent`](ops.PebbleReadyEvent), which can be handled using [`Framework.observe`](ops.Framework.observe). This gives the charm author access to `event.workload`, a [`Container`](ops.Container) instance.

The `Container` class has methods to modify the Pebble configuration "plan", start and stop services, read and write files, and run commands. These methods use the Pebble API, which communicates from the charm container to the workload container using HTTP over a Unix domain socket.

The rest of this document provides details of how a charm interacts with the workload container via Pebble, using `ops` [`Container`](ops.Container) methods.


```{note}

The [`Container.pebble`](ops.Container.pebble) property returns the [`pebble.Client`](ops.pebble.Client) instance for the given container.
```

## Set up the workload container

### Configure Juju to set up Pebble in the workload container

<!--Juju already sets it up when it provisions the container-->

The preferred way to run workloads on Kubernetes with charms is to start your workload with [Pebble](https://canonical-pebble.readthedocs-hosted.com/). You do not need to modify upstream container images to make use of Pebble for managing your workload. The Juju controller automatically injects Pebble into workload containers using an [Init Container](https://kubernetes.io/docs/concepts/workloads/pods/init-containers/) and [Volume Mount](https://kubernetes.io/docs/concepts/storage/volumes/). The entrypoint of the container is overridden so that Pebble starts first and is able to manage running services. Charms communicate with the Pebble API using a UNIX socket, which is mounted into both the charm and workload containers.

```{note}

By default, you'll find the Pebble socket at `/var/lib/pebble/default/pebble.sock` in the workload container, and `/charm/<container>/pebble.sock` in the charm container.
```

Most Kubernetes charms will need to define a `containers` map in their `charmcraft.yaml` in order to start a workload with a known OCI image:

```yaml
# ...
containers:
  myapp:
    resource: myapp-image
  redis:
    resource: redis-image

resources:
  myapp-image:
    type: oci-image
    description: OCI image for my application
  redis-image:
    type: oci-image
    description: OCI image for Redis
# ...
```

```{note}

In some cases, you may wish not to specify a `containers` map, which will result in an "operator-only" charm. These can be useful when writing "integrator charms" (sometimes known as "proxy charms"), which are used to represent some external service in the Juju model.
```

For each container, a resource of type `oci-image` must also be specified. The resource is used to inform the Juju controller how to find the correct OCI-compliant container image for your workload on Charmhub.

If multiple containers are specified in `charmcraft.yaml` (as above), each Pod will contain an instance of every specified container. Using the example above, each Pod would be created with a total of 3 running containers:

- a container running the `myapp-image`
- a container running the `redis-image`
- a container running the charm code

The Juju controller emits [`PebbleReadyEvent`](ops.PebbleReadyEvent)s to charms when Pebble has initialised its API in a container. These events are named `<container_name>_pebble_ready`. Using the example above, the charm would receive two Pebble related events (assuming the Pebble API starts correctly in each workload):

- `myapp_pebble_ready`
- `redis_pebble_ready`.

Consider the following example snippet from a `charmcraft.yaml`:

```yaml
# ...
containers:
  pause:
    resource: pause-image

resources:
  pause-image:
    type: oci-image
    description: Docker image for google/pause
# ...
```

Once the containers are initialised, the charm needs to tell Pebble how to start the workload. Pebble uses a series of "layers" for its configuration. Layers contain a description of the processes to run, along with the path and arguments to the executable, any environment variables to be specified for the running process and any relevant process ordering (more information available in the [Pebble documentation](https://canonical-pebble.readthedocs-hosted.com)).

```{note}

In many cases, using the container's specified entrypoint may be desired. You can find the original entrypoint of an image locally like so:

`$ docker pull <image>`
`$ docker inspect <image>`
```

When using an OCI-image that is not built specifically for use with Pebble, layers are defined at runtime using Pebble’s API. Recall that when Pebble has initialised in a container (and the API is ready), the Juju controller emits a [`PebbleReadyEvent`](ops.PebbleReadyEvent) event to the charm. Often it is in the callback bound to this event that layers are defined, and services started:

```python
# ...
import ops
# ...

class PauseCharm(ops.CharmBase):
    # ...
    def __init__(self, framework):
        super().__init__(framework)
        # Set a friendly name for your charm. This can be used with the Operator
        # framework to reference the container, add layers, or interact with
        # providers/consumers easily.
        self.name = "pause"
        # This event is dynamically determined from the service name
        # in ops.pebble.Layer
        # 
        # If you set self.name as above and use it in the layer definition following this
        # example, the event will be <self.name>_pebble_ready
        framework.observe(self.on.pause_pebble_ready, self._on_pause_pebble_ready)
        # ...

    def _on_pause_pebble_ready(self, event: ops.PebbleReadyEvent) -> None:
        """Handle the pebble_ready event"""
        # You can get a reference to the container from the PebbleReadyEvent
        # directly with:
        # container = event.workload
        #
        # The preferred method is through get_container()
        container = self.unit.get_container(self.name)
        # Add our initial config layer, combining with any existing layer
        container.add_layer(self.name, self._pause_layer(), combine=True)
        # Start the services that specify 'startup: enabled'
        container.autostart()
        self.unit.status = ops.ActiveStatus()

    def _pause_layer(self) -> ops.pebble.Layer:
        """Returns Pebble configuration layer for google/pause"""
        return ops.pebble.Layer(
            {
                "summary": "pause layer",
                "description": "pebble config layer for google/pause",
                "services": {
                    self.name: {
                        "override": "replace",
                        "summary": "pause service",
                        "command": "/pause",
                        "startup": "enabled",
                    }
                },
            }
        )
# ...
```

A common method for configuring container workloads is by manipulating environment variables. The layering in Pebble makes this easy. Consider the following extract from a `config-changed` callback which combines a new overlay layer (containing some environment configuration) with the current Pebble layer and restarts the workload:

```python
# ...
import ops
# ...
def _on_config_changed(self, event: ops.ConfigChangedEvent) -> None:
    """Handle the config changed event."""
    # Get a reference to the container so we can manipulate it
    container = self.unit.get_container(self.name)

    # Create a new config layer - specify 'override: merge' in 
    # the 'pause' service definition to overlay with existing layer
    layer = ops.pebble.Layer(
        {
            "services": {
                "pause": {
                    "override": "merge",
                    "environment": {
                        "TIMEOUT": self.model.config["timeout"],
                    },
                }
            },
        }
    )

    try:
        # Add the layer to Pebble
        container.add_layer(self.name, layer, combine=True)
        logging.debug("Added config layer to Pebble plan")

        # Tell Pebble to update the plan, which will restart any services if needed.
        container.replan()
        logging.info("Updated pause service")
        # All is well, set an ActiveStatus
        self.unit.status = ops.ActiveStatus()
    except ops.pebble.PathError, ops.pebble.ProtocolError, ops.pebble.ConnectionError:
        # handle errors (for example: the container might not be ready yet)
        .....
```

In this example, each time a `config-changed` event is fired, a new overlay layer is created that only includes the environment config, populated using the charm’s config. Pebble will ensure that that the application is only restarted if the configuration has changed.

### Configure a Pebble layer

Pebble services are [configured by means of layers](https://canonical-pebble.readthedocs-hosted.com/en/latest/reference/layer-specification/), with higher layers adding to or overriding lower layers, forming the effective Pebble configuration, or "plan".

When a workload container is created and Pebble starts up, it looks in `/var/lib/pebble/default/layers` (if that exists) for configuration layers already present in the container image, such as `001-layer.yaml`. If there are existing layers there, that becomes the starting configuration, otherwise Pebble is happy to start with an empty configuration, meaning no services.

In the latter case, Pebble is configured dynamically via the API by adding layers at runtime.

See the [layer specification](https://canonical-pebble.readthedocs-hosted.com/en/latest/reference/layer-specification/) for more details.

#### Add a configuration layer

To add a configuration layer, call [`Container.add_layer`](ops.Container.add_layer) with a label for the layer, and the layer's contents as a YAML string, Python dict, or [`pebble.Layer`](#ops.pebble.Layer) object.

You can see an example of `add_layer` under the ["Replan" heading](#replan). The `combine=True` argument tells Pebble to combine the named layer into an existing layer of that name (or add a layer if none by that name exists). Using `combine=True` is common when dynamically adding layers.

Because `combine=True` combines the layer with an existing layer of the same name, it's normally used with `override: replace` in the YAML service configuration. This means replacing the entire service configuration with the fields in the new layer.

If you're adding a single layer with `combine=False` (default option) on top of an existing base layer, you may want to use `override: merge` in the service configuration. This will merge the fields specified with the service by that name in the base layer. [See an example of overriding a layer.](https://canonical-pebble.readthedocs-hosted.com/en/latest/reference/layers/#layer-override)

#### Fetch the effective plan

Charm authors can also introspect the current plan using [`Container.get_plan`](ops.Container.get_plan). It returns a [`pebble.Plan`](ops.pebble.Plan) object whose `services` attribute maps service names to [`pebble.Service`](ops.pebble.Service) instances.

It is not necessary to use `get_plan` to determine whether the plan has changed and start services accordingly. If you call [`replan`](ops.Container.replan), then Pebble will take care of this for you.

Below is an example of how you might use `get_plan` to introspect the current configuration, and log the active services:

```python
class MyCharm(ops.CharmBase):
    ...

    def _on_config_changed(self, event):
        container = self.unit.get_container("main")
        container.replan()
        plan = container.get_plan()
        for service in plan.services:
            logger.info('Service: %s', service)
        ...
```

## Control and monitor services in the workload container

The main purpose of Pebble is to control and monitor services, which are usually long-running processes like web servers and databases.

In the context of Juju sidecar charms, Pebble is run with the `--hold` argument, which prevents it from automatically starting the services marked with `startup: enabled`. This is to give the charm full control over when the services in Pebble's configuration are actually started.

### Replan

After adding a configuration layer to the plan (details below), you need to call `replan` to make any changes to `services` take effect. When you execute replan, Pebble will automatically restart any services that have changed, respecting dependency order. If the services are already running, it will stop them first using the normal [stop sequence](#start-and-stop).

The reason for replan is so that you as a user have control over when the (potentially high-impact) action of stopping and restarting your services takes place.

Replan also starts the services that are marked as `startup: enabled` in the configuration plan, if they're not running already.

Call [`Container.replan`](ops.Container.replan) to execute the replan procedure. For example:

```python
class SnappassTestCharm(ops.CharmBase):
    ...

    def _start_snappass(self):
        container = self.unit.containers["snappass"]
        snappass_layer = {
            "services": {
                "snappass": {
                    "override": "replace",
                    "summary": "snappass service",
                    "command": "snappass",
                    "startup": "enabled",
                }
            },
        }
        container.add_layer("snappass", snappass_layer, combine=True)
        container.replan()
        self.unit.status = ops.ActiveStatus()
```

### Check container health

`ops` provides a way to ensure that your container is healthy. In the `Container` class, `Container.can_connect()` can be used if you only need to know that Pebble is responding at a specific point in time - for example to update a status message. This should *not* be used to guard against later Pebble operations, because that introduces a race condition where Pebble might be responsive when `can_connect()` is called, but is not when the later operation is executed. Instead, charms should always include `try`/`except` statements around Pebble operations, to avoid the unit going into error state.

> See more: [](ops.Container)

### Start and stop

To start (or stop) one or more services by name, use the [`start`](ops.Container.start) and [`stop`](ops.Container.stop) methods. Here's an example of how you might stop and start a database service during a backup action:

```python
class MyCharm(ops.CharmBase):
    ...

    def _on_pebble_ready(self, event):
        container = event.workload
        container.start('mysql')

    def _on_backup_action(self, event):
        container = self.unit.get_container('main')
        try:
            container.stop('mysql')
            do_mysql_backup()
            container.start('mysql')
        except ops.pebble.ProtocolError, ops.pebble.PathError, ops.pebble.ConnectionError:
            # handle Pebble errors
```

It's not an error to start a service that's already started, or stop one that's already stopped. These actions are *idempotent*, meaning they can safely be performed more than once, and the service will remain in the same state.

When Pebble starts a service, it waits one second to ensure the process doesn't exit too quickly. In Juju 3.6.0 and earlier, if the process exits within one second, the start operation raises an error and the service remains stopped. In Juju 3.6.1 and later, the operation will still raise an error, but Pebble will continue to try starting the service.

To stop a service, Pebble first sends `SIGTERM` to the service's process group to try to stop the service gracefully. If the process has not exited after 5 seconds, Pebble sends `SIGKILL` to the process group. If the process still doesn't exit after another 5 seconds, the stop operation raises an error. If the process exits any time before the 10 seconds have elapsed, the stop operation succeeds.

### Fetch service status

You can use the [`get_service`](ops.Container.get_service) and [`get_services`](ops.Container.get_services) methods to fetch the current status of one service or multiple services, respectively. The returned [`ServiceInfo`](ops.pebble.ServiceInfo) objects provide a `status` attribute with various states, or you can use the [`ServiceInfo.is_running`](ops.pebble.ServiceInfo.is_running) method.

Here is a modification to the start/stop example that checks whether the service is running before stopping it:

```python
class MyCharm(ops.CharmBase):
    ...

    def _on_backup_action(self, event):
        container = self.unit.get_container('main')
        is_running = container.get_service('mysql').is_running()
        if is_running:
            container.stop('mysql')
        do_mysql_backup()
        if is_running:
            container.start('mysql')
```

### Send signals to services

You can use the [`Container.send_signal`](ops.Container.send_signal) method to send a signal to one or more services. For example, to send `SIGHUP` to the hypothetical "nginx" and "redis" services:

```python
container.send_signal('SIGHUP', 'nginx', 'redis')
```

This will raise an `APIError` if any of the services are not in the plan or are not currently running.

### View service logs

Pebble stores service logs (stdout and stderr from services) in a ring buffer accessible via the `pebble logs` command. Each log line is prefixed with the timestamp and service name, using the format `2021-05-03T03:55:49.654Z [snappass] ...`. Pebble allocates a ring buffer of 100KB per service (not one ring to rule them all), and overwrites the oldest logs in the buffer when it fills up.

When running under Juju, the Pebble server is started with the `--verbose` flag, which means it also writes these logs to Pebble's own stdout. That in turn is accessible via Kubernetes using the `kubectl logs` command. For example, to view the logs for the "redis" container, you could run:

```
microk8s kubectl logs -n snappass snappass-test-0 -c redis
```

In the command line above, "snappass" is the namespace (Juju model name), "snappass-test-0" is the pod, and "redis" the specific container defined by the charm configuration.

### Configure service auto-restart

Pebble automatically restarts services when they exit unexpectedly.

By default, Pebble will automatically restart a service when it exits (with either a zero or nonzero exit code). In addition, Pebble implements an exponential backoff delay and a small random jitter time between restarts.

You can configure this behavior in the layer configuration, specified under each service. Here is an example showing the complete list of auto-restart options with their defaults:

```yaml
services:
    server:
        override: replace
        command: python3 app.py

        # auto-restart options (showing defaults)
        on-success: restart   # can also be "shutdown" or "ignore"
        on-failure: restart   # can also be "shutdown" or "ignore"
        backoff-delay: 500ms
        backoff-factor: 2.0
        backoff-limit: 30s
```

The `on-success` action is performed if the service exits with a zero exit code, and the `on-failure` action is performed if it exits with a nonzero code. The actions are defined as follows:

* `restart`: automatically restart the service after the current backoff delay. This is the default.
* `shutdown`: shut down the Pebble server. Because Pebble is the container's "PID 1" process, this will cause the container to terminate -- useful if you want Kubernetes to restart the container.
* `ignore`: do nothing (apart from logging the failure).

The backoff delay between restarts is calculated using an exponential backoff: `next = current * backoff_factor`, with `current` starting at the configured `backoff-delay`. If `next` is greater than `backoff-limit`, it is capped at `backoff-limit`. With the defaults, the delays (in seconds) will be: 0.5, 1, 2, 4, 8, 16, 30, 30, and so on.

The `backoff-factor` must be greater than or equal to 1.0. If the factor is set to 1.0, `next` will equal `current`, so the delay will remain constant.

Just before delaying, a small random time jitter of 0-10% of the delay is added (the current delay is not updated). For example, if the current delay value is 2 seconds, the actual delay will be between 2.0 and 2.2 seconds.

## Perform health checks on the workload container

Pebble supports adding custom health checks: first, to allow Pebble itself to restart services when certain checks fail, and second, to allow Kubernetes to restart containers when specified checks fail.

Each check can be one of three types. The types and their success criteria are:

* `http`: an HTTP `GET` request to the URL specified must return an HTTP 2xx status code.
* `tcp`: opening the given TCP port must be successful.
* `exec`: executing the specified command must yield a zero exit code.

### Check configuration

Checks are configured in the layer configuration using the top-level field `checks`. Here's an example showing the three different types of checks:

```yaml
checks:
    up:
        override: replace
        level: alive  # optional, but required for liveness/readiness probes
        period: 10s   # this is the default
        timeout: 3s   # this is the default
        threshold: 3  # this is the default
        exec:
            command: service nginx status

    online:
        override: replace
        level: ready
        tcp:
            port: 8080

    http-test:
        override: replace
        http:
            url: http://localhost:8080/test
```

Each check is performed with the specified `period` (the default is 10 seconds apart), and is considered an error if a `timeout` happens before the check responds -- for example, before the HTTP request is complete or before the command finishes executing.

A check is considered healthy until it's had `threshold` errors in a row (the default is 3). At that point, the `on-check-failure` action will be triggered, and the health endpoint will return an error response (both are discussed below). When the check succeeds again, the failure count is reset.

See the [layer specification](https://canonical-pebble.readthedocs-hosted.com/en/latest/reference/layer-specification/) for more details about the fields and options for different types of checks.

### Respond to a check failing or recovering

> Added in `ops 2.15` and `juju 3.6`

To have the charm respond to a check reaching the failure threshold, or passing again afterwards, observe the `pebble_check_failed` and `pebble_check_recovered` events and switch on the info's `name`:

```python
class PostgresCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        # Note that "db" is the workload container's name
        framework.observe(self.on["db"].pebble_check_failed, self._on_pebble_check_failed)
        framework.observe(self.on["db"].pebble_check_recovered, self._on_pebble_check_recovered)

    def _on_pebble_check_failed(self, event: ops.PebbleCheckFailedEvent):
        if event.info.name == "http-test":
            logger.warning("The http-test has started failing!")
            self.unit.status = ops.ActiveStatus("Degraded functionality ...")

        elif event.info == "online":
            logger.error("The service is no longer online!")

    def _on_pebble_check_recovered(self, event: ops.PebbleCheckRecoveredEvent):
        if event.info.name == "http-test":
            logger.warning("The http-test has stopped failing!")
            self.unit.status = ops.ActiveStatus()

        elif event.info == "online":
            logger.error("The service is online again!")
```

All check events have an `info` property with the details of the check's current status. Note that, by the time that the charm receives the event, the status of the check may have changed (for example, passed again after failing). If the response to the check failing is light (such as changing the status), then it's fine to rely on the status of the check at the time the event was triggered — there will be a subsequent check-recovered event, and the status will quickly flick back to the correct one. If the response is heavier (such as restarting a service with an adjusted configuration), then the two events should share a common handler and check the current status via the `info` property; for example:

```python
class PostgresCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        # Note that "db" is the workload container's name
        framework.observe(self.on["db"].pebble_check_failed, self._on_pebble_check_failed)
        framework.observe(self.on["db"].pebble_check_recovered, self._on_pebble_check_recovered)

    def _on_pebble_check_failed(self, event: ops.PebbleCheckFailedEvent):
        if event.info.name != "up":
            # For now, we ignore the other tests.
            return
        if event.info.status == ops.pebble.CheckStatus.DOWN:
            self.activate_alternative_configuration()
        else:
            self.activate_main_configuration()
```

### Fetch check status

You can use the [`get_check`](ops.Container.get_check) and [`get_checks`](ops.Container.get_checks) methods to fetch the current status of one check or multiple checks, respectively. The returned [`CheckInfo`](ops.pebble.CheckInfo) objects provide various attributes, most importantly a `status` attribute which will be either `UP` or `DOWN`.

Here is a code example that checks whether the `uptime` check is healthy, and writes an error log if not:

```python
container = self.unit.get_container('main')
check = container.get_check('uptime')
if check.status != ops.pebble.CheckStatus.UP:
    logger.error('Uh oh, uptime check unhealthy: %s', check)
```

### Check auto-restart

To enable Pebble auto-restart behavior based on a check, use the `on-check-failure` map in the service configuration. For example, to restart the "server" service when the "http-test" check fails, use the following configuration:

```yaml
services:
    server:
        override: merge
        on-check-failure:
            http-test: restart   # can also be "shutdown" or "ignore" (the default)
```

### Check health endpoint and probes

Pebble includes an HTTP `/v1/health` endpoint that allows a user to query the health of configured checks, optionally filtered by check level with the query string `?level=<level>` This endpoint returns an HTTP 200 status if the checks are healthy, HTTP 502 otherwise.

Each check can optionally specify a `level` of "alive" or "ready". These have semantic meaning: "alive" means the check or the service it's connected to is up and running; "ready" means it's properly accepting network traffic. These correspond to Kubernetes ["liveness" and "readiness" probes](https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/).

When Juju creates a sidecar charm container, it initialises the Kubernetes liveness and readiness probes to hit the `/v1/health` endpoint with `?level=alive` and `?level=ready` filters, respectively.

Ready implies alive, and not alive implies not ready. If you've configured an "alive" check but no "ready" check, and the "alive" check is unhealthy, `/v1/health?level=ready` will report unhealthy as well, and the Kubernetes readiness probe will act on that.

If there are no checks configured, Pebble returns HTTP 200 so the liveness and readiness probes are successful by default. To use this feature, you must explicitly create checks with `level: alive` or `level: ready` in the layer configuration.

Consider the K8s liveness success (`level=alive` check) to mean "Pebble is alive" rather than "the application is fully alive" (and failure to mean "this container needs to die"). For charms that take a long time to start, you should not have a `level=alive` check (if Pebble's running, it will report alive to K8s), and instead use an ordinary Pebble check (without a `level`) in conjunction with `on-check-failure: restart`. That way Pebble itself has full control over restarting the service in question.

### Test checks

> Added in ops 2.17

To test charms that use Pebble check events, use the `CheckInfo` class and the emit the appropriate event. For example, to simulate the "http-test" check failing, the charm test could do the following:

```python
import ops
from ops import testing

def test_http_check_failing():
    ctx = testing.Context(PostgresCharm)
    check_info = testing.CheckInfo("http-test", failures=3, status=ops.pebble.CheckStatus.DOWN)
    container = testing.Container("db", check_infos={check_info})
    state_in = testing.State(containers={container})

    state_out = ctx.run(ctx.on.pebble_check_failed(container, check_info), state_in)

    assert state_out...
```

## Manage files in the workload container

Pebble's files API allows charm authors to read and write files on the workload container. You can write files ("push"), read files ("pull"), list files in a directory, make directories, and delete files or directories.

### Push

Probably the most useful operation is [`Container.push`](ops.Container.push), which allows you to write a file to the workload, for example, a PostgreSQL configuration file. You can use `push` as follows (note that this code would be inside a charm event handler):

```python
config = """
port = 7777
max_connections = 1000
"""
container.push('/etc/pg/postgresql.conf', config, make_dirs=True)
```

The `make_dirs=True` flag tells `push` to create the intermediate directories if they don't already exist (`/etc/pg` in this case).

There are many additional features, including the ability to send raw bytes (by providing a Python `bytes` object as the second argument) and write data from a file-like object. You can also specify permissions and the user and group for the file. See the [API documentation](ops.Container.push) for details.

### Pull

To read a file from the workload, use [`Container.pull`](ops.Container.pull), which returns a file-like object that you can `read()`.

The files API doesn't currently support update, so to update a file you can use `pull` to perform a read-modify-write operation, for example:

```python
# Update port to 8888 and restart service
config = container.pull('/etc/pg/postgresql.conf').read()
if 'port =' not in config:
    config += '\nport = 8888\n'
container.push('/etc/pg/postgresql.conf', config)
container.restart('postgresql')
```

If you specify the keyword argument `encoding=None` on the `pull()` call, reads from the returned file-like object will return `bytes`. The default is `encoding='utf-8'`, which will decode the file's bytes from UTF-8 so that reads return a Python `str`.

### Push recursive

To copy several files to the workload, use [`Container.push_path`](ops.Container.push_path), which copies files recursively into a specified destination directory.  The API docs contain detailed examples of source and destination semantics and path handling.

```python
# copy "/source/dir/[files]" into "/destination/dir/[files]"
container.push_path('/source/dir', '/destination')

# copy "/source/dir/[files]" into "/destination/[files]"
container.push_path('/source/dir/*', '/destination')
```

A trailing "/*" on the source directory is the only supported globbing/matching.

### Pull recursive

To copy several files to the workload, use [`Container.pull_path`](ops.Container.pull_path), which copies files recursively into a specified destination directory.  The API docs contain detailed examples of source and destination semantics and path handling.

```python
# copy "/source/dir/[files]" into "/destination/dir/[files]"
container.pull_path('/source/dir', '/destination')

# copy "/source/dir/[files]" into "/destination/[files]"
container.pull_path('/source/dir/*', '/destination')
```

A trailing "/*" on the source directory is the only supported globbing/matching.

### List files

To list the contents of a directory or return stat-like information about one or more files, use [`Container.list_files`](ops.Container.list_files). It returns a list of [`pebble.FileInfo`](ops.pebble.FileInfo) objects for each entry (file or directory) in the given path, optionally filtered by a glob pattern. For example:

```python
infos = container.list_files('/etc', pattern='*.conf')
total_size = sum(f.size for f in infos)
logger.info('total size of config files: %d', total_size)
names = set(f.name for f in infos)
if 'host.conf' not in names:
    raise Exception('This charm requires /etc/host.conf!')
```

If you want information about the directory itself (instead of its contents), call `list_files(path, itself=True)`.

### Create directory

To create a directory, use [`Container.make_dir`](ops.Container.make_dir). It takes an optional `make_parents=True` argument (like `mkdir -p`), as well as optional permissions and user/group arguments. Some examples:

```python
container.make_dir('/etc/pg', user='postgres', group='postgres')
container.make_dir('/some/other/nested/dir', make_parents=True)
```

### Remove path

To delete a file or directory, use [`Container.remove_path`](ops.Container.remove_path). If a directory is specified, it must be empty unless `recursive=True` is specified, in which case the entire directory tree is deleted, recursively (like `rm -r`). For example:

```python
# Delete Apache access log
container.remove_path('/var/log/apache/access.log')
# Blow away /tmp/mysubdir and all files under it
container.remove_path('/tmp/mysubdir', recursive=True)
```

### Check file and directory existence

To check if a paths exists you can use [`Container.exists`](ops.Container.exists) for directories or files and [`Container.isdir`](ops.Container.isdir) for directories.  These functions are analogous to python's `os.path.isdir` and `os.path.exists` functions.  For example:

```python
# if /tmp/myfile exists
container.exists('/tmp/myfile') # True
container.isdir('/tmp/myfile') # False

# if /tmp/mydir exists
container.exists('/tmp/mydir') # True
container.isdir('/tmp/mydir') # True
```

## Run commands on the workload container

Pebble includes an API for executing arbitrary commands on the workload container: the [`Container.exec`](ops.Container.exec) method. It supports sending stdin to the process and receiving stdout and stderr, as well as more advanced options.

To run simple commands and receive their output, call `Container.exec` to start the command, and then use the returned [`Process`](ops.pebble.ExecProcess) object's [`wait_output`](ops.pebble.ExecProcess.wait_output) method to wait for it to finish and collect its output.

For example, to back up a PostgreSQL database, you might use `pg_dump`:

```python
process = container.exec(['pg_dump', 'mydb'], timeout=5*60)
sql, warnings = process.wait_output()
if warnings:
    for line in warnings.splitlines():
        logger.warning('pg_dump: %s', line.strip())
# do something with "sql"
```

### Handle errors

The `exec` method raises a [`pebble.APIError`](ops.pebble.APIError) if basic checks fail and the command can't be executed at all, for example, if the executable is not found.

The [`ExecProcess.wait`](ops.pebble.ExecProcess.wait) and [`ExecProcess.wait_output`](ops.pebble.ExecProcess.wait_output) methods raise [`pebble.ChangeError`](ops.pebble.ChangeError) if there was an error starting or running the process, and [`pebble.ExecError`](ops.pebble.ExecError) if the process exits with a non-zero exit code.

In the case where the process exits via a signal (such as SIGTERM or SIGKILL), the exit code will be 128 plus the signal number. SIGTERM's signal number is 15, so a process terminated via SIGTERM would give exit code 143 (128+15).

It's okay to let these exceptions bubble up: Juju will mark the hook as failed and re-run it automatically. However, if you want fine-grained control over error handling, you can catch the `ExecError` and inspect its attributes. For example:

```python
process = container.exec(['cat', '--bad-arg'])
try:
    stdout, _ = process.wait_output()
    logger.info(stdout)
except ops.pebble.ExecError as e:
    logger.error('Exited with code %d. Stderr:', e.exit_code)
    for line in e.stderr.splitlines():
        logger.error('    %s', line)
```

That will log something like this:

```text
Exited with code 1. Stderr:
    cat: unrecognized option '--bad-arg'
    Try 'cat --help' for more information.
```

### Use command options

The `Container.exec` method has various options (see [full API documentation](ops.pebble.Client.exec)), including:

* `environment`: a dict of environment variables to pass to the process
* `working_dir`: working directory to run the command in
* `timeout`: command timeout in seconds
* `user_id`, `user`, `group_id`, `group`: UID/username and GID/group name to run command as
* `service_context`: run the command in the context of the specified service

Here is a (contrived) example showing the use of most of these parameters:

```python
process = container.exec(
    ['/bin/sh', '-c', 'echo HOME=$HOME, PWD=$PWD, FOO=$FOO'],
    environment={'FOO': 'bar'},
    working_dir='/tmp',
    timeout=5.0,
    user='bob',
    group='staff',
)
stdout, _ = process.wait_output()
logger.info('Output: %r', stdout)
```

This will execute the echo command in a shell and log something like `Output: 'HOME=/home/bob, PWD=/tmp, FOO=bar\n'`.

The `service_context` option allows you to specify the name of a service to "inherit" context from. Specifically, inherit its environment variables, user/group settings, and working directory. The other exec options (`user_id`, `user`, `group_id`, `group`, `working_dir`) will override the service's settings; `environment` will be merged on top of the service’s environment.

Here's an example that uses the `service_context` option:

```python
# Use environment, user/group, and working_dir from "database" service
process = container.exec(['pg_dump', 'mydb'], service_context='database')
process.wait_output()
```

### Use input/output options

The simplest way of receiving standard output and standard error is by using the [`ExecProcess.wait_output`](ops.pebble.ExecProcess.wait_output) method as shown below. The simplest way of sending standard input to the program is as a string, using the `stdin` parameter to `exec`. For example:

```python
process = container.exec(['tr', 'a-z', 'A-Z'],
                         stdin='This is\na test\n')
stdout, _ = process.wait_output()
logger.info('Output: %r', stdout)
```

By default, input is sent and output is received as Unicode using the UTF-8 encoding. You can change this with the `encoding` parameter (which defaults to `utf-8`). The most common case is to set `encoding=None`, which means "use raw bytes", in which case `stdin` must be a bytes object and `wait_output()` returns bytes objects. 

For example, the following will log `Output: b'\x01\x02'`:

```python
process = container.exec(['cat'], stdin=b'\x01\x02',
                         encoding=None)
stdout, _ = process.wait_output()
logger.info('Output: %r', stdout)
```

You can also pass [file-like objects](https://docs.python.org/3/glossary.html#term-file-object) using the `stdin`, `stdout`, and `stderr` parameters. These can be real files, streams, `io.StringIO` instances, and so on. When the `stdout` and `stderr` parameters are specified, call the `ExecProcess.wait` method instead of `wait_output`, as output is being written, not returned.

For example, to pipe standard input from a file to the command, and write the result to a file, you could use the following:

```python
with open('LICENSE.txt') as stdin:
    with open('output.txt', 'w') as stdout:
        process = container.exec(
            ['tr', 'a-z', 'A-Z'],
            stdin=stdin,
            stdout=stdout,
            stderr=sys.stderr,
        )
        process.wait()
# use result in "output.txt"
```

For advanced uses, you can also perform streaming I/O by reading from and writing to the `stdin` and `stdout` attributes of the `ExecProcess` instance. For example, to stream lines to a process and log the results as they come back, use something like the following:

```python
process = container.exec(['cat'])

# Thread that sends data to process's stdin
def stdin_thread():
    try:
        for line in ['one\n', '2\n', 'THREE\n']:
            process.stdin.write(line)
            process.stdin.flush()
            time.sleep(1)
    finally:
        process.stdin.close()
threading.Thread(target=stdin_thread).start()

# Log from stdout stream as output is received
for line in process.stdout:
    logging.info('Output: %s', line.strip())

# Will return immediately as stdin was closed above
process.wait()
```

That will produce the following logs:

```
Output: 'one\n'
Output: '2\n'
Output: 'THREE\n'
```

Caution: it's easy to get threading wrong and cause deadlocks, so it's best to use `wait_output` or pass file-like objects to `exec` instead if possible.

### Send signals to a running command

To send a signal to the running process, use [`ExecProcess.send_signal`](ops.pebble.ExecProcess.send_signal) with a signal number or name. For example, the following will terminate the "sleep 10" process after one second:

```python
process = container.exec(['sleep', '10'])
time.sleep(1)
process.send_signal(signal.SIGTERM)
process.wait()
```

Note that because sleep will exit via a signal, `wait()` will raise an `ExecError` with an exit code of 143 (128+SIGTERM):

```
Traceback (most recent call last):
  ...
ops.pebble.ExecError: non-zero exit code 143 executing ['sleep', '10']
```

## Use custom notices from the workload container

### Record a notice

To record a custom notice, use the `pebble notify` CLI command. For example, the workload might have a script to back up the database and then record a notice:

```sh
pg_dump mydb >/tmp/mydb.sql
/charm/bin/pebble notify canonical.com/postgresql/backup-done path=/tmp/mydb.sql
```

The first argument to `pebble notify` is the key, which must be in the format `<domain>/<path>`. The caller can optionally provide map data arguments in `<name>=<value>` format; this example shows a single data argument named `path`.

The `pebble notify` command has an optional `--repeat-after` flag, which tells Pebble to only allow the notice to repeat after the specified duration (the default is to repeat for every occurrence). If the caller says `--repeat-after=1h`, Pebble will prevent the notice with the same type and key from repeating within an hour -- useful to avoid the charm waking up too often when a notice occurs frequently.

> See more: [GitHub | Pebble > Notices > `pebble notify`](https://canonical-pebble.readthedocs-hosted.com/en/latest/reference/cli-commands/#reference-pebble-notify-command)

### Respond to a notice

To have the charm respond to a notice, observe the `pebble_custom_notice` event and switch on the notice's `key`:

```python
class PostgresCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        # Note that "db" is the workload container's name
        framework.observe(self.on["db"].pebble_custom_notice, self._on_pebble_custom_notice)

    def _on_pebble_custom_notice(self, event: ops.PebbleCustomNoticeEvent) -> None:
        if event.notice.key == "canonical.com/postgresql/backup-done":
            path = event.notice.last_data["path"]
            logger.info("Backup finished, copying %s to the cloud", path)
            f = event.workload.pull(path, encoding=None)
            s3_bucket.upload_fileobj(f, "db-backup.sql")

        elif event.notice.key == "canonical.com/postgresql/other-thing":
            logger.info("Handling other thing")
```

All notice events have a [`notice`](ops.PebbleNoticeEvent.notice) property with the details of the notice recorded. That is used in the example above to switch on the notice `key` and look at its `last_data` (to determine the backup's path).

### Fetch notices

A charm can also query for notices using the following two `Container` methods:

* [`get_notice`](ops.Container.get_notice), which gets a single notice by unique ID (the value of `notice.id`).
* [`get_notices`](ops.Container.get_notices), which returns all notices by default, and allows filtering notices by specific attributes such as `key`.

### Test notices

To test charms that use Pebble Notices, use the [`pebble_custom_notice`](ops.testing.CharmEvents.pebble_custom_notice) method to simulate recording a notice with the given details. For example, to simulate the "backup-done" notice handled above, the charm tests could do the following:

```python
from ops import testing

@patch('charm.s3_bucket.upload_fileobj')
def test_backup_done(upload_fileobj):
    # Arrange:
    ctx = testing.Context(PostgresCharm)

    notice = testing.Notice(
        'canonical.com/postgresql/backup-done',
        last_data={'path': '/tmp/mydb.sql'},
    )
    container = testing.Container('db', can_connect=True, notices=[notice])
    root = container.get_filesystem()
    (root / "tmp").mkdir()
    (root / "tmp" / "mydb.sql").write_text("BACKUP")
    state_in = testing.State(containers={container})

    # Act:
    state_out = ctx.run(ctx.on.pebble_custom_notice(container, notice), state_in)

    # Assert:
    upload_fileobj.assert_called_once()
    upload_f, upload_key = upload_fileobj.call_args.args
    self.assertEqual(upload_f.read(), b"BACKUP")
    self.assertEqual(upload_key, "db-backup.sql")
```

<!--
 <a href="#heading--access-the-pebble-client-directly"><h2 id="heading--access-the-pebble-client-directly">Access the Pebble client directly</h2></a>

Occasionally charm code may want to access the lower-level Pebble API directly: the [`Container.pebble`](ops.Container.pebble) property returns the [`pebble.Client`](ops.pebble.Client) instance for the given container.

Below is a (contrived) example of an action that uses the Pebble client directly to call [`pebble.Client.get_changes`](ops.pebble.Client.get_changes):

```python
import ops

class MyCharm(ops.CharmBase):
    ...

    def show_pebble_changes(self):
        container = self.unit.get_container('main')
        client = container.pebble
        changes = client.get_changes(select=ops.pebble.ChangeState.ALL)
        for change in changes:
            logger.info('Pebble change %d: %s', change.id, change.summary)
```
-->
