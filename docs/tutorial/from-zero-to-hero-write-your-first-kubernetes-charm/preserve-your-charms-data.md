(preserve-your-charms-data)=
# Preserve your charm's data

> <small> {ref}`From Zero to Hero: Write your first Kubernetes charm <from-zero-to-hero-write-your-first-kubernetes-charm>` > Preserve your charm's data </small>
>
> **See previous: {ref}`Integrate your charm with PostgreSQL <integrate-your-charm-with-postgresql>`** 


````{important}

This document is part of a  series, and we recommend you follow it in sequence.  However, you can also jump straight in by checking out the code from the previous branches:

```bash
git clone https://github.com/canonical/juju-sdk-tutorial-k8s.git
cd juju-sdk-tutorial-k8s
git checkout 04_integrate_with_psql
git checkout -b  05_preserve_charm_data
```

````


Charms are stateless applications. That is, they are reinitialised for every event and do not retain information from previous executions. This means that, if an accident occurs and the Kubernetes pod dies, you will also lose any information you may have collected. 

In many cases that is not a problem. However, there are situations where it may be necessary to maintain information from previous runs and to retain the state of the application. As a charm author you should thus know how to preserve state.

There are a  few strategies you can adopt here:

First, you can use an Ops construct called `Stored State`. With this strategy you can store data on the local unit (at least, so long as your `main` function doesn't set `use_juju_for_storage` to `True`). However, if your Kubernetes pod dies, your unit also dies, and thus also the data. For this reason this strategy is generally not recommended.

> Read more: {ref}`StoredState <7433md>`, {ref}`StoredState: Uses, Limitations <storedstate-uses-limitations>`

Second, you can make use of the Juju notion of 'peer relations'  and 'data bags'  and set up a peer relation data bag. This will help you store the information in the Juju's database backend. 

> Read more: [Peer integrations](https://juju.is/docs/juju/relation#heading--peer)

Third, when you have confidential data, you can use Juju secrets (from Juju 3.1 onwards).

> Read more: [Juju | Secret](https://juju.is/docs/juju/secret)

In this chapter we will adopt the second strategy, that is, we will store charm data in a peer relation databag. (We will explore the third strategy in a different scenario in the next chapter.)  We will illustrate this strategy with an artificial example where we save the counter of how many times the application pod has been restarted.

## Define a peer relation

The first thing you need to do is define a peer relation. Update the `charmcraft.yaml` file to add a `peers` block before the `requires` block, as below (where `fastapi-peer` is a custom name for the peer relation and `fastapi_demo_peers` is a custom name for the peer relation interface): 

```yaml
peers:
  fastapi-peer:
    interface: fastapi_demo_peers
```
> Read more: {ref}`File ‘charmcraft.yaml’ <7433md>`

## Set and get data from the peer relation databag

Now, you need a way to set and get data from the peer relation databag. For that you need to update the `src/charm.py` file as follows:

First, define some helper methods that will allow you to read and write from the peer relation databag:

```python
@property
def peers(self) -> Optional[ops.Relation]:
    """Fetch the peer relation."""
    return self.model.get_relation(PEER_NAME)

def set_peer_data(self, key: str, data: JSONData) -> None:
    """Put information into the peer data bucket instead of `StoredState`."""
    peers = cast(ops.Relation, self.peers)
    peers.data[self.app][key] = json.dumps(data)

def get_peer_data(self, key: str) -> Dict[str, JSONData]:
    """Retrieve information from the peer data bucket instead of `StoredState`."""
    if not self.peers:
        return {}
    data = self.peers.data[self.app].get(key, '')
    if not data:
        return {}
    return json.loads(data)
```

This block uses the built-in `json` module of Python, so you need to import that as well. You also need to define a global variable called `PEER_NAME = "fastapi-peer"`, to match the name of the peer relation defined in `charmcraft.yaml` file. We'll also need to import some additional types from `typing`, and define a type alias for JSON data. Update your imports to include the following:

```python
import json
from typing import Dict, List, Optional, Union, cast
```
Then define our global and type alias as follows:

```python
PEER_NAME = 'fastapi-peer'

JSONData = Union[
    Dict[str, 'JSONData'],
    List['JSONData'],
    str,
    int,
    float,
    bool,
    None,
]
```

Next, you need to add a method that updates a counter for the number of times a Kubernetes pod has been started. Let's make it retrieve the current count of pod starts from the 'unit_stats' peer relation data, increment the count, and then update the 'unit_stats' data with the new count, as below:

```python
def _count(self, event: ops.StartEvent) -> None:
    """This function updates a counter for the number of times a K8s pod has been started.

    It retrieves the current count of pod starts from the 'unit_stats' peer relation data,
    increments the count, and then updates the 'unit_stats' data with the new count.
    """
    unit_stats = self.get_peer_data('unit_stats')
    counter = cast(str, unit_stats.get('started_counter', '0'))
    self.set_peer_data('unit_stats', {'started_counter': int(counter) + 1})
```

Finally, you need to call this method and update the peer relation data every time the pod is started. For that, define another event observer in the `__init__` method, as below:

```python
framework.observe(self.on.start, self._count)
```

## Validate your charm

First, repack and refresh your charm:

```bash
charmcraft pack
juju refresh \
  --path="./demo-api-charm_ubuntu-22.04-amd64.charm" \
  demo-api-charm --force-units --resource \
  demo-server-image=ghcr.io/canonical/api_demo_server:1.0.1
```


Next, run `juju status` to make sure the application is refreshed and started, then investigate the relation data as below:

```bash
juju show-unit demo-api-charm/0
```

The output should include the following lines related to our peer relation:

```bash
  relation-info:
  - relation-id: 25
    endpoint: fastapi-peer
    related-endpoint: fastapi-peer
    application-data:
      unit_stats: '{"started_counter": 1}'
```

Now, simulate a Kubernetes pod crash by deleting the charm pod:

```bash
microk8s kubectl --namespace=charm-model delete pod demo-api-charm-0
```

Finally, check the peer relation again. You should see that the `started_counter` has been incremented by one. Good job, you've preserved your application data across restarts!

## Review the final code


For the full code see: [05_preserve_charm_data](https://github.com/canonical/juju-sdk-tutorial-k8s/tree/05_preserve_charm_data)

For a comparative view of the code before and after this doc see: [Comparison](https://github.com/canonical/juju-sdk-tutorial-k8s/compare/04_integrate_with_psql...05_preserve_charm_data)


> **See next: {ref}`Expose your charm's operational tasks via actions <expose-operational-tasks-via-actions>`**

