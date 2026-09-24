We welcome contributions to Ops!

Before working on changes, please consider [opening an issue](https://github.com/canonical/operator/issues) explaining your use case. If you would like to chat with us about your use cases or proposed implementation, you can reach us at [Matrix](https://matrix.to/#/#charmhub-charmdev:ubuntu.com) or [Discourse](https://discourse.charmhub.io/).

# AI

You're welcome to submit pull requests that are partly or entirely generated using generative AI tools. However, you must review the code yourself before moving the PR out of draft -- by submitting the PR, you are claiming personal responsibility for its quality and suitability. If you are not capable of reviewing the PR, please open an issue instead. PRs that are clearly (co-)authored by tools will be closed without review unless there is a human author that claims responsibility for the PR.

Please do not use tools such as GitHub Copilot to provide PR reviews.

# Pull requests

Changes are proposed as [pull requests on GitHub](https://github.com/canonical/operator/pulls).

- Work on a branch in your own fork.
- Sequence your commits logically if possible. But don't worry too much -- we'll squash to `main` after review.
- Don't force-push after review has started.
- Follow [conventional commit style](https://www.conventionalcommits.org/en/) for the PR title (not required for individual commits). We consider Ops too small a project to use scopes, so we don't use them.

## Branch updates

Before you ask for review, please rebase your branch onto `main` so that your changes will merge cleanly.

If you need to bring in the latest changes from `main` after the review has started, please use a merge commit.

## Coding style

We have a team [Python style guide](https://github.com/canonical/charm-tech/blob/main/style/python.md), most of which is enforced by CI checks. Please be complete with docstrings and keep them informative for _users_, as the [Ops library reference](https://canonical.com/juju/docs/ops/latest/reference/) is automatically generated from Python docstrings.

## Dependencies

The Python dependencies of `ops` are kept as minimal as possible, to avoid
bloat and to minimise conflict with the charm's dependencies. The dependencies
are listed in [pyproject.toml](pyproject.toml) in the `project.dependencies` section.

When adding a new dependency, also add it to the appropriate group in
[.github/dependabot.yaml](.github/dependabot.yaml) so Dependabot bundles
it into the right update PR:

- `charm-tech`: Charm Tech tooling (for example, `jubilant`, `pytest-jubilant`).
- `dev-tooling`: linters, type checkers, and other dev tools (for example,
  `ruff`, `pyright`, `codespell`, `pre-commit`).
- `test-deps`: `pytest` and its plugins.
- `runtime`: catch-all for everything else; minor and patch bumps only.

# Setting up a dev environment

To work in the framework itself you will need Python >= 3.10. Linting, testing,
and docs automation is performed using [`tox`](https://tox.readthedocs.io/en/latest/).

First, make sure to install [uv](https://docs.astral.sh/uv/), for example:

```sh
sudo snap install astral-uv --classic
```

Then install `tox` with the `tox-uv` extension:

```sh
uv tool install tox --with tox-uv
uv tool update-shell
```

Optionally, to run checks automatically before each commit, install
[pre-commit](https://pre-commit.com/#install) and run `pre-commit install`.

You can validate that you have a working installation by running `tox`, which will run a linter, type checker, and unit tests.

To enable Python type hints and language server support in your editor or IDE, set your interpreter path to the `.tox/lint` virtual environment created by tox.

For improved performance on the tests, install the library that allows
PyYAML to use C speedups:

```sh
sudo apt-get install libyaml-dev
```

# Tests

Changes should include tests. Where reasonable, prefer to write 'Scenario' tests using [ops.testing](https://canonical.com/juju/docs/ops/latest/reference/ops-testing/) instead of legacy [ops.testing.Harness](https://canonical.com/juju/docs/ops/latest/reference/ops-testing-harness/) tests.

Tests for Ops should go in the test module corresponding to the code. For example, a feature added in `ops/main.py` would go in `test/test_main.py`. However, when adding a large number of logically related tests, consider putting these in their own file, named accordingly. For example, if adding a feature `foo` in `ops/main.py`, the tests might go in `test/test_main_foo.py`.

Tests for [`ops-scenario`](https://github.com/canonical/operator/tree/main/testing/tests) and [`ops-tracing`](https://github.com/canonical/operator/tree/main/tracing/test) are arranged differently in places. Try to find the most logical place to add tests, based on the code that is tested.

## Running tests

The following are likely to be useful during development:

```sh
# Run the linter, type checker, and unit tests
tox

# Run tests, specifying whole suite or specific files
tox -e unit
tox -e unit -- test/test_charm.py

# Format the code
tox -e format

# Run only tests matching a certain pattern
tox -e unit -- -k <pattern>
```

The framework has some tests that interact with a real/live Pebble server, which can be installed as a snap. To run these tests, you must have [pebble](https://github.com/canonical/pebble) installed and available in your path.

```sh
tox -e pebble
```

## Using an `ops` branch in a charm

When making changes to `ops`, you'll commonly want to try those changes out in
a charm.

### From a Git branch

If your changes are in a Git branch, you can simply replace your `ops` version
in `requirements.txt` (or `pyproject.toml`) with a reference to the branch, like:

```
#ops ~= 3.0
git+https://github.com/{your-username}/operator@{your-branch-name}
```

`git` is not normally available when `charmcraft` is packing the charm, so you'll
need to also tell `charmcraft` that it's required for the build, by adding
something like this to your `charmcraft.yaml`:

```yaml
parts:
  charm:
    build-packages:
      - git
```

### From local code

If your changes are only on your local device, you can inject your local `ops`
into the charm after it has packed, and before you deploy it, by unzipping the
`.charm` file and replacing the `ops` folder in the virtual environment.

The [canonical/hyrum](https://github.com/canonical/hyrum) tool is useful for automating this, and allows you to test using a large number of different charms.

### Regression testing against existing charms

We rely on automation to [update charm pins](.github/actions/update-charm-pins/) of
a bunch of charms that use the operator framework. The script can be run locally too.

# Documentation

The published docs at [canonical.com/juju/docs/ops](https://canonical.com/juju/docs/ops/latest/) are built automatically from [the top-level `docs` directory](./docs). We use [MyST Markdown](https://mystmd.org/) for most pages and arrange the pages according to [Diátaxis](https://diataxis.fr/).

The documentation uses Canonical's [Sphinx Stack](https://github.com/canonical/sphinx-stack).

Sphinx Stack provides [`docs/conf.py`](./docs/conf.py), which we've customised with project metadata (as expected). We've also added config that goes beyond the provisions of Sphinx Stack. Search for `[BEYOND SPHINX STACK]` in `docs/conf.py`.

Sphinx Stack provides [`docs/Makefile`](./docs/Makefile). We've replaced the stock `$(DOCS_VENVDIR)` target by a custom version that uses uv to ensure that `ops-scenario` and `ops-tracing` are installed in the virtual environment.

Keep these customisations in mind when upgrading Sphinx Stack. To upgrade Sphinx Stack, see [Update the new Sphinx Stack](https://documentation.ubuntu.com/sphinx-stack/latest/how-to/update-sphinx-stack/new-sphinx-stack/).

## Contributing docs

1. Fork this repo and edit the relevant source files:
    - Tutorials - [`/docs/tutorial`](./docs/tutorial)
    - How-to guides - [`/docs/howto`](./docs/howto)
    - Reference - Automatically generated from Python docstrings
    - Explanation - [`/docs/explanation`](./docs/explanation)

    Make sure to follow the [documentation style guide](https://github.com/canonical/charm-tech/blob/main/style/docs.md).

2. Build the documentation locally to check that everything looks right
3. [Propose your changes using a pull request](#pull-requests)

When you create the pull request, GitHub automatically builds a preview of the docs. To find the preview, look for the "docs/readthedocs.com:canonical-juju-ops" check near the bottom of the pull request page, which links to the preview. You can use the preview to double check that everything looks right.

To build the docs and serve them locally:

```sh
make -C docs run
```

The docs automatically rebuild whenever you edit a file.

To check spelling in the doc source files:

```sh
make -C docs spelling
```

To list all doc commands:

```sh
make -C docs help
```

## How to document version dependencies

We publish separate documentation for each major version of Ops. We generally only make improvements to the latest version of the docs. If an older version of Ops changes in a way that's only applicable to that version, we update the older version of the docs. We also update the older version of the docs if there's an improvement that's critical for charming.

The published docs at [canonical.com/juju/docs/ops](https://canonical.com/juju/docs/ops/latest/) are always for the in-development (main branch) of Ops, and do not include any notes indicating changes or additions across Ops versions. We encourage all charmers to promptly upgrade to the latest version of Ops, and to refer to the release notes and changelog for learning about changes.

We do note when features behave differently when using different versions of Juju.

In docstrings:

- Use `.. jujuadded:: x.y` to indicate that the feature is only available when using version x.y (or higher) of Juju.
- Use `.. jujuchanged:: x.y` when the feature's behaviour changed in version x.y of Juju.
- Use `.. jujuremoved:: x.y` when the feature was removed in version x.y of Juju.

Similar directives also work in MyST Markdown. For example:

````markdown
```{jujuadded} x.y
Summary
```
````

Unmarked features are assumed to work and be available in the latest LTS version of Juju.

# Releases

## Release documentation

Part of making a release is a summary of it, and you review and edit that summary rather than writing it from nothing: the "Propose a release" workflow drafts it and puts it in the description of the pull request it opens. The summary appears in the GitHub release notes and in Discourse and Matrix.

In the summary, outline the key improvements from all areas of Ops,
including testing, tracing, and the docs.
The point here is to encourage people to check out the full notes and to upgrade
promptly, so ensure that you entice them with the best that the new versions
have to offer.

Avoid using the word "Scenario", preferring "unit testing API" or "state
transition testing".

### CHANGES.md

[CHANGES.md](CHANGES.md) lists the changes in each release. The changelog is kept up-to-date by the PR that the "Propose a release" workflow opens during the release process. You only need to manually edit the changelog if a commit message needs adjusting (we try to avoid doing this).

The entry is generated from the commits in the release, so it is a reference rather than an explanation: comprehensive, consistent, and not the place for prose. That is what the release notes are for.

There's also a changelog for `ops-scenario`:
[testing/CHANGES.md](testing/CHANGES.md). Don't add new entries to this file.
We've kept it for historical reference, but we no longer maintain it.

### GitHub release notes

The GitHub release notes include the summary of the release and the list of changes found in the changelog. The "Create the draft release" workflow puts the two together when the version-bump PR is merged: the summary as you left it in that PR's description, then this version's section of the changelog, copied rather than generated again. You might need to edit the draft release after a review.

### Discourse and Matrix

After completing the release process, post to
[the 'framework' category in Discourse](https://discourse.charmhub.io/c/framework/42) and
[Charm Development in Matrix](https://matrix.to/#/#charmhub-charmdev:ubuntu.com).

The Discourse post title should be:

```
Ops x.y.z released
```

And the post should resemble this:

```
The main improvements in this release are ...

Read more in the [full release notes on GitHub](link to the GitHub release).
```

The Matrix post should be similar.

## Publishing a release

Three workflows make a release, and you decide twice: once when you review the version-bump PR, and once when you publish the draft release. Nothing reaches PyPI until you publish the draft, so an abandoned attempt costs at most a branch and a draft to delete.

You don't need a GitHub token, a checkout, or a fork for any of this. The whole release runs in Actions and the only tools you need are the Actions tab and the releases page.

### 1. Propose the release

Run the ["Propose a release"](https://github.com/canonical/operator/actions/workflows/propose-release.yaml) workflow. It takes three inputs:

- `version`: leave this empty for an ordinary release. The workflow counts from the last release tag on the branch and reads the conventional commits since then: a feature or a breaking change makes it a minor release, and anything else makes it a patch release. Fill it in when the commits can't give the right answer, that is, for a major release or a pre-release such as `3.9.0rc1`. What you type is used as it stands, with no reconciling against what the commits suggest.
- `branch`: `main`, or a maintenance branch such as `2.23-maintenance`.
- `dry_run`: do everything except push the branch and open the PR. The proposed version, the changelog entry and the drafted notes go in the run summary, so this is how to see what a release would look like without proposing one.

> The version comes from the last tag, and never from `ops/version.py`. Between releases that file holds a development version left behind by the last post-release bump, which is a guess rather than something we shipped. The tag is also where the changelog starts, so the two can't drift apart.

The workflow writes the `CHANGES.md` entry, updates the version strings across `ops`, `ops-scenario`, `ops-tracing` and the tool-versions table, runs `uv lock`, drafts the release notes, and opens a PR from a `release-prep-X.Y.Z` branch, titled "chore: update changelog and versions for X.Y.Z release".

Review both halves of it, because they are different jobs:

- The diff: the version strings, the changelog entry, and the lockfile.
- The release notes, which are in the PR description between `<!-- release-notes:start -->` and `<!-- release-notes:end -->`. Edit them there, in the description: that is where the next workflow reads them from. Everything outside the markers is for reviewers and goes no further.

> The PR is opened with the workflow's own token, so GitHub won't start the usual checks on it. Close and reopen the PR to get them to run.

Wait for the checks to pass, then merge. If they don't pass at the tip of the branch, don't continue.

### 2. Merge the PR, and check the draft release

Merging the PR starts the ["Create the draft release"](https://github.com/canonical/operator/actions/workflows/create-draft-release.yaml) workflow. It runs on every push to `main` and to the maintenance branches, and decides that a push is a release when it leaves `ops/version.py` holding a version it didn't hold before, with no `.devN` suffix. Every other push, the post-release bump included, stops there quietly.

For a release, it takes the notes out of the merged PR's description, adds this version's section of `CHANGES.md` underneath, and creates a **draft** release named for the version. A version with an `a`, `b` or `rc` in it is marked as a pre-release. Nothing is published and the tag doesn't exist yet.

This is where somebody reads the notes as a reader will see them, which is a different act from reviewing a diff. Read them, edit the release body if it needs it, and then:

1. If you are releasing from `main`, tick "Set as the latest release". If you are releasing from a maintenance branch, untick it.
2. Click "Publish release". GitHub creates the tag as it publishes.

### 3. Publishing does the rest

Publishing the draft starts two workflows, which are siblings rather than one after the other:

- [Publish](https://github.com/canonical/operator/actions/workflows/publish.yaml) builds the three packages and uploads them to PyPI ([ops](https://pypi.org/project/ops/), [ops-scenario](https://pypi.org/project/ops-scenario), and [ops-tracing](https://pypi.org/project/ops-tracing/)), attests what it built, and runs the "SBOM and secscan" workflow. It sometimes takes a while for the new releases to show up on PyPI.
- [Post-release version bump](https://github.com/canonical/operator/actions/workflows/post-release.yaml) works out which branch the release came from, and opens a PR titled "chore: adjust versions after the X.Y.Z release" that puts that branch back onto a development version. Review and merge it. The same token caveat applies, so close and reopen it if you want the checks to run.

> The version in that PR is a placeholder rather than a prediction. Nothing counts from it, because the next release is counted from the last tag, so it doesn't matter if the next release turns out to be a different version. `main` sat at `3.9.0.dev0` through both the 3.8.1 and the 3.8.2 releases.

Two things are still yours to do by hand:

1. On the summary page of the most recent Publish run, locate the secscan artifacts. There will be two artifacts: `secscan-report-upload-sdist` and `secscan-report-upload-wheel`.

    Download both of these, and then upload them to the [SSDLC Ops folder in Drive](https://drive.google.com/drive/folders/17pOwak4LQ6sicr6OekuVPMECt2OcMRj8?usp=drive_link). Open the artifacts and verify that the security scan has not found any vulnerabilities. If you are releasing from the 2.23-maintenance branch, then follow the manual process instead, for both [SBOM generation](https://library.canonical.com/corporate-policies/information-security-policies/ssdlc/ssdlc---software-bill-of-materials-(sbom)) and [security scanning](https://library.canonical.com/corporate-policies/information-security-policies/ssdlc/ssdlc---vulnerability-identification).

2. Announce the release on [Discourse](https://discourse.charmhub.io/c/framework/42) and [Matrix](https://matrix.to/#/#charmhub-charmdev:ubuntu.com).

### Maintenance branches, pre-releases and major releases

A **maintenance release** is the same three steps with `branch` set to, for example, `2.23-maintenance`. Both the version and the changelog come from that branch's own last tag rather than from the newest tag in the repository.

"Propose a release" stops, rather than releasing, if the commits on a maintenance branch since its last tag include a feature or a breaking change. That means somebody has put a commit on the wrong branch, and a release is not the place to absorb it: fix the branch, or pass an explicit `version` if it really is what you want. Remember to untick "Set as the latest release" on the draft.

A **pre-release** needs an explicit `version`, for example `3.9.0rc1`, because the commits never imply one. The draft is marked as a pre-release, and it does go to PyPI: the Publish workflow fires on any published release rather than on a version pattern. Publishing a pre-release opens a post-release bump like any other release, and the bump drops the suffix, so after 3.4.0b3 the branch goes back to working towards `3.4.0.dev0`.

A **major release** needs an explicit `version` too. A `!` on a commit is surfaced in the changelog under "Breaking Changes" but is never read as a major bump, because we sometimes let a breaking change ride in a minor release.

To build the packages and upload them to **Test PyPI**, run the Publish workflow by hand from whichever branch or tag you want built. That path needs the setting described below.

### Settings a repository admin has to create

Two things live in the repository settings, so no PR can add them.

- An environment called `release-notes`, holding an `OPENROUTER_API_KEY` secret and an `OPENROUTER_MODEL` variable. The model is a variable so that changing it is a settings edit rather than a PR. The key should be its own, and not the one the `ai-failure-triage` environment uses: release notes are published prose on every release and failure triage is internal, so they have different blast radii, and a shared key means either can spend the other's budget.

    A release doesn't wait on this. With any of the three missing, "Propose a release" writes a placeholder in place of the notes - a line saying none were drafted, and an instruction to write them before merging - and carries on. Write them yourself in the PR description; everything after that works the same way.

- A trusted publisher on Test PyPI pointing at `publish.yaml`. PyPI matches a trusted publisher against the workflow's *file name*, and Test PyPI's publisher was configured against `test-publish.yaml`, which has been folded into `publish.yaml`. Until somebody re-points it, a manual run fails when it tries to upload. PyPI's own publisher is unaffected, because the file it names kept its name.

### If something fails partway

Every step reads what it needs fresh from the branch or the API, so re-running the failed job is usually the fix. Specifically:

- **"Propose a release" failed.** If it failed before pushing, nothing happened and you can run it again. If it pushed `release-prep-X.Y.Z` and then failed, close the PR if there is one and delete that branch before running it again: the workflow refuses to start while the branch exists, so that a half-finished attempt can't be mistaken for the real one.
- **The PR merged but no draft release appeared.** The workflow decided the push wasn't a release. Check the run's log, which says what it decided and why: the usual cause is a version that still has a `.devN` suffix on it.
- **"Create the draft release" failed.** Fix the cause and re-run the failed job; the push doesn't have to happen again. A PR description can still be edited after the merge, so markers somebody removed can be put back. If a draft was created before the failure, delete it first, because the workflow refuses to make a second one.
- **Publish failed.** Re-run it. The release stays published and the tag stays where it is, so there's nothing to unwind. If the packages reached PyPI before the failure, they can't be replaced: fix the problem in a new patch release.
- **"Post-release version bump" failed.** Re-run it. If the bump is already on the branch, it says so and stops, so a re-run after somebody did it by hand is safe. If a `post-release-X.Y.Z` branch is left over from an attempt, merge, close or delete it first.

If you need to give up on an attempt, delete the draft release and any `release-prep-*` and `post-release-*` branches, then start again. The one thing that can't be undone is a published release: the tag and the PyPI upload are both permanent.

# Updating the Charmcraft profiles

The Charmcraft `kubernetes` and `machine` profiles specify a minimum Ops version in their `pyproject.toml` templates. If an Ops release includes a major new feature or resolves a dependency issue, open a Charmcraft PR to increase the minimum Ops version in the profiles.

Here's the general maintenance process for the Charmcraft profiles.

## Editing the profiles

In your Charmcraft clone, check out a new branch, then edit the .j2 template files in these directories:

- `charmcraft/templates/init-kubernetes`
- `charmcraft/templates/init-machine`

Don't commit changes yet. Wait until you've tested the charms that `charmcraft init` generates.

## Testing the profiles

Create a directory outside your Charmcraft clone, for example `~/generated-charms`, and a script `~/generated-charms/generate.sh`:

```sh
#!/usr/bin/env bash
set -xueo pipefail

charmcraft_dir="$1"

for profile in kubernetes machine; do
    project="myapp-${profile}"
    rm -rf "${project}"
    uv run --project "$charmcraft_dir" --no-dev \
        charmcraft init --profile "${profile}" --project-dir "${project}"
    pushd "${project}"
    uv lock
    uvx --python 3.10 --with tox-uv tox -e lint,unit
    popd
done
```

Then run `./generate.sh <dir>` where `<dir>` is the location of your Charmcraft clone.

## Opening a Charmcraft PR

Use a conventional commit type **for each commit**. For example, `chore(templates):`.

After your PR has merged and Charmcraft has released to `latest/stable`, make sure that the Ops tutorials and example charms are consistent with your profile changes.

# Copyright

The format for copyright notices is documented in the [LICENSE.txt](LICENSE.txt). New files should begin with a copyright line with the current year (e.g. Copyright 2024 Canonical Ltd.) and include the full boilerplate (see APPENDIX of [LICENSE.txt](LICENSE.txt)). The copyright information in existing files does not need to be updated when those files are modified -- only the initial creation year is required.
