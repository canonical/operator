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

Make sure that your charm's name only contains ASCII lowercase letters, numbers, and hyphens.

The general naming pattern is `<workload name>[-<function>][-k8s]`, where `<function>` could be `server`, `dashboard`, and so on.

Don't add an `operator` or `charm` prefix/suffix. Don't include an organisation or publisher name.

### Charms without a workload

Some charms do not operate a workload, such as integrator and configurator charms. These categories serve different purposes:

* An integrator charm allows integration with a service that is not managed through Juju. This can both apply to server side integrations (such as `s3-integrator`, which integrates an externally managed S3 object storage) or to client side integrations (such as `data-integrator`, representing the integration of external client application that needs a database).

* A configurator charm provides logic to configure a particular charm or relation that is already in Juju. Examples include `cos-configuration` when it applies to a single charm (such as providing more fine-grained configuration of the Prometheus scraping) or for a relation (such as `ingress-configurator` to provide additional configuration of ingress requests).

When naming your charm, use `-integrator` and `-configurator` to signal the category. For example, `foo-integrator` or `bar-configurator`.

### Kubernetes charms

The `k8s` suffix is for disambiguation, not classification. Only use `-k8s` in the name of a Kubernetes charm if there is (or could be in the future) a machine variant of your charm.

For example, a charm that manages Kubernetes resources with `lightkube` shouldn't use `-k8s` in the name, as the charm is inherently tied to Kubernetes.

Don't use `-k8s` for workload-less charms. These charms work on machines and Kubernetes.

(create-a-repository)=
## Create a repository

Create a repository with your source control of choice.

```{admonition} Best practice
:class: hint

If your charm operates a workload, name the repository `<charm name>-operator`. For advice about the charm name, see [](#decide-your-charms-name). If your charm doesn't operate a workload (as in the case of integrator charms and configurator charms), the `-operator` suffix isn't needed. For example, `foo-integrator` and `bar-configurator`.

Repositories that contain multiple charms or one or more charms and other artefacts (like rocks) will need to use other naming patterns.
```

Examples:

- [kafka-operator](https://github.com/canonical/kafka-operator) - Contains a single charm that operates a machine workload.
- [kafka-k8s-operator](https://github.com/canonical/kafka-k8s-operator) - Contains a single charm that operates a K8s workload.
- [katib-operators](https://github.com/canonical/katib-operators) - Contains multiple charms.
- [data-integrator](https://github.com/canonical/data-integrator) - Contains a charm that integrates an externally managed service (such as a client application).
- [s3-integrator](https://github.com/canonical/object-storage-integrators) - Contains multiple charms that integrate an externally managed service (such as different kinds of object storage backends).
- [request-authentication-configurator](https://github.com/canonical/request-authentication-configurator) - Contains a charm that configures Gateway to perform request authentication.

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
