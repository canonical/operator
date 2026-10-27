---
myst:
  html_meta:
    description: Understand what happens to a Kubernetes charm when Juju's charm container receives SIGTERM.
---

(handle-kubernetes-termination)=
# Handle Kubernetes pod termination

When Kubernetes terminates a Juju unit pod, it sends `SIGTERM` to each container in the pod and starts the pod's termination grace period. This is different from a charm receiving a `stop` event: Kubernetes and the container runtime initiate the shutdown, while Juju decides whether the unit is being permanently removed or is expected to return.

## What Juju does

For a Kubernetes unit, the Juju unit agent listens for `SIGTERM`. On receipt, it calls the controller to report that the unit is terminating.

- If the unit is **dying** (for example, the application or unit is being removed), Juju lets its normal lifecycle handling shut down the agent. The unit's normal lifecycle events, including `stop` and then `remove` where applicable, are still the mechanism for charm cleanup. A pod deletion does not create a second, special Ops event.
- If the unit is expected to **restart** (for example, while Kubernetes replaces a pod during a staged update), Juju terminates the unit agent worker so that the agent can restart in the replacement container. This is not a `stop` event and does not mean that the unit has been removed.

The distinction is important: do not use a signal handler in the charm to infer whether the unit is being removed. Handle cleanup that must happen as part of the charm lifecycle in `self.stop` and `self.remove`, and make it safe to run again after a restart.

A `SIGTERM` does not make Juju wait for an arbitrary charm handler to finish. If a hook or event handler is already running, it may be interrupted as the agent shuts down. Code must therefore tolerate being stopped part-way through and run correctly when the event is retried or delivered again. Persist progress before doing irreversible work, and avoid relying on Python process shutdown handlers (`atexit`, object cleanup methods, or a custom signal handler) for charm cleanup.

## What happens to Pebble and workload services

Kubernetes sends the signal to the workload container as well as the charm container. Pebble is the workload container's process supervisor and normally receives the signal as PID 1. It forwards `SIGTERM` to the process groups of its managed services. Pebble gives a service five seconds to exit, then sends `SIGKILL`; its stop operation allows up to ten seconds in total. These Pebble timeouts do not extend Kubernetes' pod termination grace period.

A workload that needs more time must be given a suitable Kubernetes termination grace period by the workload's deployment configuration. It should still stop promptly: once the pod grace period expires, Kubernetes sends `SIGKILL` and no cleanup code can run. The charm should not assume that Pebble can finish stopping every service before the pod disappears.

See {doc}`Manage the workload container <manage-containers/manage-the-workload-container>` for Pebble service shutdown details and [](ops.Container) for the Ops container API.

## Grace periods and timeouts

The termination grace period is a Kubernetes pod setting. Kubernetes uses its configured value (normally 30 seconds when no value is specified), sends `SIGTERM`, waits for the remaining grace period, and then forcefully kills containers that are still running. Juju does not turn this into an Ops event with a separate timeout, and there is no guarantee that a `stop` or `remove` hook will run before the grace period expires.

Plan termination handlers accordingly:

- keep them short and idempotent;
- do not wait indefinitely for a workload or external service;
- handle connection failures because the Juju controller or Pebble may already be unavailable; and
- treat durable external cleanup as a reconciliation problem rather than something that can only happen during shutdown.

## Reproduce and observe it

Use a disposable model and watch both Juju and Kubernetes while deleting or replacing a unit. For example:

```shell
juju deploy <charm> demo
juju debug-log --replay --include demo/0
kubectl -n <model-namespace> get pod -w
kubectl -n <model-namespace> delete pod <pod-name>
```

To replace a unit pod, change the charm or workload configuration in a way that causes the pod to be replaced rather than deleting the application. Inspect the pod's termination grace period and container logs:

```shell
kubectl -n <model-namespace> get pod <pod-name> -o yaml
kubectl -n <model-namespace> logs <pod-name> -c charm --previous
kubectl -n <model-namespace> logs <pod-name> -c <workload-container> --previous
```

The exact ordering of log messages is not an API: scheduling, controller connectivity, and the grace period affect it. The durable contract is that a pod-level `SIGTERM` shuts down the agent and workload; it is not itself an additional charm event. Observe `stop` and `remove` only when Juju's model lifecycle says that the unit is dying.

For the Kubernetes pod termination contract, see the [Kubernetes documentation on pod lifecycle](https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/) and its [pod termination flow](https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/#pod-termination-flow).
