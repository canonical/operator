(expose-the-version-of-the-application-behind-your-charm)=
# Expose the version of the application behind your charm

> <small> {ref}`From Zero to Hero: Write your first Kubernetes charm <from-zero-to-hero-write-your-first-kubernetes-charm>` > Expose the version of the application behind your charm </small>
>
> **See previous: {ref}`Make your charm configurable <make-your-charm-configurable>`** 

````{important}

This document is part of a  series, and we recommend you follow it in sequence.  However, you can also jump straight in by checking out the code from the previous branches:

```
git clone https://github.com/canonical/juju-sdk-tutorial-k8s.git
cd juju-sdk-tutorial-k8s
git checkout 02_make_your_charm_configurable
git checkout -b 03_set_workload_version 
```

````

In this chapter of the tutorial you will learn how to expose the version of the application (workload) run by the charm -- something that a charm user might find it useful to know. 


## Define functions to collect the workload application version and set it in the charm

As a first step we need to add two helper functions that will send an HTTP request to our application to get its version. If the container is available, we can send a request using the `requests` Python library and then add class methods to parse the JSON output to get a version string, as shown below:

- Import the `requests` Python library:

```python
import requests
```

- Add the following class methods:


```python
@property
def version(self) -> str:
    """Reports the current workload (FastAPI app) version."""
    try:
        if self.container.get_services(self.pebble_service_name):
            return self._request_version()
    # Catching Exception is not ideal, but we don't care much for the error here, and just
    # default to setting a blank version since there isn't much the admin can do!
    except Exception as e:
        logger.warning("unable to get version from API: %s", str(e), exc_info=True)
    return ""

def _request_version(self) -> str:
    """Helper for fetching the version from the running workload using the API."""
    resp = requests.get(f"http://localhost:{self.config['server-port']}/version", timeout=10)
    return resp.json()["version"]
```

Next, we need to update the `_update_layer_and_restart` method to set our workload version. Insert the following lines before setting `ActiveStatus`:

```python
# Add workload version in Juju status.
self.unit.set_workload_version(self.version)
```

## Declare Python dependencies


Since we've added a third party Python dependency into our project, we need to list it in `requirements.txt`. Edit the file to add the following line:

```
requests~=2.28
```

Next time you run `charmcraft` it will fetch this new dependency into the charm package.


## Validate your charm

We've exposed the workload version behind our charm. Let's test that it's working!

First, repack and refresh your charm:

```text
charmcraft pack
juju refresh \
  --path="./demo-api-charm_ubuntu-22.04-amd64.charm" \
  demo-api-charm --force-units --resource \
  demo-server-image=ghcr.io/canonical/api_demo_server:1.0.1
```

Our charm should fetch the application version and forward it to `juju`. Run `juju status` to check: 

```text
juju status
```

Indeed, the version of our workload is now displayed -- see the App block, the Version column:

```text
Model        Controller           Cloud/Region        Version  SLA          Timestamp
charm-model  tutorial-controller  microk8s/localhost  3.0.0    unsupported  12:37:27+01:00

App             Version  Status  Scale  Charm           Channel  Rev  Address         Exposed  Message
demo-api-charm  1.0.1    active      1  demo-api-charm             0  10.152.183.233  no       

Unit               Workload  Agent  Address      Ports  Message
demo-api-charm/0*  active    idle   10.1.157.75   
```

## Review the final code


For the full code see: [03_set_workload_version](https://github.com/canonical/juju-sdk-tutorial-k8s/tree/03_set_workload_version)

For a comparative view of the code before and after this doc see: [Comparison](https://github.com/canonical/juju-sdk-tutorial-k8s/compare/02_make_your_charm_configurable...03_set_workload_version)


> **See next: {ref}`Integrate your charm with PostgreSQL <integrate-your-charm-with-postgresql>`**


