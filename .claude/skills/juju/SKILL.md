---
name: juju
description: "Develop and test against a real Juju controller"
---

# Juju Skill

Use Juju to develop and test changes in the Ops project. Works on Linux, ideally in a sandboxed environment.

## Quickstart

```bash
sudo concierge prepare -p dev  # Installs all the required packages and bootstraps local clouds and Juju itself
juju switch concierge-lxd  # For a machine charm
juju switch concierge-k8s  # For a Kubernetes charm
juju add-model claude-[random ID]  # Use a consistent prefix
```

After adding a model ALWAYS tell the user the name of the model and how they can inspect the status, filling in the details:

```
To inspect the status of the model:
  juju status -m [contoller-name]:[model-name]

Or to see the Juju logs:
  juju debug-log -m [controller-name]:[model-name]
```

This must ALWAYS be printed right after a session was started and once again at the end of the tool loop. But the earlier you send it, the happier the user will be.

## Watching output

Use `juju debug-log -m [controller-name]:[model-name]`. See `juju debug-log --help` for details.

## Important commands

- `charmcraft pack` - use this to pack a charm so that it can be deployed
- `juju deploy -m [controller-name]:[model-name] ./path-to-charm.charm` - deploy a charm -- see `--help` for information about providing resources
- `juju status --format json -m [controller-name]:[model-name]` - get information about the status of the deployed charms
- `juju actions` and `juju run` - run an action that a charm defines
- `juju config` - set configuration for a charm
- `juju integrate` - create a relation between two charms
- `juju ssh` - open a SSH connection to a charm container, see `--help` for details

## Cleanup

- Remove a model when done: `juju destroy-model [controller-name]:[model-name]`
- Do *not* remove the controller unless explicitly requested
- Do *not* remove any of the packages installed by Concierge unless explicitly requested
