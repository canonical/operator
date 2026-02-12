(manage-containers)=
# How to manage containers

Kubernetes charms use {external+pebble:doc}`Pebble <index>` to manage containers. These guides walk you through the Ops API for interacting with Pebble.

## Managing a Kubernetes workload

Your charm manages the workload by defining the Pebble service configuration. Your charm can also use Pebble to run commands and read and write files in the workload container.

```{toctree}
:maxdepth: 1

Manage the workload container <manage-the-workload-container>
Manage files in the workload container <manage-files-in-the-workload-container>
```

## Monitoring the workload

Pebble can regularly check that the workload is healthy and report back to your charm.

```{toctree}
:maxdepth: 1

Manage Pebble health checks <manage-pebble-health-checks>
```

Custom notices enable the workload to tell your charm that something has happened.

```{toctree}
:maxdepth: 1

Manage Pebble custom notices <manage-pebble-custom-notices>
```

Your charm can configure Pebble so that you can access metrics for services and health checks.

```{toctree}
:maxdepth: 1

Manage Pebble metrics <manage-pebble-metrics>
```
