# Contributing

This document explains the processes and practices recommended for contributing enhancements to Ops.

- Generally, before developing enhancements, you should consider [opening an issue](https://github.com/canonical/operator/issues) explaining your use case.

- If you would like to chat with us about your use cases or proposed implementation, you can reach us at [Matrix](https://matrix.to/#/#charmhub-charmdev:ubuntu.com) or [Discourse](https://discourse.charmhub.io/).

- All enhancements require review before being merged. Code review typically examines:
  - Code quality
  - Test coverage
  - User experience

- When evaluating design decisions, we optimize for the following personas, in descending order of priority:
  - Charm authors and maintainers
  - Contributors to the Ops codebase
  - Juju developers

- Please help us out in ensuring easy to review branches by rebasing your pull request branch onto the `main` branch. This also avoids merge commits and creates a linear Git commit history.

## Notable design decisions

### ops-scenario

- The `State` object is immutable from the perspective of the test writer. At the moment there is some hackery here and there (`object.__setattr__`...) to bypass the read-only dataclass for when the charm code mutates the state; at some point it would be nice to refactor the code to make that unnecessary.

- At the moment the mocking operates at the level of `ops.ModelBackend`-mediated hook tool calls. `ModelBackend` would `Popen` hook tool calls, but `Scenario` patches the methods that would call `Popen`, which is therefore never called. Instead, values are returned according to the `State`. We could consider allowing to operate in increasing levels of stricter confinement:
  - Actually generate hook tool scripts that read/write from/to `State`, making patching `ModelBackend` unnecessary.
  - On top of that, run the whole simulation in a container.

## Developing

See [HACKING.md](./HACKING.md).
