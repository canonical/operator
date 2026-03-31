(set-up-ci)=
# How to set up continuous integration for a charm

```{admonition} Best practice
:class: hint

The quality assurance pipeline of a charm should be automated using a continuous integration (CI) system.
```

This guide demonstrates how to automatically run your charm's tests against any PR into the main branch of your GitHub repository.

You might also want to automatically publish your charm on Charmhub or publish charm libraries on PyPI. [charming-actions](https://github.com/canonical/charming-actions) has some useful GitHub actions for publishing on Charmhub. For guidance about publishing on PyPI, see {external+charmlibs:ref}`How to distribute charm libraries <python-package-distribution-pypi>`.

(set-up-ci-linting-unit)=
## Create a workflow for linting and unit tests

Create a file called `.github/workflows/tests.yaml`:

```yaml
name: Linting and unit tests
on:
  push:
    branches:
      - main
  pull_request:
  workflow_call:
  workflow_dispatch:

jobs:
  lint:
    name: Linting
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v6
      - name: Set up uv
        uses: astral-sh/setup-uv@7
      - name: Set up tox and tox-uv
        run: uv tool install tox --with tox-uv
      - name: Lint the code
        run: tox -e lint

  unit:
    name: Unit tests
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v6
      - name: Set up uv
        uses: astral-sh/setup-uv@7
      - name: Set up tox and tox-uv
        run: uv tool install tox --with tox-uv
      - name: Run unit tests
        run: tox -e unit
```

(set-up-ci-integration)=
## Create a workflow for integration tests

Integration tests require a Juju controller and a cloud in which to deploy your charm. We recommend that you use [Concierge](https://github.com/canonical/concierge) to prepare the CI environment.

If your charm is a Kubernetes charm, create a file called `.github/workflows/integration-tests.yaml`:

```yaml
name: Integration tests
on:
  push:
    branches:
      - main
  pull_request:
  workflow_call:
  workflow_dispatch:

jobs:
  integration:
    name: Integration tests
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v6
      - name: Set up uv
        uses: astral-sh/setup-uv@7
      - name: Set up tox and tox-uv
        run: uv tool install tox --with tox-uv
      - name: Set up Concierge
        run: sudo snap install --classic concierge
      - name: Set up Juju and charm development tools
        run: sudo concierge prepare -p k8s
      - name: Pack the charm
        run: charmcraft pack
      - name: Run integration tests
        # Set a predictable model name so it can be consumed by charm-logdump-action.
        run: tox -e integration -- --model testing
      - name: Dump logs
        uses: canonical/charm-logdump-action@main
        if: failure()
        with:
          app: your-app
          model: testing
```

The option `-p k8s` tells Concierge that we want a cloud managed by Canonical Kubernetes.

If your charm is a machine charm, use `-p machine` instead.
