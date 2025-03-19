(manage-charms)=
# How to manage charms

> See first: {external+juju:ref}`Juju | Build a charm <build-a-charm>`, {external+charmcraft:ref}`Charmcraft | Manage charms <manage-charms>`

## Create a repository and initialise it

Create a repository with your source control of choice. Commit the code you have
added and changed after every significant change, so that you have a record of
the work, and can revert to an earlier version when required.

```{admonition} Best practice
:class: important

Name the repository using the pattern ``<charm name>-operator`` for a single
charm, or ``<base charm name>-operators`` when the repository will hold
multiple related charms. For the charm name, see
{external+charmcraft:ref}`Charmcraft | Specify a name <specify-a-name>`.
```

In your new repository, run `charmcraft init` to generate the recommended
structure for building a charm.

```{note}
In most cases, you'll want to use `--profile=machine` or `profile=kubernetes`.
If you are charming an application built with a popular framework, check if
charmcraft has a {external+charmcraft:ref}`specific profile <tutorial>` for it.

Avoid the default (`--profile=simple`), which provides a demo charm, rather than
a base for building a charm of your own.
```

````{tip}
If your repository will hold multiple charms, or a charm and source for other
artifacts, like a Rock, create a `charms` folder at the top level, then a folder
for each charm inside of that one, and run `charmcraft --init` in each charm
folder. You'll end up with a structure similar to:

```
my-charm-set-operators/
├── charms
│   ├── my-charm
│   │   ├── charmcraft.yaml
│   │   ├── pyproject.toml
│   │   ├── README.md
│   │   ├── requirements.txt
│   │   ├── src
│   │   │   └── charm.py
│   │   ├── tests
│   │   │   ├── integration
│   │   │   │   └── test_charm.py
│   │   │   └── unit
│   │   │       └── test_charm.py
│   │   └── tox.ini
│   ├── my-charm-dashboard
|   |   └── ...
│   └── my-charm-helper
|   |   └── ...
├── CONTRIBUTING.md
├── LICENSE
├── README.md
└── rock
    └── ...
```

````

## Use the provided tooling to maintain style and detect issues early

The Charmcraft profile you've chosen has configured a number of recommended
tools for developing charms. To use these, install
[`tox`](https://tox.wiki/en/stable/index.html) on your development server.

```{tip}
If you use the `charm-dev` [Multipass](https://canonical.com/multipass) image or
the [`concierge`](https://github.com/jnsgruk/concierge) tool to configure your
development environment, you'll already have `tox` installed.
```

- Run `tox` to format and lint the code, and run static type checking and the
  charm unit tests.
- Run `tox -e integration` to run the charm integration tests.
- Run `tox list` to see the available commands.

```{admonition} Best practice
:class: important

All charms should provide the commands configured by the charmcraft profiles, to
allow easily testing across the charm ecosystem. It's fine to tweak the
configuration of individual tools, or to add additional commands, but keep the
command names and meanings that the profiles provide.
```

## Define the required dependencies

### Use the Python provided by the base

Charms run using the Python version provided by the base Ubuntu version. Write
charm code that will run with the Python version of the oldest base you support.

> See also: {external+juju:ref}`Juju | Roadmap and releases <juju-roadmap-and-releases>`

```{admonition} Best practice
:class: important

Set the [`requires-python`](https://packaging.python.org/en/latest/specifications/pyproject-toml/#requires-python)
version in your `pyproject.toml` so that tooling will detect any use of Python
features not available in the versions you support.
```

### Add Python dependencies to pyproject.toml, and generate a lock file

Specify all the direct dependencies of your charm in your `pyproject.toml`
file in the top-level charm folder. For example:

```toml
# Required group: these are all dependencies required to run the charm.
dependencies = [
    "ops~=2.19",
]

# Required group: these are all dependencies required to run all the charm's tests.
[dependency-groups]
test = [
    "ops[testing]",
    "pytest",
    "coverage[toml]",
    "jubilant",
]
# Optional additional groups:
docs = [
    "canonical-sphinx-extensions",
    "furo",
    "sphinx ~= 8.0.0",
    "sphinxext-opengraph",
]
```

Use the `pyproject.toml` dependencies to specify *all* dependencies (including
indirect or transitive dependencies) in a lock file.

````{admonition} Best practice
:class: important

When using the `charm` plugin with charmcraft, ensure that you set strict
dependencies to true, for example:

```yaml
parts:
  my-charm:
    plugin: charm
    charm-strict-dependencies: false
```
````

The default lock file is a plain `requirements.txt` file (you can use a tool
such as [pip-compile](https://pip-tools.readthedocs.io/en/latest/) to produce
it from `pyproject.toml`).

```{tip}
Charmcraft provides plugins for {external+charmcraft:ref}`uv <craft_parts_uv_plugin>`
and {external+charmcraft:ref}`poetry <craft_parts_poetry_plugin>`. Use one of
these tools to simplify the generation of your lock file.
```

```{admonition} Best practice
:class: important

Ensure that the `pyproject.toml` *and* the lock file are committed to version
control, so that exact versions of charms can be reproduced.
```

```{tip}
Including an external dependency is a significant choice. It can help with
reducing the complexity and development cost. However, it also increases the
complexity of understanding the entire system, and adds a maintenance burden of
keeping track of upstream versions, particularly around security issues.

> See more: [Our Software Dependency Problem](https://research.swtch.com/deps)
```

## Validate your charm with every change

Configure your continuous integration tooling so that whenever changes are
proposed for or accepted into your main branch the `lint`, `unit`, and
`integration` commands are run, and will block merging when failing.

```{admonition} Best practice
:class: important

The quality assurance pipeline of a charm should be automated using a
continuous integration (CI) system.
```

If you are using GitHub, create a file called `.github/workflows/ci.yaml`. For
example, to include a `lint` job that runs the `tox` `lint` environment:

```yaml
name: Tests
on:
  workflow_call:
  workflow_dispatch:

jobs:
  lint:
    name: Lint
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
      - name: Install dependencies
        run: pip install tox
      - name: Run linters
        run: tox -e lint
```

Other `tox` environments can be run similarly; for example unit tests:

```yaml
  unit-test:
    name: Unit tests
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
      - name: Install dependencies
        run: pip install tox
      - name: Run tests
        run: tox -e unit
```

Integration tests are a bit more complex, because in order to run those tests, a Juju controller and
a cloud in which to deploy it, is required. This example uses a `concierge` in order to set up
`k8s` and Juju:

```
  integration-test-k8s:
    name: Integration tests (k8s)
    needs:
      - lint
      - unit-test
    runs-on: ubuntu-latest
    steps:
      - name: Install concierge
        run: sudo snap install --classic concierge
      - name: Install Juju and tools
        run: sudo concierge prepare -p k8s
      - name: Checkout
        uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
      - name: Install dependencies
        run: pip install tox
      - name: Run integration tests
        # Set a predictable model name so it can be consumed by charm-logdump-action
        run: tox -e integration -- --model testing
      - name: Dump logs
        uses: canonical/charm-logdump-action@main
        if: failure()
        with:
          app: my-app-name
          model: testing
```

```{tip}

The `charming-actions <https://github.com/canonical/charming-actions>`_
repository includes actions to ensure that libraries are up-to-date, publish
charms and libraries, and more.
```

```{admonition} Best practice
:class: important

Ensure that tooling is configured to automatically detect new versions,
particularly security releases, for all your dependencies.
```
