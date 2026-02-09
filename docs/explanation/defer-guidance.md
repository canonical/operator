(how-and-when-to-defer-events)=
# How, and when, to defer events

Deferring an event is a common pattern, and when used appropriately is a convenient tool for charmers. However, there are limitations to `defer()` - in particular, that the charm has no way to specify when the handler will be re-run, and that event ordering and context move away from the expected pattern. Our advice is that `defer()` is a good solution for some problems, but is best avoided for others.

## Good: retrying on temporary failure

If the charm encounters a temporary failure (such as working with a container or an external API), and expects that the failure may be very short lived, our recommendation is to retry several times for up to a second. If the failure continues, but the charm still expects that it will be resolved without any intervention from a human, then deferring the event handler is often a good choice - along with placing the unit or app in waiting status.

Note that it’s important to consider that when the deferred handler is run again, the Juju context may not be exactly the same as it was when the event was first emitted, so the charm code needs to be aware of this.

If the temporary failure is because the workload is busy, and the charm is deployed to a Kubernetes sidecar controller, you might be able to avoid the defer using a [Pebble custom notice](#pebble-custom-notices). For example, if the code can’t continue because the workload is currently restarting, if you can have a post-completion hook for the restart that executes `pebble notify`, then you can ensure that the charm is ‘woken up’ at the right time to handle the work.

In the future, we hope to see a Juju ‘request re-emit event’ feature that will let the charm tell Juju when it expects the problem to be resolved.

## Reconsider: sequencing

There are some situations where sequencing of units needs to be arranged - for example, to restart replicas before a primary is restarted. Deferring a handler can be used to manage this situation. However, sequencing can also be arranged using a peer relation, and there’s a convenient [rolling-ops charm lib](https://github.com/canonical/charm-rolling-ops) that implements this for you, and we recommend using that approach first.

Using a peer relation to orchestrate the rolling operation allows for more fine-grained control than a simple defer, and avoids the issue of not having control over when the deferred handler will be re-run.

## Reconsider: waiting for a collection of events

It’s common for charms to need a collection of information in order to configure the application (for example, to write a configuration file). For example, the configuration might require a user-set config value, a secret provided by a relation, and a Kubernetes sidecar container to be ready.

Rather than having the handlers for each of these events (`config-changed`, `secret-changed` and/or `relation-changed`, `pebble-ready`) defer if other parts of the configuration are not yet available, it’s best to have the charm observe all three events and set the unit or app state to waiting, maintenance, or blocked status (or have the `collect-status` handler do this) and return. When the last piece of information is available, the handler that notifies the charm of that will complete the work. This is commonly called the "holistic" event handling pattern.

Avoiding defer means that there isn’t a queue of deferred handlers that all do the same work - for example, if `config-changed`, `relation-changed`, and `pebble-ready` were all deferred then when they were all ready, they would all run successfully. This is particularly important when the work is expensive - such as an application restart after writing the configuration, so should not be done unnecessarily.

## OK: waiting without expecting a follow-up event

In some situations, the charm is waiting for a system to be ready, but it’s not one that will trigger a Juju event (as in the case above). For example, the charm might need the workload application to be fully started up, and that might happen after all of the initial start, `config-changed`, `relation-joined`, `pebble-ready`, etc events.

Deferring the work here is ok, but it’s important to consider the delay between deferring the event and its eventual re-emitting - it’s not safe to assume that this will be a small period of time, unless you know that another event can be expected.

For a Kubernetes charm, if the charm is waiting on the workload and it’s possible to have the workload execute a command when it’s ready, then using a [Pebble custom notice](#pebble-custom-notices) is much better than deferring. This then becomes another example of “waiting for a collection of events”, described above.

## Not possible: actions, shutting down, framework generated events, secrets

In some situations, it’s not possible to defer an event, and attempting to do so will raise a `RuntimeError`.

In some cases, this is because the events are run with every Juju hook event, such as `pre-commit`, `commit`, and `update-status`. In others, it’s because Juju provides a built-in retry mechanism, such as `secret-expired` and `secret-rotate`.

With actions, there’s an expectation that the action either succeeds or fails immediately, and there are mechanisms for communicating directly with the user that initiated the action (`event.log` and `event.set_results`). This means that deferring an action event doesn’t make sense.

Finally, when doing cleanup during the shutdown phase of a charm’s lifecycle, deferring isn’t practical with the current implementation, where it’s tied to future events. For `remove`, for example, the unit will no longer exist after the event, so there will not be any future events that can trigger the deferred one - if there’s work that has to be done before the unit is gone, then you’ll need to enter an error state instead. The stop event is followed by remove, and possibly a few other events, but likewise has few chances to be re-emitted.

Note that all deferred events vanish when the unit is removed, so the charm code needs to take this into consideration.
