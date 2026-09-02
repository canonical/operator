We welcome contributions to Ops!

Before working on changes, please consider [opening an issue](https://github.com/canonical/operator/issues) explaining your use case. If you would like to chat with us about your use cases or proposed implementation, you can reach us at [Matrix](https://matrix.to/#/#charmhub-charmdev:ubuntu.com) or [Discourse](https://discourse.charmhub.io/).

For detailed technical information about the development of Ops, see [HACKING.md](./HACKING.md).


# AI

You're welcome to submit pull requests that are partly or entirely generated using generative AI tools. However, you must review the code yourself before moving the PR out of draft -- by submitting the PR, you are claiming personal responsibility for its quality and suitability. If you are not capable of reviewing the PR (for example, if you are not fluent in Python, or are not familiar with Ops), please do not submit the PR (maybe you'd like to open an issue instead). PRs that are clearly (co-)authored by tools will be closed without review unless there is a human author that claims responsibility for the PR.

Please do not use tools (such as GitHub Copilot) to provide PR reviews. The Charm Tech team also has access to these tools, and will use them when appropriate.


# Pull requests

Changes are proposed as [pull requests on GitHub](https://github.com/canonical/operator/pulls).

- Work on a branch in your own fork.
- Sequence your commits logically if possible. But don't worry too much -- we'll squash to `main` after review.
- Don't force-push after review has started.
- Follow [conventional commit style](https://www.conventionalcommits.org/en/) for the PR title (not required for individual commits).

Examples of PR titles:

- feat: add the ability to observe change-updated events
- fix!: correct the type hinting for config data
- docs: clarify how to use mounts in ops.testing.Container
- ci: adjust the workflow that publishes ops-scenario

We consider Ops too small a project to use scopes, so we don't use them.

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

Then install `tox` with extensions, as well as a range of Python versions:

```sh
uv tool install tox --with tox-uv
uv tool update-shell
```

Optionally, to run checks automatically before each commit, install
[pre-commit](https://pre-commit.com/#install) and run `pre-commit install`.

You can validate that you have a working installation by running:

```sh
tox --version
4.26.0 from /home/<your-user>/.local/share/uv/tools/tox/lib/python3.13/site-packages/tox/__init__.py
registered plugins:
    tox-uv-1.26.0 at /home/<your-user>/.local/share/uv/tools/tox/lib/python3.13/site-packages/tox_uv/plugin.py with uv==0.7.12
```

For improved performance on the tests, install the library that allows
PyYAML to use C speedups:

```sh
sudo apt-get install libyaml-dev
```

## Formatting and Checking

Test environments are managed with [tox](https://tox.wiki/) and executed with
[pytest](https://pytest.org), with coverage measured by
[coverage](https://coverage.readthedocs.io/).
Static type checking is done using [pyright](https://github.com/microsoft/pyright),
and extends the Python 3.10 type hinting support through the
[typing_extensions](https://pypi.org/project/typing-extensions/) package.

Formatting uses [Ruff](https://docs.astral.sh/ruff/).

All tool configuration is kept in [project.toml](pyproject.toml). The list of
dependencies can be found in the relevant `tox.ini` environment `deps` field.

## Building

The build backend is [setuptools](https://pypi.org/project/setuptools/), and
the build frontend is [build](https://pypi.org/project/build/).


# Tests

Changes should include tests. Where reasonable, prefer to write 'Scenario' tests using [ops.testing](https://canonical.com/juju/docs/ops/latest/reference/ops-testing/) instead of legacy [ops.testing.Harness](https://canonical.com/juju/docs/ops/latest/reference/ops-testing-harness/) tests.

Tests for Ops should go in the test module corresponding to the code. For example, a feature added in `ops/main.py` would go in `test/test_main.py`. However, when adding a large number of logically related tests, consider putting these in their own file, named accordingly. For example, if adding a feature `foo` in `ops/main.py`, the tests might go in `test/test_main_foo.py`.

Tests for [`ops-scenario`](https://github.com/canonical/operator/tree/main/testing/tests) and [`ops-tracing`](https://github.com/canonical/operator/tree/main/tracing/test) are arranged differently in places. Try to find the most logical place to add tests, based on the code that is tested.

## Running tests

The following are likely to be useful during development:

```sh
# Run linting and unit tests
tox

# Run tests, specifying whole suite or specific files
tox -e unit
tox -e unit -- test/test_charm.py

# Format the code using Ruff
tox -e format

# Generate a local copy of the Sphinx docs in docs/_build
make -C docs html

# Check spelling in the doc source files
make -C docs spelling

# run only tests matching a certain pattern
tox -e unit -- -k <pattern>
```

For more in depth debugging, you can enter the virtualenv so that you can run
`pytest` or other tools directly:

```sh
uv sync --all-groups
source .venv/bin/activate
pytest
```

Likewise, use this virtualenv to enable Python type hints and language server if
you use an editor from the console or specify it as interpreter path in an IDE.

## Pebble tests

The framework has some tests that interact with a real/live Pebble server.  To
run these tests, you must have [pebble](https://github.com/canonical/pebble)
installed and available in your path.  If you have the Go toolchain installed,
you can run `go install github.com/canonical/pebble/cmd/pebble@master`.  This will
install pebble to `$GOBIN` if it is set or `$HOME/go/bin` otherwise.  Add
`$GOBIN` to your path (e.g. `export PATH=$PATH:$GOBIN` or `export
PATH=$PATH:$HOME/go/bin` in your `.bashrc`) and you are ready to run the real
Pebble tests:

```sh
tox -e pebble
```

To do this even more manually, you could start the Pebble server yourself:

```sh
export PEBBLE=$HOME/pebble
export RUN_REAL_PEBBLE_TESTS=1
pebble run --create-dirs --http=:4000 &>pebble.log &

# Then
tox -e unit -- test/test_real_pebble.py
# or
source .tox/unit/bin/activate
pytest -v test/test_real_pebble.py
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
`.charm` file and replacing the `ops` folder in the virtualenv. This small
script will handle that for you:

```shell-script
#!/usr/bin/env bash

if [ "$#" -lt 2 ]
then
    echo "Inject local copy of Python Operator Framework source into charm"
    echo
    echo "usage: inject-ops.sh file.charm /path/to/ops/dir" >&2
    exit 1
fi

if [ ! -f "$2/framework.py" ]; then
    echo "$2/framework.py not found; arg 2 should be path to 'ops' directory"
    exit 1
fi

set -ex

mkdir inject-ops-tmp
unzip -q $1 -d inject-ops-tmp
rm -rf inject-ops-tmp/venv/ops
cp -r $2 inject-ops-tmp/venv/ops
cd inject-ops-tmp
zip -q -r ../inject-ops-new.charm .
cd ..
rm -rf inject-ops-tmp
rm $1
mv inject-ops-new.charm $1
```

### Using a Juju branch

If your `ops` change relies on a change in a Juju branch, you'll need to deploy
your charm to a controller using that version of Juju. For example, with microk8s:

1. [Build Juju and its dependencies](https://github.com/juju/juju/blob/3.4/CONTRIBUTING.md#build-juju-and-its-dependencies)
2. Run `make microk8s-operator-update`
3. Run `GOBIN=/path/to/your/juju/_build/linux_amd64/bin:$GOBIN /path/to/your/juju bootstrap`
4. Add a model and deploy your charm as normal

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

Before you start, make sure that you've [installed uv](https://docs.astral.sh/uv/getting-started/installation/). On Ubuntu, you can run:

```sh
sudo snap install astral-uv --classic
```

To build the docs:

```sh
make -C docs html
```

This generates HTML docs in the `docs/_build` directory.

To view the docs, you'll need to serve the docs locally. The easiest way is to run the following command instead of `make -C docs html`:

```sh
make -C docs run
```

This serves the docs locally and automatically refreshes them whenever you edit a file.

## How to document version dependencies

We publish separate documentation for each major version of Ops. We generally only make improvements to the latest version of the docs. If an older version of Ops changes in a way that's only applicable to that version, we update the older version of the docs. We also update the older version of the docs if there's an improvement that's critical for charming.

The published docs at [canonical.com/juju/docs/ops](https://canonical.com/juju/docs/ops/latest/) are always for the in-development (main branch) of Ops, and do not include any notes indicating changes or additions across Ops versions. We encourage all charmers to promptly upgrade to the latest version of Ops, and to refer to the release notes and changelog for learning about changes.

We do note when features behave differently when using different versions of Juju.

In docstrings:

- Use `.. jujuadded:: x.y` to indicate that the feature is only available when using version x.y (or higher) of Juju.
- Use `.. jujuchanged:: x.y` when the feature's behaviour changed in version x.y of Juju.
- Use `.. jujuremoved:: x.y` when the feature's behaviour changed in version x.y of Juju.

Similar directives also work in MyST Markdown. For example:

````markdown
```{jujuadded} x.y
Summary
```
````

Unmarked features are assumed to work and be available in the current LTS version of Juju.


# Releases

## Release documentation

As part of the release process, you'll write a summary of the release.
The summary appears in the GitHub release notes and in Discourse and Matrix.

In the summary, outline the key improvements from all areas of Ops,
including testing, tracing, and the docs.
The point here is to encourage people to check out the full notes and to upgrade
promptly, so ensure that you entice them with the best that the new versions
have to offer.

Avoid using the word "Scenario", preferring "unit testing API" or "state
transition testing".

### CHANGES.md

[CHANGES.md](CHANGES.md) lists the changes in each release. The changelog is
kept up-to-date by the PR that's created when you run `tox -e draft-release`
during the release process. You only need to manually edit the changelog if a
commit message needs adjusting (we try to avoid doing this).

There's also a changelog for `ops-scenario`:
[testing/CHANGES.md](testing/CHANGES.md). Don't add new entries to this file.
We've kept it for historical reference, but we no longer maintain it.

### GitHub release notes

The GitHub release notes include the summary of the release and
the list of changes found in the changelog. A draft release is created when
you run `tox -e draft-release` duing the release process. You might need to
edit the draft release after a review.

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

Before you start, ensure that your environment variable GITHUB_TOKEN is set and that the token has sufficient permissions. The easiest way to set a token is to run `gh auth login` first, follow the steps to log in, then run `export GITHUB_TOKEN=$(gh auth token)`.

Alternatively, you can also create a personal access token. To do so, go to GitHub -> Settings -> Developer Settings -> Personal access tokens -> Fine-grained tokens, and click "Generate new token" (shortcut: click [this link](https://github.com/settings/personal-access-tokens/new)). For "Resource owner", choose "canonical". For "Expiration", choose a desired setting (maximum is 366 days). Under "Repository access", choose "Only select repositories" and select "canonical/operator". Under "Permissions", click "Add permissions", select "Contents" and "Pull requests", then set the access to both of them to "Read and write" (since we need to create draft releases and PRs); note that "Metadata" will be chosen automatically as well. Click "Generate token", then set the environment variable `GITHUB_TOKEN` with it.

Then, check out the main branch of your forked operator repo and pull upstream to ensure the release automation script is the latest.

1. Draft a release: Run: `tox -e draft-release` at the root directory of the forked repo.

    > This assumes a draft release on the main branch, and your forked remote name is `origin`, and the `canonical/operator` remote name is `upstream`.
    >
    > If you have different settings, add parameters accordingly. For example, the following command assumes your forked remote name is `mine`, and `canonical/operator` remote name is `origin`:
    >
    > `tox -e draft-release -- --canonical-remote origin --fork-remote mine`
    >
    > By default, the script makes a release on the main branch. If you want to make a release on another branch, for example, on "2.23-maintenance" (you do not need to switch to this branch in your forked repo), run it with the "--branch" parameter:
    >
    > `tox -e draft-release -- --branch 2.23-maintenance`

2. Follow the steps of the `tox -e draft-release` output. You need to input the release title and an introduction section, which can be multiple paragraphs with empty lines in between. End the introduction section by typing a period sign (.) in a new line, then press enter.

3. If drafting the release succeeds, a PR named "chore: update changelog and versions for X.Y.Z release" will be created. Get it reviewed and merged, then wait until the tests pass after merging. It takes around 10 minutes. If the tests don't pass at the tip of the main branch, do not continue.

4. Go to the GitHub releases page, then edit the latest draft release. If you are releasing from the main branch, tick the "set as latest release" box. If you are releasing from a maintenance branch, uncheck the box for "set as latest release". Then, click "Publish release". GitHub will create the additional tag.

    > Pushing the tags will trigger automatic builds for the Python packages and
    > publish them to PyPI ([ops](https://pypi.org/project/ops/)
    > ,[ops-scenario](https://pypi.org/project/ops-scenario), and
    > [ops-tracing](https://pypi.org/project/ops-tracing/)).
    > Note that it sometimes take a bit of time for the new releases to show up.
    >
    > See [.github/workflows/publish.yaml](.github/workflows/publish.yaml) for details.
    >
    > You can troubleshoot errors at [Actions > Publish](https://github.com/canonical/operator/actions/workflows/publish.yaml).
    >
    > The Publish workflow includes a job that runs the "SBOM and secscan" workflow.

5. On the summary page of the most recent Publish run, locate the secscan artifacts. There will be two artifacts: `secscan-report-upload-sdist` and `secscan-report-upload-wheel`.

    Download both of these, and then upload them to the [SSDLC Ops folder in Drive](https://drive.google.com/drive/folders/17pOwak4LQ6sicr6OekuVPMECt2OcMRj8?usp=drive_link). Open the artifacts and verify that the security scan has not found any vulnerabilities. If you are releasing from the 2.23-maintenance branch, then follow the manual process instead, for both [SBOM generation](https://library.canonical.com/corporate-policies/information-security-policies/ssdlc/ssdlc---software-bill-of-materials-(sbom)) and [security scanning](https://library.canonical.com/corporate-policies/information-security-policies/ssdlc/ssdlc---vulnerability-identification).

6. Announce the release on [Discourse](https://discourse.charmhub.io/c/framework/42) and
[Matrix](https://matrix.to/#/#charmhub-charmdev:ubuntu.com).

7. Post release: At the root directory of your forked `canonical/operator` repo, check out to the main branch to ensure the release automation script is up-to-date, then run: `tox -e post-release`.

    > This assumes the same defaults as mentioned in step 1.
    >
    > Add parameters accordingly if your setup differs, for example, if you are releasing from a maintenance branch.

8. Follow the steps of the `tox -e post-release` output. If it succeeds, a PR named "chore: adjust versions after release" will be created. Get it reviewed and merged.

If the release automation script fails, delete the draft release and the newly created branches (`release-prep-*`, `post-release-*`) both locally and in the origin, fix issues, and retry.


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
