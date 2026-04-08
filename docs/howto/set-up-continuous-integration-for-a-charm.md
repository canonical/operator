---
myst:
  html_meta:
    description: Learn how to set up CI for your Juju charm, so that your charm's tests run on every pull request.
---

(set-up-ci)=
# How to set up continuous integration for a charm

```{admonition} Best practice
:class: hint

The quality assurance pipeline of a charm should be automated using a continuous integration (CI) system.
```

This guide demonstrates how to automatically run your charm's tests against any PR into the main branch of your GitHub repository.

You might also want to automatically publish your charm on Charmhub or publish charm libraries on PyPI. [charming-actions](https://github.com/canonical/charming-actions) has some useful GitHub actions for publishing on Charmhub. For guidance about publishing libraries on PyPI, see {external+charmlibs:ref}`How to distribute charm libraries <python-package-distribution-pypi>`.

(set-up-ci-linting-unit)=
## Run linting and unit tests in CI

Create a file called `.github/workflows/ci.yaml`:

```yaml
name: Charm tests
on:
  push:
    branches:
      - main
  pull_request:
  workflow_call:
  workflow_dispatch:

permissions: {}

jobs:
  lint:
    name: Linting
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v6
        with:
          persist-credentials: false
      - name: Set up uv
        uses: astral-sh/setup-uv@cec208311dfd045dd5311c1add060b2062131d57  # v8.0.0
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
        with:
          persist-credentials: false
      - name: Set up uv
        uses: astral-sh/setup-uv@cec208311dfd045dd5311c1add060b2062131d57  # v8.0.0
      - name: Set up tox and tox-uv
        run: uv tool install tox --with tox-uv
      - name: Run unit tests
        run: tox -e unit
```

(set-up-ci-integration)=
## Run integration tests in CI

Integration tests require a Juju controller and a cloud in which to deploy your charm. We recommend that you use [Concierge](https://github.com/canonical/concierge) to prepare the CI environment.

If your charm is a Kubernetes charm, add the following job to `.github/workflows/ci.yaml`:

```yaml
  integration:
    name: Integration tests
    runs-on: ubuntu-latest
    needs:
      - unit
    steps:
      - name: Checkout
        uses: actions/checkout@v6
        with:
          persist-credentials: false
      - name: Set up uv
        uses: astral-sh/setup-uv@cec208311dfd045dd5311c1add060b2062131d57  # v8.0.0
      - name: Set up tox and tox-uv
        run: uv tool install tox --with tox-uv
      - name: Set up Concierge
        run: sudo snap install --classic concierge
      - name: Set up Juju and charm development tools
        run: sudo concierge prepare -p k8s
      - name: Pack the charm
        # The integration tests don't pack the charm. Instead, they look for a .charm
        # file in the project dir (or use CHARM_PATH, if set).
        run: charmcraft pack
      - name: Run integration tests
        run: tox -e integration -- --juju-dump-logs
      - name: Upload logs
        if: ${{ !cancelled() }}
        uses: actions/upload-artifact@v7
        with:
          name: juju-dump-logs
          path: .logs
```

The option `-p k8s` tells Concierge that we want a cloud managed by Canonical Kubernetes.

If your charm is a machine charm, use `-p machine` instead.

The "Upload logs" step assumes that your integration tests use Jubilant together with `pytest-jubilant`. See [How to write integration tests for a charm](#write-integration-tests-for-a-charm-view-juju-logs).
