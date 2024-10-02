# Contributing

![GitHub License](https://img.shields.io/github/license/canonical/ops-scenario)
![GitHub Commit Activity](https://img.shields.io/github/commit-activity/y/canonical/ops-scenario)
![GitHub Lines of Code](https://img.shields.io/tokei/lines/github/canonical/ops-scenario)
![GitHub Issues](https://img.shields.io/github/issues/canonical/ops-scenario)
![GitHub PRs](https://img.shields.io/github/issues-pr/canonical/ops-scenario)
![GitHub Contributors](https://img.shields.io/github/contributors/canonical/ops-scenario)
![GitHub Watchers](https://img.shields.io/github/watchers/canonical/ops-scenario?style=social)

This documents explains the processes and practices recommended for contributing enhancements to this project.

- Generally, before developing enhancements to this project, you should consider [opening an issue](https://github.com/canonical/ops-scenario/issues) explaining your use case.
- If you would like to chat with us about your use-cases or proposed implementation, you can reach us at [Canonical Mattermost public channel](https://chat.charmhub.io/charmhub/channels/charm-dev) or [Discourse](https://discourse.charmhub.io/).
- Familiarising yourself with the [Charmed Operator Framework](https://juju.is/docs/sdk) library will help you a lot when working on new features or bug fixes.
- All enhancements require review before being merged. Code review typically examines:
  - code quality
  - test coverage
  - user experience
- When evaluating design decisions, we optimize for the following personas, in descending order of priority:
  - charm authors and maintainers
  - the contributors to this codebase
  - juju developers
- Please help us out in ensuring easy to review branches by rebasing your pull request branch onto the `main` branch. This also avoids merge commits and creates a linear Git commit history.

## Notable design decisions

- The `State` object is immutable from the perspective of the test writer.
At the moment there is some hackery here and there (`object.__setattr__`...) to bypass the read-only dataclass for when the charm code mutates the state; at some point it would be nice to refactor the code to make that unnecessary.

- At the moment the mocking operates at the level of `ops.ModelBackend`-mediated hook tool calls. `ModelBackend` would `Popen` hook tool calls, but `Scenario` patches the methods that would call `Popen`, which is therefore never called. Instead, values are returned according to the `State`. We could consider allowing to operate in increasing levels of stricter confinement:
  - Actually generate hook tool scripts that read/write from/to `State`, making patching `ModelBackend` unnecessary.
  - On top of that, run the whole simulation in a container.

## Developing

To set up the dependencies you can run:
`pip install . ; pip uninstall ops-scenario`

We recommend using the provided `pre-commit` config. For how to set up git pre-commit: [see here](https://pre-commit.com/).
If you dislike that, you can always manually remember to `tox -e lint` before you push.
 
### Testing
```shell
tox -e fmt           # auto-fix your code as much as possible, including formatting and linting
tox -e lint          # code style
tox -e unit          # unit tests
tox -e lint-tests    # lint testing code
tox                  # runs 'lint', 'lint-tests' and 'unit' environments
```

