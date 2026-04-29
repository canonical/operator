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
(create-a-repository-and-initialise-it)=
## Create a repository and initialise it

Create a repository with your source control of choice.

```{admonition} Best practice
:class: hint

Name the repository using the pattern ``<charm name>-operator`` for a single
charm, or ``<base charm name>-operators`` when the repository will hold
multiple related charms. For the charm name, see [](#decide-your-charms-name).
```

For example, name the repository `mega-calendar-k8s-operator` if your charm will be called `mega-calendar-k8s`.

Next, use {external+charmcraft:doc}`Charmcraft <index>` to generate the recommended project structure in the repository:

```text
charmcraft init --name mega-calendar-k8s --profile kubernetes
```

Or for a machine charm:

```text
charmcraft init --name mega-calendar --profile machine
```

If you don't specify `--name` when running `charmcraft init`, Charmcraft uses the parent directory name for your charm. For example, `mega-calendar-k8s-operator`, from the name of the repository. So we recommend specifying `--name` to ensure that your charm's name doesn't end with `-operator`.

Charmcraft's `kubernetes` and `machine` profiles are minimal charms that contain placeholder code and configuration.
These profiles also give you starting points for unit tests and integration tests.

Important files to be aware of:

- `charmcraft.yaml` - Metadata about your charm.
- `pyproject.toml` - Python project configuration, including the dependencies of your charm.
- `src/charm.py` - The Python file that will contain the main logic of your charm.

If your charm's workload was built with a web framework such as Django or FastAPI, consider using one of Charmcraft's 12-factor app profiles instead of `kubernetes` or `machine`. These profiles accelerate development by generating charms that are ready to deploy. {external+charmcraft:ref}`Write your first 12-factor app charm <tutorial>`.

## Next steps

- Start writing your charm code. See {ref}`write-and-structure-charm-code` and our other guides.
- Provide metadata in `charmcraft.yaml`. See {external+charmcraft:ref}`Charmcraft | Configure package information <configure-package-information>`.
