(storedstate-uses-limitations)=
# StoredState: Uses, Limitations

... and why charm authors should avoid state when they can.

## Purpose of this doc

This is an explanatory doc covering how charm authors might track local state in a Juju unit. We'll cover the `ops` concept of [](ops.StoredState), along with some differences in how it works between machine charms and Kubernetes charms. We'll talk about Peer Relations as an alternative for storing some kinds of information, and also talk about how charm authors probably should avoid recording state when they can avoid doing so.

> See more: {external+juju:ref}`Peer Relations <manage-relations>`

## A trivial example

We'll begin by setting up a simple scenario. A charm author would like to charm up a (made up) service called `ExampleBlog`. The ideal cloud service is stateless and immutable, but `ExampleBlog` has some state: it can run in either a `production` mode or a `test` mode.

The standard way to set ExampleBlog's mode is to write either the string `test` or `production` to `/etc/example_blog/mode`, then restart the service. Leaving aside whether this is *advisable* behavior, this is how `ExampleBlog` works, and an `ExampleBlog` veteran user would expect a `ExampleBlog` charm to allow them to toggle modes by writing to that config file. (I sense a patch to upstream brewing, but let's assume, for our example, that we can't dynamically load the config).

Here's a simplified charm code snippet that will allow us to toggle the state of an already running instance of `ExampleBlog`.

```python
def _on_config_changed(self, event: ops.ConfigChangedEvent):
    mode = self.config['mode']
    if mode not in ('production', 'test'):
        self.unit.status = ops.BlockedStatus(f'Invalid mode: {mode!r})
        return

    with open('/etc/example_blog/mode', 'w') as mode_file:
        mode_file.write(f'{mode}\n')

    self._restart()
```

Assume that `_restart` does something sensible to restart the service -- for example, calls `service_restart` from the [systemd](https://charmhub.io/operator-libs-linux/libraries/systemd) library in a machine version of this charm.

## A problematic solution

The problem with the code as written is that the `ExampleBlog` daemon will restart every time the `config-changed` hook fires. That's definitely unwanted downtime! We might be tempted to solve the issue with `StoredState`:

```python
def __init__(self, framework: ops.Framework):
    super().__init__(framework)
    framework.observe(self.on.config_changed, self._on_config_changed)
    self._stored.set_default(current_mode='test')

def _on_config_changed(self, event):
    mode = self.config['mode']
    if self._stored.current_mode == mode:
        return
    if mode not in ('production', 'test'):
        self.unit.status = ops.BlockedStatus(f'Invalid mode: {mode!r})
        return

    with open('/etc/example_blog/mode', 'w') as mode_file:
        mode_file.write('{}\n'.format(mode)

    self._restart()

    self._stored.current_mode = mode
```

We advise against doing this. We have added one to the list of places that attempt to track `ExampleBlog`'s "mode". In addition to the config file on disk, the Juju config, and the actual state of the running code, we've added a fourth "instance" of the state: `current_mode` in our `StoredState` object. We've doubled the number of possible states of this part of the system from 8 to 16, without increasing the number of correct states. There are still only two: all set to `test`, or all set to `production`. We have essentially halved the reliability of this part of our code.

## Differences in StoredState behaviour across substrates

Let's say the charm is running on Kubernetes, and the container it is running in gets destroyed and recreated. This might happen due to events outside of an operator's control -- perhaps the underlying Kubernetes service rescheduled the pod, for example. In this scenario the `StoredState` will go away, and the flags will be reset.

Do you see the bug in our example code? We could fix it by setting the initial value in our `StoredState` to something other than `test` or `production`. E.g., `self._stored.set_default(current_mode="unset")`. This will never match the actual intended state, and we'll thus always invoke the code path that loads the operator's intended state after a pod restart, and write that to the new local disk.

## Practical suggestions and solutions

_Most of the time, charm authors should not track state in a charm._

More specifically, authors should only use `StoredState` when they are certain that the charm can handle any cache consistency issues, and that tracking the state is actually saving a significant number of unneeded CPU cycles.

In our example code, for instance, we might think about the fact that `config_changed` hooks, even in a busy cloud, fire with a frequency measured in seconds. It's not particularly expensive to read the contents of a small file every few seconds, and so we might implement the following, which is stateless (or at least, does not hold state in the charm):

```python
def _on_config_changed(self, event: ops.ConfigChangedEvent):
    mode = self.config['mode']
    if mode not in ('production', 'test'):
        self.unit.status = ops.BlockedStatus(f'Invalid mode: {mode!r})
        return

    with open('/etc/example_blog/mode') as mode_file:
        prev_mode = mode_file.read().strip()
    if mode == prev_mode:
        return

    with open('/etc/example_blog/mode', 'w') as mode_file:
        mode_file.write(f'{mode}\n')

    self._restart()
```

One common scenario where charm authors get tempted to use `StoredState` is to track the occurrence of certain events like [](ops.PebbleReadyEvent). This is dangerous. The emission of a `pebble-ready` event means that Pebble was up and running when the hook was invoked, but makes no guarantees about the future. Pebble may not remain running -- see the note about the Kubernetes scheduler above -- meaning your `StoredState` contains an invalid cache value which will likely lead to bugs. In cases where charm authors want to perform an action if and only if the workload container is up and running, they should guard against Pebble issues by catching [](ops.pebble.ConnectionError):

```python
def some_event_handler(event):
    try:
        self.do_thing_that_assumes_container_running()
    except ops.pebble.ConnectionError:
        event.defer()
        return
```

In the other cases where state is needed, authors ideally want to integrate a charm with a database, attach storage (see Juju storage), or simply be opinionated, and hard code the single "correct" state into the charm. (Perhaps `ExampleBlog` should always be run in `production` mode when deployed as a charm?)

> See more: {external+juju:ref}`Juju Storage <manage-storage>`

In the cases where it is important to share some lightweight configuration data between units of an application, charm author's should look into peer relations. And in the cases where data must be written to a container's local file system (Canonical's Kubeflow bundle, for example, must do this, because the sheer number of services mean that we run into limitations on attached storage in the underlying cloud), authors should do so mindfully, with an understanding of the pitfalls involved.

> See more: {external+juju:ref}`Peer Relations <manage-relations>`

In sum: use state mindfully, with well chosen tools, only when necessary.
