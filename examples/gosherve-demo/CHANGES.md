# Changes from jnsgruk/hello-kubecon

This charm is an updated version of the "Hello Kubecon" charm created by Jon
Seager. The following changes were made to align with current charming practice.

* Unified `charmcraft.yaml`: the `metadata.yaml`, `actions.yaml`, and
  `config.yaml` files were merged into the `charmcraft.yaml` file.
* Dev tooling was updated to use `ruff` and `pyright`, with `tox` (and `tox-uv`)
  as task runner.
* Changed to use `uv` for dependencies
* Moved to the `uv` plugin for the charm
* Changed the link for a quick start to the Ops K8s Tutorial.
* Use "import ops" rather than "from ops.x import"
* Use "framework: ops.Framework" rather than "*args"
* Use "framework.observe" rather than "self.framework.observe"
* Use "self.on[gosherve].pebble_ready" rather than "self.on.goserve_pebble_ready", same for action.
* Added a config class.
* Bumped the required Python version to 3.12.
* Added type annotations.
* Removed the `git` build package requirement.
* Changed to Charmcraft 3 style base, and 24.04 for the base.
* Added 'optional:' to the `ingress` relation.
* Moved tests into `unit/`, and added basic integration tests.
* Migrated unit tests from harness to Scenario.
* Migrated unit tests from unittest to pytest.
* De-HTML'd the README, updated a few links, and removed the option to see branches.
* Added a local file with short URLs and changed the default config to that file.
