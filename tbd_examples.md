# Examples of common operations in a charm

## Configuration

Configuration can be accesed on the `config` object of the `model`
property on the charm object. On first access it will run `juju
config-get`, and cache the results transparently.

<details><summary>Example</summary>

```python
from ops.charm import CharmBase

class MyCharm(CharmBase):
    # ...

    def on_some_event(self, event):
        if self.model.config['foo'] == 'xyzzy':
            # yak yak yak
```
</details>

### Handling changes to configuration

Configuration changes are reported via a `ConfigChangedEvent`, as
expected.

<details><summary>Example</summary>

```python
from ops.charm import CharmBase

class MyCharm(CharmBase):
    # ...
    
    def on_config_changed(self, event):
        # self.model.config will already have the new values
```
</details>

### Validate configuration, blocking charm until fixed

If the charm has a way to validate its config, it can do that and set
the charm's status to blocked if it fails.

<details><summary>Example</summary>

```python
from ops.charm import CharmBase
from ops.model import BlockedStatus

class MyCharm(CharmBase):
    # ...
    
    def on_config_changed(self, event):
        try:
            # call my custom validator that raises a custom exception on error
            self._validate_config()
        except MyValidationError as e:
            self.status = BlockedStatus("fix yo stuff: {}".format(e))
```
</details>

## Writing to juju logs

The operator framework ties together Python's standard library's
logging facility with juju's. Logging should just work™ (file bugs).

> ⚠️The tieing-together is done in the framework's `main`; if you somehow
> manage to not use that, you need to reimplement that for it to work.

<details><summary>Example</summary>

```python
from ops.charm import CharmBase

import logging

logger = logging.getLogger()

class MyCharm(CharmBase):
    # ...
    
    def on_frobnicated(self, event):
        logger.warning("'tis the end of times")
```
</details>

## Relation data

<details><summary>Example</summary>

```python

```
</details>

### Getting relation data

### Setting relation data

### Getting subordinate/juju-info relation data

## Determining if the unit is the application “leader”

## Changing “leader” settings

## Rendering a pod spec (for k8s charms)

## Simple actions:

### Decoupled from charm, such as triggering a backup

### Coupled to charm state, such as shutting down the service (charm needs to know so it doesn’t restart it)

## Getting network information

### IP address for daemons to listen on

### IP address to publish to clients

## Open/Close ports [not implemented yet]

## Use of shared code and libraries

### How shared code extends config.yaml, metadata.yaml, actions.yaml

### How to embed Python dependencies from pypi (ie. reactive wheelhouse)

## Storage
