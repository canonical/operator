---
myst:
  html_meta:
    description: Decide your charm's name and use Charmcraft to generate the recommended project structure.
---

(init-charm)=
# How to initialise your project

Before you initialise your project, install charm development tools. See [](#prepare-your-environment).

This guide demonstrates how to name your charm and generate the recommended project structure. You should decide your charm's name before you create a repository for your charm.

(decide-your-charms-name)=
## Decide your charm's name

Your charm's name should be based on the name of the workload and should be short and memorable. Examples:

- `mega-calendar` for a machine charm that operates a workload called Mega Calendar
- `mega-calendar-k8s` for a Kubernetes charm that operates the same workload

To check that your preferred name isn't already in use, visit the (future) Charmhub URL, which should be an error page:

```text
https://charmhub.io/mega-calendar-k8s
```

There also exists charms that do operate a workload, such as integrators and configurators charms. These two categories serve two different purposes:

* An integrator charm provides the possibility to integrate a service that is not managed via Juju into the Juju model. This can both apply to server side integrations (e.g. `s3-integrator`, that integrates an externally managed s3 object storage) or to client side integration (e.g. `data-integrator`, representing the integration of external client applications that needs a database).

* A configurator charm provides better scalability and centralized logic to further configure for a particular charm or relation that is already in Juju. Examples for this could be `cos-configuration` when it applies to a single charm (e.g. providing more fine-grained configuration the prometheus scraping) or for relation/integration (e.g. `ingress-configurator` as to provide futher configuration of ingresses requests)

Since workload-less charms can equally work on machines and on Kubernetes, when naming integrator charms and configurator charms, avoid using the `k8s` suffix, unless the charm is only relevant for Kubernetes, e.g. managing K8s resources within the charm logic. Use the `integrator` and `configurator` suffix to signal the category of the charm, e.g. `foo-integrator` or `bar-configurator`.

(create-a-repository)=
## Create a repository

Create a repository with your source control of choice.

```{admonition} Best practice
:class: hint

If your charm operates a workload, name the repository `<charm name>-operator`. If your charm doesn't operate a workload (as in the case of integrator charms and configurator charms), the `-operator` suffix is not needed and the repository can be named with the same name of the charm, e.g. `foo-integrator` and `bar-configurator`. Use the plural when `s` the repository contains multiple charms or artefacts (such as rocks).
```

Examples:

- [kafka-operator](https://github.com/canonical/kafka-operator) - Contains a single charm that operates a workload on machine.
- [kafka-k8s-operator](https://github.com/canonical/kafka-k8s-operator) - Contains a single charm that operates a workload on K8s.
- [katib-operators](https://github.com/canonical/katib-operators) - Contains multiple charms.
- [data-integrator](https://github.com/canonical/data-integrator) - Contains a charm that integrates an externally managed service (e.g. client application).
- [s3-integrator](https://github.com/canonical/object-storage-integrators) - Contains multiple charm that integrates externally managed service (e.g. different kind of object storage backends).
- [request-authentication-configurator](https://github.com/canonical/request-authentication-configurator) - Contains a charm that configure Gateway to perform request authentication

(initialise-the-repository)=
## Initialise the repository

Next, use {external+charmcraft:doc}`Charmcraft <index>` to generate the recommended project structure in the repository:

```text
charmcraft init --name mega-calendar-k8s --profile kubernetes
```

Or for a machine charm:

```text
charmcraft init --name mega-calendar --profile machine
```

<!-- Remove this tip when the charmcraft stable version is up-to-date. -->
````{tip}
The `charmcraft` version that you have installed may come with older versions of the profiles.

To use the latest profile versions, initialise your charm using `charmcraft` directly from Github, like this:

```text
uvx git+https://github.com/canonical/charmcraft@74d12bc init --name <name> --profile <profile>
```
````

If you don't specify `--name` when running `charmcraft init`, Charmcraft uses the parent directory name for your charm. For example, `mega-calendar-k8s-operator`, from the name of the repository. So we recommend specifying `--name` to ensure that your charm's name doesn't end with `-operator`.

## Inspect your charm

Charmcraft's `kubernetes` and `machine` profiles are minimal charms that contain placeholder code and configuration.
These profiles also give you starting points for unit tests and integration tests.

Important files to be aware of:

- `charmcraft.yaml` - Metadata about your charm.
- `pyproject.toml` - Python project configuration, including the dependencies of your charm.
- `src/charm.py` - The Python file that will contain the main logic of your charm.

## Next steps

- Start writing your charm code. See {ref}`write-and-structure-charm-code` and our other guides.
- Provide metadata in `charmcraft.yaml`. See {external+charmcraft:ref}`Charmcraft | Configure package information <configure-package-information>`.

If your charm's workload was built with a web framework such as Django or FastAPI, consider using one of Charmcraft's 12-factor app profiles instead of `kubernetes` or `machine`. These profiles accelerate development by generating charms that are ready to deploy. {external+charmcraft:ref}`Write your first 12-factor app charm <tutorial>`.
