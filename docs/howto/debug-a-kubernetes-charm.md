---
myst:
  html_meta:
    description: Debug Kubernetes charms and their Pebble-managed workloads -- inspect the charm and workload containers, read Pebble services, logs, plans, changes, checks, and notices, and diagnose common sidecar failure modes.
---

(debug-a-kubernetes-charm)=
# How to debug a Kubernetes charm

> See first: {ref}`debug-your-charm`, {ref}`workload-containers`, {external+juju:ref}`Juju | How to manage logs <manage-logs>`

A Kubernetes charm runs as a sidecar: each unit is a pod with a *charm container* (running your charm code) alongside zero or more *workload containers*. Juju injects {external+pebble:doc}`Pebble <index>` into each workload container as its service manager. Your charm talks to each workload's Pebble over an HTTP-on-Unix-socket API.

This split is what makes debugging a Kubernetes charm different from debugging a machine charm: a problem can live in the charm code, in the Pebble configuration, in the workload process itself, or at the Kubernetes layer below all of them. This guide covers the Kubernetes-specific tools for narrowing that down.

For substrate-agnostic tools (`juju debug-log`, `juju debug-hooks`, `juju debug-code`, jhack, and remote debugging with VS Code), see {ref}`debug-your-charm`.

(k8s-two-container-model)=
## Know which container you're looking at

Each piece of the system lives in a specific place. Reaching for the wrong one is the most common way to waste time.

| What | Where it runs | How to reach it |
| --- | --- | --- |
| Your charm code (`src/charm.py`), logs, hooks | charm container | `juju ssh <unit>`, `juju debug-log`, `juju debug-hooks` |
| Pebble and the workload process | workload container (named after the `containers` entry in `charmcraft.yaml`) | `juju ssh --container <name> <unit>`, the Pebble CLI |
| The pod, image pulls, scheduling | Kubernetes | `kubectl` |

The charm and workload containers each have their own filesystem and process space. The charm reaches a workload's Pebble through a Unix socket that Juju mounts into both containers:

- **Workload container** -- The socket is at `/var/lib/pebble/default/pebble.sock`.
- **Charm container** -- The same socket is mounted at `/charm/<container>/pebble.sock`. The Pebble CLI binary is at `/charm/bin/pebble`.

(k8s-common-failure-modes)=
## Common failure modes

If you're not sure where to start, find your symptom here and jump to the section that covers it:

| Symptom | Where to look |
| --- | --- |
| Charm stuck in `maintenance`/`waiting`; `can_connect()` is `False` (or a Pebble call raises `ConnectionError`) at startup | The charm container can't reach the workload's Pebble. Usually the workload container hasn't started yet (no [`PebbleReadyEvent`](ops.PebbleReadyEvent) has fired). Look at the pod, not your charm code. Run `kubectl describe pod` for image-pull or scheduling errors. See [](#k8s-inspect-the-pod) |
| Service shows `backoff` or `error` | `pebble logs` for the crash output, then `pebble changes` / `pebble tasks` for the start failure ([](#k8s-pebble-cli)). |
| Config change has no effect on the running process | The charm added a layer but didn't [`replan`](#run-workloads-with-a-charm-kubernetes-replan). Confirm with `pebble plan` and `pebble services`. |
| Charm raises `ConnectionError` mid-handler | The workload's Pebble became unreachable. Guard Pebble calls with `try`/`except` rather than `can_connect()` ([](ops.Container.can_connect)). |
| `pebble_custom_notice` never fires | Confirm the notice was recorded with `pebble notices`. Check the `key` your handler matches on ([](#k8s-pebble-cli)). |
| Workload isn't ready despite running | A health check is failing. Run `pebble checks` and `pebble check <name> --refresh` ([](#k8s-pebble-cli)). |
| `juju ssh --container` lands in an image with no shell or tools | The workload image is stripped down. Run Pebble against it from the charm container instead, where the socket is mounted ([](#k8s-debug-from-charm-container)), or see [](#k8s-limited-containers). |

(k8s-pebble-cli)=
## Inspect the workload with the Pebble CLI

SSH into the workload container and use the Pebble CLI to see what Pebble thinks is going on. {ref}`debug-your-charm` covers `pebble services`, `pebble logs`, `pebble exec`, `pebble plan`, and `pebble checks`. The commands below go deeper and are the ones you'll reach for when a workload won't start or keeps crashing.

### SSH into the workload container

```shell
juju ssh --container myapp myapp/0
```

All of the examples below assume you're running them inside the workload container, where `pebble` is on the `PATH`. To run them from the charm container instead, see [](#k8s-debug-from-charm-container).

### Read service states

`pebble services` reports a `Current` state for each service. The state tells you most of what you need to know:

| State | Meaning |
| --- | --- |
| `active` | The service is running normally. |
| `inactive` | The service is not running. It was never started (`startup: disabled`), was stopped, or its command could not be executed at all (a wrong path or a binary missing from the image). |
| `backoff` | The service started but exited, and Pebble is restarting it on a backoff schedule. The workload is crashing each time it starts. |
| `error` | The service failed and Pebble has stopped trying to restart it. |

`backoff` and `error` mean the process ran and then died. Look at the workload itself with `pebble logs`.

An unexpected `inactive` (a service you expected to be running) usually means the command never executed. The reason is in `pebble changes` / `pebble tasks`, rather than in the service's logs. We'll look at that next.

### Trace what Pebble did with changes and tasks

When a service won't start, or a `replan` from your charm seems to have done nothing, the *change log* tells you what Pebble actually attempted and why it failed. This is the single most useful Pebble debugging command and is not obvious from the service list alone.

`pebble changes` lists recent operations -- each replan, service start, service stop, and check change:

```text
$ pebble changes
ID  Status  Spawn               Ready               Summary
1   Done    today at 02:05 UTC  today at 02:05 UTC  Autostart service "myapp"
2   Error   today at 02:09 UTC  today at 02:09 UTC  Start service "myapp"
```

A change in `Error` is your lead. Drill into its tasks to see the failure detail and the captured logs:

```text
$ pebble tasks 2
Status  Spawn               Ready               Summary
Error   today at 02:09 UTC  today at 02:09 UTC  Start service "myapp"

......................................................................
Start service "myapp"

2026-05-22T02:09:01Z INFO Most recent service output:
    Traceback (most recent call last):
      ...
    KeyError: 'DATABASE_URL'
2026-05-22T02:09:01Z ERROR service start attempt: exited quickly with code 1, will restart
```

Instead of `pebble tasks <change-id>`, use `pebble tasks --last=start` to jump straight to the most recent service start attempt.

The captured "Most recent service output" is the workload's own stdout/stderr, so a stack trace, a missing-config error, or a permission error shows up right here.

A service whose command can't be executed at all (a wrong path, or a binary missing from the image) fails differently. For example, `cannot start service: fork/exec ...: no such file or directory`.

### Verify the effective plan

`pebble plan` prints the *merged* plan -- the result of combining every layer Pebble knows about. If a service is missing or has the wrong command, compare this against what your charm intended:

```text
$ pebble plan
services:
    myapp:
        summary: my application
        startup: enabled
        override: replace
        command: /bin/myapp --port 8080
```

`pebble plan` is the right tool for "did my charm's configuration take effect?" -- it shows the live, in-memory result.

A charm adds its configuration at runtime with [`Container.add_layer()`](ops.Container.add_layer), which sends the layer to Pebble over the API. Added layers are held in memory and are *not* written to `/var/lib/pebble/default/layers/`. That directory contains only the layers baked into the container image (a rock built with Rockcraft may ship some), which Pebble reads once at startup. An empty or sparse layers directory is normal and doesn't mean your charm's `add_layer()` call failed. Trust `pebble plan`, not the directory listing.

If you change a service's configuration but the running process doesn't change, the usual cause is a missing [`replan`](#run-workloads-with-a-charm-kubernetes-replan): Pebble updates the plan when you add a layer, but doesn't restart services until you call `replan`.

### Check health checks

A failed {ref}`Pebble health check <pebble-health-checks>` behaves differently depending on how it's configured:
- Going "down" can restart the service (set with `on-check-failure`).
- A `level: alive` or `level: ready` check is wired to the container's Kubernetes liveness or readiness probe. This means that a failing `alive` check makes Kubernetes restart the container, while a failing `ready` check marks the pod not-ready and removes it from its Service's endpoints.

Inspect checks with:

```shell
pebble checks                 # status of all checks
pebble check myapp-ready      # full detail for one check, in YAML
pebble check myapp-ready --refresh   # run it now instead of waiting for the next interval
pebble health                 # exit code 0 if all checks healthy, 1 otherwise
```

`pebble check <name>` shows the failure count, the threshold, and the error from the most recent run. This is useful for distinguishing "the check is configured incorrectly" from "the workload is genuinely unhealthy".

### Read notices and warnings

If your charm responds to {ref}`custom notices <pebble-custom-notices>` and an expected `pebble_custom_notice` event never fires, check whether the notice was actually recorded:

```shell
pebble notices                # notices not yet acknowledged
pebble notice 4               # detail for one notice by ID
pebble warnings --all         # Pebble's own warnings (deprecations, config issues)
```

(k8s-debug-from-charm-container)=
## Debug from the charm container

Run Pebble commands against a workload from the charm container, where the workload's socket is mounted:

```shell
juju ssh myapp/0   # connects to the charm container by default
export PEBBLE_SOCKET=/charm/myapp/pebble.sock   # point at the workload's Pebble
/charm/bin/pebble services
/charm/bin/pebble logs
/charm/bin/pebble exec -- cat /etc/myapp/config.yaml
```

This is also the most faithful way to reproduce what your charm sees, since your charm talks to exactly this socket. If a Pebble command works here but your charm raises an error, the problem is in the charm code rather than the Pebble configuration.

(k8s-limited-containers)=
## Work in a stripped-down or rootless workload container

Production workload images are often minimal: no shell, no `ls`, no package manager, and sometimes no root. `juju ssh --container` still lands you inside, but the usual debugging reflexes don't work. Pebble runs as PID 1 in the container and can stand in for most of them.

### Shell commands via Pebble

| Instead of | Use |
| --- | --- |
| `ls /var/lib/myapp` | `pebble ls /var/lib/myapp` |
| `cat /etc/myapp/config.yaml` | `pebble pull /etc/myapp/config.yaml /tmp/config.yaml`, then read it locally |
| `./myprogram --flag` | `pebble exec -- /path/to/myprogram --flag` |
| `cp local.conf /etc/myapp/` | `pebble push local.conf /etc/myapp/local.conf` |
| `env` | `pebble exec --context <service> -- env` (uses the service's environment) |

`pebble ls`, `pebble push`, and `pebble pull` work even when the container has no shell at all, because they go through Pebble's API rather than running a binary in the container.

### Inject a rescue shell

If you need an interactive shell and the image doesn't ship one, push a statically-linked `busybox` in from the outside:

```shell
apt install busybox-static                          # on your local machine
pebble push /usr/bin/busybox /charm/bin/busybox     # into the workload container
pebble exec /charm/bin/busybox sh
# hostname
mycharm-0
```

Pushing binaries in modifies the running container. Remove them when you're done, or restart the pod to get back to a clean state.

Or use a tool like [Borescope](https://borescope.dev), which gives you a bash-like shell over Juju and Pebble without touching the container's filesystem.

### Enter the container as root from the host

If you have shell access to the Kubernetes node the pod is scheduled on, and sufficient host capabilities, you can `nsenter` into the container as root -- useful when the workload runs unprivileged and you need to inspect something Pebble's own user can't touch:

```shell
# On the node:
apt install busybox-static
cp /usr/bin/busybox /proc/<pebble-pid>/root/charm/bin/busybox
nsenter -a -t <pebble-pid> -S 0 -G 0 /charm/bin/busybox sh
# whoami
root
```

`<pebble-pid>` is Pebble's PID as seen from the host (find it with `pgrep pebble` or from `crictl inspect`). This bypasses Pebble entirely and requires root on the node, so it's a last resort for things the other approaches can't reach.

(k8s-inspect-the-pod)=
## Inspect the pod at the Kubernetes layer

When a unit is stuck before Pebble is even reachable, drop below Juju to the Kubernetes layer. Juju puts each model in its own namespace, and names each unit's pod `<app>-<unit-number>`.

```shell
kubectl -n <model> get pods
kubectl -n <model> describe pod myapp-0        # events: image pulls, scheduling, OOM kills, restarts
kubectl -n <model> logs myapp-0 -c charm       # charm container stdout
kubectl -n <model> logs myapp-0 -c myapp       # workload container stdout (Pebble's own output)
kubectl -n <model> logs myapp-0 -c myapp --previous   # output from the last crashed instance
```

The `Events` section of `describe pod` is where you'll find `ImagePullBackOff`, `CreateContainerConfigError`, failed liveness probes, and out-of-memory kills -- none of which appear in `juju debug-log` or the Pebble logs.

```{tip}
Reach for `kubectl` when the problem is the *container or pod* not coming up. Once the workload container is running and Pebble is responding, switch back to the Pebble CLI and `juju debug-log`, which give you a workload- and charm-aware view that raw `kubectl logs` does not.
```
