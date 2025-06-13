We welcome contributions to Ops!

Before working on changes, please consider [opening an issue](https://github.com/canonical/operator/issues) explaining your use case. If you would like to chat with us about your use cases or proposed implementation, you can reach us at [Matrix](https://matrix.to/#/#charmhub-charmdev:ubuntu.com) or [Discourse](https://discourse.charmhub.io/).

For detailed technical information about the development of Ops, see [HACKING.md](./HACKING.md).

# Pull requests

Changes are proposed as [pull requests on GitHub](https://github.com/canonical/operator/pulls).

Pull requests should have a short title that follows the [conventional commit style](https://www.conventionalcommits.org/en/) using one of these types:

- chore
- ci
- docs
- feat
- fix
- perf
- refactor
- revert
- test

Some examples:

- feat: add the ability to observe change-updated events
- fix!: correct the type hinting for config data
- docs: clarify how to use mounts in ops.testing.Container
- ci: adjust the workflow that publishes ops-scenario

We consider Ops too small a project to use scopes, so we don't use them.

Note that the commit messages to the PR's branch do not need to follow the conventional commit format, as these will be squashed into a single commit to `main` using the PR title as the commit message.

To help us review your changes, please rebase your pull request onto the `main` branch before you request a review. If you need to bring in the latest changes from `main` after the review has started, please use a merge commit.

# Tests

Changes should include tests. Where reasonable, prefer to write 'Scenario' tests using [ops.testing](https://ops.readthedocs.io/en/latest/reference/ops-testing.html) instead of legacy [ops.testing.Harness](https://ops.readthedocs.io/en/latest/reference/ops-testing-harness.html) tests.

Tests for Ops should go in the test module corresponding to the code. For example, a feature added in `ops/main.py` would go in `test/test_main.py`. However, when adding a large number of logically related tests, consider putting these in their own file, named accordingly. For example, if adding a feature `foo` in `ops/main.py`, the tests might go in `test/test_main_foo.py`.

Tests for [`ops-scenario`](https://github.com/canonical/operator/tree/main/testing/tests) and [`ops-tracing`](https://github.com/canonical/operator/tree/main/tracing/test) are arranged differently in places. Try to find the most logical place to add tests, based on the code that is tested.

# Coding style

We have a team [Python style guide](./STYLE.md), most of which is enforced by CI checks. Please be complete with docstrings and keep them informative for _users_, as the [Ops library reference](https://ops.readthedocs.io/en/latest/reference/index.html) is automatically generated from Python docstrings.

# Documentation

The published docs at [ops.readthedocs.io](https://ops.readthedocs.io/en/latest/index.html) are built automatically from [the top-level `docs` directory](./docs). We use [MyST Markdown](https://mystmd.org/) for most pages and arrange the pages according to [Diátaxis](https://diataxis.fr/).

To contribute docs:

1. Fork this repo and edit the relevant source files:
    - Tutorials - [`/docs/tutorial`](./docs/tutorial)
    - How-to guides - [`/docs/howto`](./docs/howto)
    - Reference - Automatically generated from Python docstrings
    - Explanation - [`/docs/explanation`](./docs/explanation)
2. [Build the documentation locally](#how-to-build-the-documentation-locally), to check that everything looks right
3. [Propose your changes using a pull request](#pull-requests)

When you create the pull request, GitHub automatically builds a preview of the docs. To find the preview, look for the "docs/readthedocs.org:ops" check near the bottom of the pull request page, then click **Details**. You can use the preview to double check that everything looks right.

## How to write great documentation

- Use short sentences, ideally with one or two clauses.
- Use headings to split the doc into sections. Make sure that the purpose of each section is clear from its heading.
- Avoid a long introduction. Assume that the reader is only going to scan the first paragraph and the headings.
- Avoid background context unless it's essential for the reader to understand.

Recommended tone:

- Use a casual tone, but avoid idioms. Common contractions such as "it's" and "doesn't" are great.
- Use "we" to include the reader in what you're explaining.
- Avoid passive descriptions. If you expect the reader to do something, give a direct instruction.

## How to build the documentation locally

To build the docs and open them in your browser:

```sh
tox -e docs
open docs/_build/html/index.html
```

Alternatively, to serve the docs locally and automatically refresh them whenever you edit a file:

```sh
tox -e docs-live
```

## How to document version dependencies

We don't publish separate documentation for separate versions of Ops. The published docs at [ops.readthedocs.io](https://ops.readthedocs.io/en/latest/index.html) are always for the in-development (main branch) of Ops, and do not include any notes indicating changes or additions across Ops versions. We encourage all charmers to promptly upgrade to the latest version of Ops, and to refer to the release notes and changelog for learning about changes.

We do note when features behave differently when using different versions of Juju.

In docstrings:

- Use `.. jujuadded:: x.y` to indicate that the feature is only available when using version x.y (or higher) of Juju.
- Use `.. jujuchanged:: x.y` when the feature's behaviour _in Ops_ changes.
- Use `.. jujuremoved:: x.y` when the feature will be available in Ops but not in that version (or later) of Juju.

Similar directives also work in MyST Markdown. For example:

````markdown
```{jujuadded} x.y
Summary
```
````

Unmarked features are assumed to work and be available in the current LTS version of Juju.

# Copyright

The format for copyright notices is documented in the [LICENSE.txt](LICENSE.txt). New files should begin with a copyright line with the current year (e.g. Copyright 2024 Canonical Ltd.) and include the full boilerplate (see APPENDIX of [LICENSE.txt](LICENSE.txt)). The copyright information in existing files does not need to be updated when those files are modified -- only the initial creation year is required.

# Reviews

All changes require review before being merged. Code review typically examines:

- Code quality
- Test coverage
- User experience

When evaluating design decisions, we give priority to the following personas:

- Charm authors and maintainers (highest priority)
- Contributors to the Ops codebase
- Juju developers
