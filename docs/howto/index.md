(how-to-guides)=
# How-to guides

These guides walk you through writing charms using Ops.

## Managing charms

As you write your charm, you'll use tools and resources from around the charming ecosystem.

```{toctree}
:maxdepth: 1

Manage charms <manage-charms>
```

## Writing charm code

Your charm is Python code that depends on Ops, with standard structures for handling events, status, and errors. As you write your charm, make sure to follow best practices.

```{toctree}
:maxdepth: 1

Write and structure charm code <write-and-structure-charm-code>
```

## Writing tests

Unit tests check that your charm correctly handles simulated events from Juju.

```{toctree}
:maxdepth: 1

Write unit tests for a charm <write-unit-tests-for-a-charm>
```

Integration tests check that your charm works correctly when deployed to a real Juju model.

```{toctree}
:maxdepth: 1

Write integration tests for a charm <write-integration-tests-for-a-charm>
```

## Logging

Ops enables your charm to output logs to the Juju logs.

```{toctree}
:maxdepth: 1

Log from your charm <log-from-your-charm>
```

## Running workloads

Your charm is responsible for interacting with a workload.

```{toctree}
:maxdepth: 1

Run workloads with a machine charm <run-workloads-with-a-charm-machines>
Run workloads with a Kubernetes charm <run-workloads-with-a-charm-kubernetes>
```

## Managing features

Ops features broadly map to Juju features.

```{toctree}
:maxdepth: 1

Manage storage <manage-storage>
Manage resources <manage-resources>
Manage actions <manage-actions>
Manage configuration <manage-configuration>
Manage relations <manage-relations>
Manage leadership changes <manage-leadership-changes>
Manage libraries <manage-libraries>
Manage interfaces <manage-interfaces>
Manage secrets <manage-secrets>
Manage stored state <manage-stored-state>
Manage opened ports <manage-opened-ports>
Manage the charm version <manage-the-charm-version>
Manage the workload version <manage-the-workload-version>
Manage metrics <manage-metrics>
```

## Tracing

Ops enables you to trace your charm code and send data to sources such as the [Canonical Observability Stack](https://documentation.ubuntu.com/observability/).

```{toctree}
:maxdepth: 1

Trace your charm <trace-your-charm>
```

## Charmhub listing

Once your charm is ready for wide production use, your next goal should be to get it publicly listed on Charmhub, so that it is visible in searches.

```{toctree}
:maxdepth: 1

Make your charm discoverable <make-your-charm-discoverable>
```

## Legacy guides

```{toctree}
:hidden:

legacy/index
```

Harness is a deprecated framework for writing unit tests. You should migrate to state-transition tests.

- {doc}`legacy/migrate-unit-tests-from-harness`

Hooks-based charms use script files instead of Python code with Ops. This isn't a recommended way of writing charms, so you should migrate to Ops.

- {doc}`legacy/turn-a-hooks-based-charm-into-an-ops-charm`
