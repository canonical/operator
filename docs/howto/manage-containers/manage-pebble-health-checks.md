(manage-pebble-health-checks)=
# How to manage Pebble health checks

Pebble supports adding custom health checks: first, to allow Pebble itself to restart services when certain checks fail, and second, to allow Kubernetes to restart containers when specified checks fail.

Each check can be one of three types. The types and their success criteria are:

* `http`: an HTTP `GET` request to the URL specified must return an HTTP 2xx status code.
* `tcp`: opening the given TCP port must be successful.
* `exec`: executing the specified command must yield a zero exit code.

## Check configuration

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

See the {external+pebble:ref}`layer specification <layer-specification>` for more details about the fields and options for different types of checks.

## Respond to a check failing or recovering

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

## Fetch check status

You can use the [`get_check`](ops.Container.get_check) and [`get_checks`](ops.Container.get_checks) methods to fetch the current status of one check or multiple checks, respectively. The returned [`CheckInfo`](ops.pebble.CheckInfo) objects provide various attributes, most importantly a `status` attribute which will be either `UP` or `DOWN`.

Here is a code example that checks whether the `uptime` check is healthy, and writes an error log if not:

```python
container = self.unit.get_container('main')
check = container.get_check('uptime')
if check.status != ops.pebble.CheckStatus.UP:
    logger.error('Uh oh, uptime check unhealthy: %s', check)
```

## Check auto-restart

To enable Pebble auto-restart behavior based on a check, use the `on-check-failure` map in the service configuration. For example, to restart the "server" service when the "http-test" check fails, use the following configuration:

```yaml
services:
    server:
        override: merge
        on-check-failure:
            http-test: restart   # can also be "shutdown" or "ignore" (the default)
```

## Check health endpoint and probes

Pebble includes an HTTP `/v1/health` endpoint that allows a user to query the health of configured checks, optionally filtered by check level with the query string `?level=<level>` This endpoint returns an HTTP 200 status if the checks are healthy, HTTP 502 otherwise.

Each check can optionally specify a `level` of "alive" or "ready". These have semantic meaning: "alive" means the check or the service it's connected to is up and running; "ready" means it's properly accepting network traffic. These correspond to Kubernetes ["liveness" and "readiness" probes](https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/).

When Juju creates a sidecar charm container, it initialises the Kubernetes liveness and readiness probes to hit the `/v1/health` endpoint with `?level=alive` and `?level=ready` filters, respectively.

Ready implies alive, and not alive implies not ready. If you've configured an "alive" check but no "ready" check, and the "alive" check is unhealthy, `/v1/health?level=ready` will report unhealthy as well, and the Kubernetes readiness probe will act on that.

If there are no checks configured, Pebble returns HTTP 200 so the liveness and readiness probes are successful by default. To use this feature, you must explicitly create checks with `level: alive` or `level: ready` in the layer configuration.

Consider the K8s liveness success (`level=alive` check) to mean "Pebble is alive" rather than "the application is fully alive" (and failure to mean "this container needs to die"). For charms that take a long time to start, you should not have a `level=alive` check (if Pebble's running, it will report alive to K8s), and instead use an ordinary Pebble check (without a `level`) in conjunction with `on-check-failure: restart`. That way Pebble itself has full control over restarting the service in question.

When checks exceed the configured failure threshold, or start succeeding again after, Juju will emit a
`pebble-check-failed` or `pebble-check-recovered` event. Note that the status of the check when the
event is received may not be the same - for example, by the time the charm receives a failed event
the check may have started passing again. If your charm needs to act based on the current state
rather than the fact that the check state changed, then the charm code must get the current check
state (and you would use the same handler for both failed and recovered events).

> See more: [](ops.PebbleCheckRecoveredEvent), [](ops.PebbleCheckFailedEvent)

## Services with long startup time

When a K8s liveness probe (a `level=alive` check) succeeds, you should consider it to mean "Pebble is alive" rather than "the workload is alive". Similarly, a liveness probe failure means "this container needs to be restarted" rather than an issue with the workload.

This means you should not usually have a `level=alive` check for a service in a charm. This is especially important for workloads that take a long or indefinite period of time to start. Instead, use a Pebble check without a level and specify `on-check-failure: restart` for the service. That way Pebble itself has control over restarting the service.

## Write unit tests

> Added in ops 2.17

To test charms that use Pebble check events, use the `CheckInfo` class and the emit the appropriate event. For example, to simulate the "http-test" check failing, the charm test could do the following:

```python
import ops
from ops import testing

def test_http_check_failing():
    ctx = testing.Context(PostgresCharm)
    check_info = testing.CheckInfo(
        'http-test',
        failures=3,
        status=ops.pebble.CheckStatus.DOWN,
        level=layer.checks['http-test'].level,
        startup=layer.checks['http-test'].startup,
        threshold=layer.checks['http-test'].threshold,
    )
    layer = ops.pebble.Layer({
        'checks': {'http-test': {'override': 'replace', 'startup': 'enabled', 'failures': 3}},
    })
    container = testing.Container('db', check_infos={check_info}, layers={'layer1': layer})
    state_in = testing.State(containers={container})

    state_out = ctx.run(ctx.on.pebble_check_failed(container, info=check_info), state_in)

    assert state_out...
```
