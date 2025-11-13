(holistic-vs-delta-charms)=
# Holistic vs delta charms

The charming community has developed two approaches to writing robust, stateless charms: "holistic" and "delta".

- Holistic charms reconcile towards a goal state on every event.
- Delta charms handle each Juju event individually.

## Handling events holistically

A typical holistic charm subscribes the same observer method, often called `_reconcile`, to all interesting Juju events.
The event payload is ignored, and reconciliation progresses towards a defined goal state: typically a functional workload configured appropriately and able to interact with the related applications.

This implies that a holistic charm has to fetch all the state it needs: the state of the current unit, and any workload state.
The observer then "rewrites the world": updates all the Juju state it needs to, overwrites the workload configuration, and instructs the workload to reload its configuration.

### Why reconcile?

Conceptually, a Juju event informs the unit that a specific thing has changed in the Juju event model, while the charm author wants the charm to process a unit's logical state at the workload's own granularity. For example:

```{list-table}
:header-rows: 1

* - Juju event
  - Unit logical state
* - `config-changed`
  - Configuration is valid and complete
* - `pebble-ready`
  - Workload container is reachable
* - `relation-joined`
  - The set of consumers requires provisioning
* - `relation-changed`
  - Consumer requirements are defined
```

Juju provides specific event kinds that signal that one "thing" changed: `config-changed` says that one or more configuration values have changed, `relation-changed` says that relation data has changed.

However, this only goes so far.
The `config-changed` event doesn't tell the charm which configuration keys have changed.
The `relation-changed` event doesn't tell the charm how the relation data has changed.

In addition, the charm may receive an event like `config-changed` before it's ready to handle it, for example, if the container is not yet ready.
In such cases, a delta charm may defer the event, effectively storing a small amount of state, or have both `config-changed` and `pebble-ready` check if everything is ready and then run the common code, which is the first step towards a holistic approach.

The holistic approach side-steps this disparity and applies a single code path, `_reconcile`, to all events of interest.
The code path reads all state it needs to perform computation, and updates all writable state.

### Example

The reconciler method below has been reduced for clarity, but is representative of the common reconciler pattern.

The body of the reconciler method comprises three main parts:

- reading the inputs (configuration, workload, and Juju environment state)
- computing the new state
- writing the output (updating the workload and writing environment state)

```py
# Read the inputs
path = self.typed_config.some_path
foo_value = self.foo_requirer.some_relation_property
bar_value = self.bar_provider.some_relation_property
current_config = self.workload.config

# Compute the new state
workload_config = self.render_config(path, foo_value, bar_value)

# Write the outputs
if workload_config != current_config:
    self.workload.update_config_and_restart(workload_config)
self.foo_requirer.update_some_relation_field(bar_value)
self.bar_provider.update_some_relation_field(foo_value)
```

Well-written charms include helper methods or classes for the workload and use charm libraries to read and write environment state on relations.

You may notice that the role of a complex charm is to cross-connect configuration, workload and libraries.
In fact, complex charms often use many charm libraries, moving the emphasis towards shovelling data from a set of charm libraries to other charm libraries.

The rest of the charm is mostly scaffolding:

- observing all events of interest
- early checks, ensuring that reconciliation is possible
- handling errors and reporting unit status

```py
def __init__(self, framework: ops.Framework):
    super().__init__(framework)
    self.typed_config = self.load_config(ConfigClass, errors='blocked')
    self.workload = Workload()
    self.foo_requirer = FooRequirer()
    self.bar_provider = BarProvider()

    events = [
        self.on.start,
        self.on.config_changed,
        self.on['foo-relation'].relation_changed,
        self.on['bar-relation'].relation_changed,
        ...
    ]

    for event in events:
        framework.observe(event, self._reconcile)

def _reconcile(self, _: ops.EventBase):
    # Early checks
    workload_ready = self.workload.is_ready
    foo_ready = self.foo_requirer.is_ready
    bar_ready = self.bar_provider.is_ready

    if not workload_ready or not foo_ready or not bar_ready:
        # Status will be set in `_on_collect_unit_status`
        return

    try:
        # 1. Read the inputs: configuration, libraries and the workload
        # 2. Compute the new state
        # 3. Write the outputs to the libraries and the workload
        ...
    except (WorkloadError, FooError, BarError, ops.ModelError, ...):
        # Error handling
        ...
```

### Expert reconcilers

Reconciliation happens towards a certain goal state.
For many charms, and for most of the charm's lifecycle, the goal state is the same: a running workload with correct configuration.
Rarely, the goal state may change:

- unit lifecycle end, that is, graceful shutdown
- failover to another unit, leaving this unit on stand-by

Complex charms often split the reconciler method into functional constituents. See the [Parca Kubernetes Operator](https://github.com/canonical/parca-k8s-operator/blob/6fda0c9844bc7a45b93ac12806a6ef04036c50c4/src/charm.py#L188-L206) for an example.

Charm libraries too can be written using the reconciler pattern. See [the implementation of `ops.tracing.Tracing`](https://github.com/canonical/operator/blob/af6764fbfdcf8ed42a0edb331870dd9d37dc804b/tracing/ops_tracing/_api.py#L128-L163) for an example.

Some applications, like database or observability providers, are expected to be related to an unbounded number of other applications.
It may become expensive to scrape all the data from that relation on every hook.

If you're developing such an application, you should profile the application. Based on the results, you might cache the Juju state, communicate less on the relation and [more out of band](https://github.com/charmed-hpc/slurm-charms/blob/edc47369560845fa54f81a2f02e0a3870b14302a/charms/slurmrestd/src/charm.py#L93-L98), or reconsider whether this key relation processing could be moved out of the reconciliation loop.
Similar [performance concerns](https://discourse.charmhub.io/t/performance-limitations-of-peer-relations-and-a-solution/18144) apply to peer relation processing for applications where hundreds of units may be expected.

## Handling events individually

A delta-based charm is when the charm handles each kind of Juju hook with a separate handler function, which does the minimum necessary to process that kind of event.

Juju itself nudges charm authors in this direction.
Juju provides specific event kinds that signal that one "thing" changed: `config-changed` says that one or more configuration values have changed, `relation-changed` says that relation data has changed, `pebble-ready` signals that the Pebble in the workload container has become ready, and so on.

### Example

```py
def __init__(self, framework: ops.Framework):
    super().__init__(framework)
    self.workload = Workload()
    self.framework.observe(self.on.install, self._on_install)
    self.framework.observe(self.on.start, self._on_start)

    hostname = socket.getfqdn()
    self.foo_requirer = FooRequirer(self, "foo-relation", address=hostname)
    self.framework.observe(
        self.foo_requirer.on.data_available,
        self._on_data_available,
    )

    self.bar_provider = BarProvider(self, "bar-relation")
    self.framework.observe(
        self.bar_provider.on.create_bar,
        self._on_create_bar,
    )

def _on_install(self, event: ops.InstallEvent):
    self.workload.install_binaries()

def _on_start(self, event: ops.StartEvent):
    self.workload.start_service()
    # Peer relation is now usable
    if self.unit.is_leader():
        ...

def _on_data_available(self, event: DataAvailableEvent):
    # Update the workload with event's data
    self.workload.reconfigure(some_key=event.some_value)

def _on_create_bar(self, event: CreateBarEvent):
    # Provision a `Bar` resource in the workload
    self.workload.create_bar(event.some_field)
```

Notice how the handler methods map to Juju and custom events directly.
There's less boilerplate and flow control is predictable.

### Developing your charm

However, the charm code and tests can get messy when dependencies between events are accounted for:

- creating a resource is only possible after the workload has been installed
- the available data typically needs to be mixed with application's configuration
- cases where something is inferred from the sequence of events (see {external+juju:ref}`Juju | Hook ordering <hook>`)

A good rule of thumb is this: if you're starting to use `defer` in various places, consider whether it's time to rewrite the charm using the reconciler pattern.

## Which approach to use?

At a high level, simple workloads are served well by delta charms.
Complex workloads are more robust if the reconciler pattern is followed.
The reconciler pattern is especially suitable for mature, feature-rich charms that use several charm libraries.

### Dedicated handlers for specific Juju events

Some events are special, and are typically processed outside the reconciler pattern in holistic charms.
In both styles of charms a dedicated event handler is used for:

- unit lifecycle end events, `stop`, and `remove`, because the goal of reconciliation is different
- action events, as these are synchronous, and the [](ops.ActionEvent) object holds arguments and results
- the `secret-rotate` event, where a secret must be modified synchronously
- the `secret-remove` event, because the revision that needs removal is not available otherwise
- the `secret-expired` event, as the expired secret must be retired or deleted
- Ops lifecycle events, like `on.collect_unit_status`, which accompany the Juju event
- some custom events, if a specific charm library API is not suited for reconciliation

A good rule of thumb is this: if an event [cannot be deferred](#how-and-when-to-defer-events), it needs a dedicated handler.

### Events observed by the reconcile method

A holistic charm attaches the same observer to a group of events.
In a charm following the reconciler pattern, the `_reconcile` method is attached to every interesting Juju event:

- the `install` and `start` events
- the `config-changed` event
- most or all relation events
- Pebble events
- storage events
- the `secret-changed` event
- the `upgrade-charm` event
- the `update-status` event

Consider relations: if a charm declares a relation, it's natural to expect that this unit's behaviour or the remote app behaviour depends on the databag content of the relation.
Therefore, the reconcile method has to read the relation data to apply the latest data, or overwrite its own databag with the latest computed data.
Thus, the reconciler loop ought to run for every event on this relation.
Following the same logic, the reconciler loop ought to run for every configuration, storage, and container event.

### When to use the holistic approach

Several charming teams at Canonical have found that using the reconciler pattern makes a charm more robust.
This comes down to two observations:

- The charm author is thinking about their workload more than about minute Juju semantics.
- When the Juju event is taken out of the equation, the same number of unit tests covers a larger portion of state and event space.

### When to use the delta approach

A delta approach is most appropriate when the Juju event model can be mapped directly to the workload semantics. Simple operators can typically be written as delta charms.

See [SSSD Operator](https://github.com/canonical/sssd-operator/blob/9118ecec6e45820f79dda97f6f7dd287a20b39ac/src/charm.py#L44-L69) and [Apache Kafka Rack Awareness Operator](https://github.com/canonical/kafka-broker-rack-awareness-operator/blob/980781a49b6d65e6d4356819c1f3a2c57a0e3625/src/charm.py#L27-L30) for examples of workloads where a delta charm is suitable. Notably, machine charms map to the delta model more readily than Kubernetes charms.
