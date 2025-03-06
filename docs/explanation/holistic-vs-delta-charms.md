(holistic-vs-delta-charms)=
# Holistic vs delta charms


Charm developers have had many discussion about "holistic" charms compared to "delta" charms, and which approach is better. First, let's define those terms:

* A *delta-based* charm is when the charm handles each kind of Juju hook with a separate handler function, which does the minimum necessary to process that kind of event.
* A *holistic* charm handles some or all Juju hooks using a common code path such as `_update_charm`, which queries the charm config and relation data and "rewrites the world", that is, rewrites application configuration and restarts necessary services.

Juju itself nudges charm authors in the direction of delta-based charms, because it provides specific event kinds that signal that one "thing" changed: `config-changed` says that a config value changed, `relation-changed` says that relation data has changed, `pebble-ready` signals that the Pebble container is ready, and so on.

However, this only goes so far: `config-changed` doesn't tell the charm which config keys changed, and `relation-changed` doesn't tell the charm how the relation data changed.

In addition, the charm may receive an event like `config-changed` before it's ready to handle it, for example, if the container is not yet ready (`pebble-ready` has not yet been triggered). In such cases, charms could try to wait for both events to occur, possibly storing state to track which events have occurred -- but that is error-prone.

Alternatively, a charm can use a holistic approach and handle both `config-changed` and `pebble-ready` with a single code path, as in this example:

```python
class MyCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on.config_changed, self._update_charm)
        framework.observe(self.on['redis'].pebble_ready, self._update_charm)

    def _update_charm(self, _: ops.EventBase):  # event parameter isn't used
        redis_port = self.config.get('redis-port')
        if not redis_port:
            # pebble-ready happened first, wait for config-changed
            return

        # If both the Pebble container and config are ready, rewrite the
        # container's config file and restart Redis if needed.
        container = self.unit.get_container('redis')
        try:
	        self._update_redis_config(container, redis_port)
	    except ops.pebble.ConnectionError:
	    	# config-changed happened first, wait for pebble-ready
            return
```


## When to use the holistic approach

If a charm is waiting for a collection of events, as in the example above, it makes sense to group those events together and handle them holistically, with a single code path.

In other words, when writing a charm, it's not so much "should the *charm* be holistic?" as "does it make sense for *these events* to be handled holistically?"

Using the holistic approach is normally centred around configuring an application. Various events that affect configuration use a common handler, to simplify writing an application config file and restarting the application.  This is common for events like `config-changed`, `relation-changed`, `secret-changed`, and `pebble-ready`.

Many existing charms use holistic event handling. A few examples are:

- [`alertmanager-k8s` uses a `_common_exit_hook` method to unify several event handlers](https://github.com/canonical/alertmanager-k8s-operator/blob/561f1d8eb1dc6e4511c1c0b3cba444a3ec399464/src/charm.py#L390)
- [`hello-kubecon` is a simple charm that handles `config-changed` and `pebble-cready` holistically](https://github.com/jnsgruk/hello-kubecon/blob/dbd133466dde59ee64f20a732a8f3d2e560ec3b8/src/charm.py#L32-L33)
- [`prometheus-k8s` uses a common `_configure` method to handle various events](https://github.com/canonical/prometheus-k8s-operator/blob/84c6a406ed585cdb7ba40e01a258864987d6f67f/src/charm.py#L221-L230)
- [`sdcore-gnbsim-k8s` also uses a common `_configure` method](https://github.com/canonical/sdcore-gnbsim-k8s-operator/blob/ea2afe069346757b1eb6c02de5b4f50f90e81698/src/charm.py#L84-L92)


## Which events can be handled holistically?

Only some events make sense to handle holistically. For example, `remove` is triggered when a unit is about to be terminated, so it doesn't make sense to handle it holistically.

Similarly, events like `secret-expired` and `secret-rotate` don't make sense to handle holistically, because the charm must do something specific in response to the event. For example, Juju will keep triggering `secret-expired` until the charm creates a new secret revision by calling [`event.secret.set_content()`](ops.Secret.set_content).

This is very closely related to [which events can be deferred](/explanation/how-and-when-to-defer-events). A good rule of thumb is this: if an event can be deferred, it may make sense to handle it holistically.

On the other hand, if an event cannot be deferred, the charm cannot handle it holistically. This applies to action "events", `stop`, `remove`, `secret-expired`, `secret-rotate`, and Ops-emitted events such as `collect-status`.