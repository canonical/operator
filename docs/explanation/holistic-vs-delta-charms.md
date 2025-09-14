(holistic-vs-delta-charms)=
# Holistic vs delta charms

Stateless charms are more robust. The charming community arrived with two approaches to keep charms mostly stateless: "holistic" and "delta".

- Holistic charms reconcile towards a goal state on every event.
- Delta charms handle each Juju event individually.

Note that processing of some Juju events doesn't lend to this distinction.

## Handling events holistically

A typical holistic charm subscribes the same observer method, often called `_reconcile` to all interesting Juju events.
The event payload is ignored, and reconciliation progresses towards a defined goal state: typically a functional workload configured appropriately and able to interact with the related applications.
This implies that the observer has to scrape the entirety of the Juju state available to the current unit, as well as workload state.
The observer then rewrite the world: updates all the Juju state it can, overwrites the workload configuration and instructs the workload to reload the configuration.

### Why reconcile?

Conceptually, a Juju event informs the unit that a specific thing has changed at a pre-defined level in the Juju event model, while the charm author wants the charm to process unit's logical state at workload's own granularity.

```{list-table}
:header-rows: 1

* - Juju event
  - Unit logical state
* - `config-changed`
  - Configuration is valid and complete
* - `pebble-ready`
  - Workload container is reachable
* - `relation-joined`
  - N+1 consumers expect resources
* - `relation-changed`
  - Consumer requirements are defined
```

Juju provides specific event kinds that signal that one "thing" changed: `config-changed` says that a configuration value has changed, `relation-changed` says that relation data has changed.

However, this only goes so far: `config-changed` doesn't tell the charm which configuration keys have changed or whether configuration has become valid; `relation-changed` doesn't tell the charm how the relation data have changed or whether the data can be parsed.

In addition, the charm may receive an event like `config-changed` before it's ready to handle it, for example, if the container is not yet ready. In such cases, a delta charm may defer the event (effectively storing a small amount of state) or could try to wait for both events to occur using intricate, error-prone custom logic.

The holistic approach side-steps this disparity and applies a single code path, `_reconcile` to all events of interest, which scrapes all of visible state to perform computation, and updates all writeable state.

### Example

```py
def __init__(self, framework: ops.Framework):
    super().__init__(framework)
    self.typed_config = self.load_config(ConfigClass, errors='blocked')
    self.workload = Workload()
    self.foo = FooRequirer()
    self.bar = BarProvider()

    events = [self.on.start, self.on.config_changed, self.on.foo_relation_changed, ...]

    for event in events:
        framework.observe(event, self._reconcile)

def _reconcile(self, event: Any):
    # Initial read
    workload_ready = self.workload.is_ready
    foo_ready = self.foo.is_ready
    bar_ready = self.bar.is_ready
    
    if workload_ready and foo_ready and bar_ready:
        # Read specifics from configuratiom, libraries and the workload
        path = self.typed_config.some_path
        foo_port = self.foo.service_port
        bar_name = self.bar.remote_name
        current_config = self.workload.config
        workload_path = self.workload.special_path

        # Render the outputs
        workload_config = self.render_config(path, foo_port, bar_name)

        # Write to the libraries and the workload
        if workload_config != current_config:
            self.workload.update_config_and_restart(workload_config)
        self.bar.update_foo_port(foo_port)
        self.foo.update_bar_name(bar_name)

    else:
        # Error handling
        ...
```

The reconciler method above has been reduced for clarity, but is representative of the common reconciler pattern.
It consists of three main parts in addition to early checks and error handling: reading the inputs (configuration, workload and Juju state), computing the updates, and writing the output (updating the workload and writing out the Juju state).
Well-written charms include helper methods or classes for the workload and use charm libraries to read and write Juju state on charm's relations.

You may notice that role of a complex charm is to cross-connect configuration, workload and libraries.
In fact, complex charms often use a dozen charm libraries, moving the emphasis towards shovelling data from a set of charm libraries to other charm libraries.

### Details

The reconciler setup attaches the same observer, `self._reconcile` to every interesting Juju event:

- lifecycle start events
- config change event
- most or all relation events
- pebble events
- storage events, if applicable

Pragmatically, most Juju events are opportunities for reconciliation.
Consider relations: if a charm declares a relation, then it's natural to expect that charm's behaviour depends on the databag content in this relation.
Therefore, the reconcile method will most likely read out all the databags for all the apps or units related.
Thus, any event on this relation is subject to running the reconciler loop.

Some events are special, and are better processed outside the reconciler pattern:

- custom events, unless required by a library API
- lifecycle end events
- action events
- secret rotation events
- Ops events, like `update-unit-status`

### Expert reconcilers

Reconciliation happens towards a certain goal state.
For many charms, and for most of the charm's lifecycle, the goal state is the same: a running workload with correct configuration.
Rarely, the goal state may change:

- unit lifecycle end, that is, graceful shutdown
- failover to another unit, leaving this unit on stand-by

Complex charms often split the reconciler method in functional constituents, see [Parca Kubernetes Operator](https://github.com/canonical/parca-k8s-operator/blob/6fda0c9844bc7a45b93ac12806a6ef04036c50c4/src/charm.py#L188-L206) for an example.

Charm libraries too can be written using the reconciler pattern, see [the implementation of `ops.tracing.Tracing`](https://github.com/canonical/operator/blob/af6764fbfdcf8ed42a0edb331870dd9d37dc804b/tracing/ops_tracing/_api.py#L128-L163) for an example.

Some applications, like database or observability providers, are expected to be related to an unbounded number of other applications.
It may become expensive to scrape all the data from the key relation on every hook.
Such applications should be profiled, and, based on the results, the charm developer may cache the Juju state, communicate less on the relation and more out of band, or perhaps reconsider whether this key relation processing could be moved out of the reconciler.
Similar [performance concern](https://discourse.charmhub.io/t/performance-limitations-of-peer-relations-and-a-solution/18144) applies to peer relation processing for applications where hundreds of units may be expected.

### When to use the holistic approach

Charms that implement the reconciler pattern have been proven more robust.
This comes down to two observations:

- The charm author is thinking about their workload more than about minute Juju semantics.
- When the Juju event is taken out of the equation, same number of unit tests covers larger portion of (state, event) space.

At the same time, simple operators can be trivially written as delta charms.
Either of the following hints at suitability of such approach:

- The Juju event model can be mapped directly to the workload semantics.
- The charm is trivial.

See [SSSD Operator](https://github.com/canonical/sssd-operator/blob/9118ecec6e45820f79dda97f6f7dd287a20b39ac/src/charm.py#L44-L69) and [Apache Kafka Rack Awareness Operator](https://github.com/canonical/kafka-broker-rack-awareness-operator/blob/980781a49b6d65e6d4356819c1f3a2c57a0e3625/src/charm.py#L27-L30) for examples of workloads there delta charm is suitable.

## FIXME events exempt from the reconciler pattern

Only some events make sense to handle holistically. For example, `remove` is triggered when a unit is about to be terminated, so it doesn't make sense to handle it holistically.

Similarly, events like `secret-expired` and `secret-rotate` don't make sense to handle holistically, because the charm must do something specific in response to the event. For example, Juju will keep triggering `secret-expired` until the charm creates a new secret revision by calling [`event.secret.set_content()`](ops.Secret.set_content).

This is very closely related to [which events can be deferred](#how-and-when-to-defer-events). A good rule of thumb is this: if an event can be deferred, it may make sense to handle it holistically.

On the other hand, if an event cannot be deferred, the charm cannot handle it holistically. This applies to action "events", `stop`, `remove`, `secret-expired`, `secret-rotate`, and Ops-emitted events such as `collect-status`.

FIXME: since the doc is part of explanation, should I explain briefly why each class of events doesn't belong to the reconciler?

## Handling events individually

* A *delta-based* charm is when the charm handles each kind of Juju hook with a separate handler function, which does the minimum necessary to process that kind of event.

Juju itself nudges charm authors in the direction of delta-based charms, because it provides specific event kinds that signal that one "thing" changed: `config-changed` says that a config value changed, `relation-changed` says that relation data has changed, `pebble-ready` signals that the Pebble container is ready, and so on.

FIXME

Juju itself nudges charm authors in a different direction.
Juju provides specific event kinds that signal that one "thing" changed: `config-changed` says that a configuration value has changed, `relation-changed` says that relation data has changed, `pebble-ready` signals that the Pebble in the workload container has become ready, and so on.

For contrast, a delta charm may look like this:

### Example

```py
def __init__(self, framework: ops.Framework):
    super().__init__(framework)
    self.framework.observe(self.on.start, self._on_start)
    self.framework.observe(self.on.install, self._on_install)

    hostname = socket.getfqdn()
    self.foo = FooRequires(self, "foo-relation", address=hostname)
    self.framework.observe(self.foo.on.data_available, self._on_data_available)

    self.bar = BarProvider(self, "bar-relation")
    self.framework.observe(self.bar.on.create_bar, self._on_create_bar)

def _on_start(self, event: ops.StartEvent):
    # This unit has been started

def _on_install(self, event: ops.InstallEvent):
    # Install the workload binary

def _on_data_available(self, event: DataAvailableEvent):
    # Compte the delta vs. old data, apply to workload

def _on_create_bar(self, CreateBarEvent):
    # A related app has requested a logical bar.
```

## Scrap yard

- [`alertmanager-k8s` uses a `_common_exit_hook` method to unify several event handlers](https://github.com/canonical/alertmanager-k8s-operator/blob/561f1d8eb1dc6e4511c1c0b3cba444a3ec399464/src/charm.py#L390)
- [`hello-kubecon` is a simple charm that handles `config-changed` and `pebble-ready` holistically](https://github.com/jnsgruk/hello-kubecon/blob/dbd133466dde59ee64f20a732a8f3d2e560ec3b8/src/charm.py#L32-L33)
- [`prometheus-k8s` uses a common `_configure` method to handle various events](https://github.com/canonical/prometheus-k8s-operator/blob/84c6a406ed585cdb7ba40e01a258864987d6f67f/src/charm.py#L221-L230)
- [`sdcore-gnbsim-k8s` also uses a common `_configure` method](https://github.com/canonical/sdcore-gnbsim-k8s-operator/blob/ea2afe069346757b1eb6c02de5b4f50f90e81698/src/charm.py#L84-L92)
