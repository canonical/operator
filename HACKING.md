We welcome contributions to Ops! Before you start work on a contribution, please also read [CONTRIBUTING.md](./CONTRIBUTING.md).

# Setting up a Dev Environment

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

# Testing

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
tox -e docs

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

## Pebble Tests

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

# Maintaining the documentation

## How to Pull in Style Changes

The documentation uses Canonical styling which is customised on top of the [Furo Sphinx theme](https://github.com/pradyunsg/furo). The easiest way to pull in Canonical style changes is by using the Canonical documentation starter pack, see [docs](https://canonical-starter-pack.readthedocs-hosted.com/) and [repository](https://github.com/canonical/sphinx-docs-starter-pack).

TL;DR:

- Clone the starter pack repository to a local directory: `git clone git@github.com:canonical/sphinx-docs-starter-pack`.
- Copy the folder `.sphinx` under the starter pack repo to the operator repo `docs/.sphinx`.

## How to Customise Configurations

There are two configuration files: [`docs/conf.py`](./docs/conf.py) and [`docs/custom_conf.py`](./docs/custom_conf.py), copied and customised from the starter pack repo.

To customise, change the file [`docs/custom_conf.py`](./docs/custom_conf.py) only, and theoretically, we should not change [`docs/conf.py`](./docs/conf.py) (however, some changes are made to [`docs/conf.py`](./docs/conf.py), such as adding autodoc, PATH, fixing issues, etc.)

## How to Pull in Dependency Changes

The Canonical documentation starter pack uses Make to build the documentation, which will run the script [`docs/.sphinx/build_requirements.py`](./docs/.sphinx/build_requirements.py) and generate a requirement file `requirements.txt` under `docs/.sphinx/`.

To pull in new dependency changes from the starter pack, change to the starter pack repository directory, and build with the following command. This will create a virtual environment, generate a dependency file, install the software dependencies, and build the documentation:

```bash
make html
```

Then, compare the generated file `.sphinx/requirements.txt` and the `docs` declaration in the `dependency-groups` section of [`pyproject.toml`](./pyproject.toml) and adjust the `pyproject.toml` file accordingly.

# Dependencies

The Python dependencies of `ops` are kept as minimal as possible, to avoid
bloat and to minimise conflict with the charm's dependencies. The dependencies
are listed in [pyproject.toml](pyproject.toml) in the `project.dependencies` section.

# Dev Tools

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

# Publishing a Release

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
4. Go to the GitHub releases page, edit the latest draft release. If you are releasing from the main branch, tick the "set as latest release" box. If you are releasing from a maintenance branch, uncheck the box for "set as latest release". Then, click "Publish release". GitHub will create the additional tag.

    > You can troubleshoot errors on the [Actions Tab](https://github.com/canonical/operator/actions).

    > Pushing the tags will trigger automatic builds for the Python packages and
    > publish them to PyPI ([ops](https://pypi.org/project/ops/) 
    > ,[ops-scenario](https://pypi.org/project/ops-scenario), and 
    > [ops-tracing](https://pypi.org/project/ops-tracing/)).
    > Note that it sometimes take a bit of time for the new releases to show up.
    > 
    > See [.github/workflows/publish.yaml](.github/workflows/publish.yaml) for details.
    >
    > You can troubleshoot errors on the [Actions Tab](https://github.com/canonical/operator/actions).

5. In the [SBOM and secscan workflow in the Actions Tab](https://github.com/canonical/operator/actions/workflows/sbom-secscan.yaml), verify that there is a run for the new release. In the workflow run, there will be two artifacts produced, `secscan-report-upload-sdist` and `secscan-report-upload-wheel`. Download both of these, and then upload them to the [SSDLC Ops folder in Drive](https://drive.google.com/drive/folders/17pOwak4LQ6sicr6OekuVPMECt2OcMRj8?usp=drive_link). Open the artifacts and verify that the security scan has not found any vulnerabilities. If you are releasing from the 2.23-maintenance branch, then follow the manual process instead, for both [SBOM generation](https://library.canonical.com/corporate-policies/information-security-policies/ssdlc/ssdlc---software-bill-of-materials-(sbom)) and [security scanning](https://library.canonical.com/corporate-policies/information-security-policies/ssdlc/ssdlc---vulnerability-identification).
6. Announce the release on [Discourse](https://discourse.charmhub.io/c/framework/42) and
[Matrix](https://matrix.to/#/#charmhub-charmdev:ubuntu.com).
7. Post release: At the root directory of your forked `canonical/operator` repo, check out to the main branch to ensure the release automation script is up-to-date, then run: `tox -e post-release`.

    > This assumes the same defaults as mentioned in step 1.
    > 
    > Add parameters accordingly if your setup differs, for example, if you are releasing from a maintenance branch.

8. Follow the steps of the `tox -e post-release` output. If it succeeds, a PR named "chore: adjust versions after release" will be created. Get it reviewed and merged.

If the release automation script fails, delete the draft release and the newly created branches (`release-prep-*`, `post-release-*`) both locally and in the origin, fix issues, and retry.

## Release Documentation

We produce several pieces of documentation for `ops` and `ops-scenario`
releases, each serving a separate purpose and covering a different level.

Avoid using the word "Scenario", preferring "unit testing API" or "state
transition testing". Users should install `ops-scenario` with
`pip install ops[testing]` rather than using the `ops-scenario` package name
directly.

### `git log`

`git log` is used to see every change since a previous release. Obviously, no
special work needs to be done so that this is available. A link to the GitHub
view of the log will be included at the end of the GitHub release notes when
the "Generate Release Notes" button is used, in the form:

```
**Full Changelog**: https://github.com/canonical/operator/compare/3.0.0...3.1.0
```

These changes include both `ops` and `ops-scenario`. If someone needs to see
changes only for one of the packages, then the `/testing/` folder can be
filtered in/out.

### CHANGES.md

A changelog is kept in version control that simply lists the changes in each
release, other than chores. The changelog for `ops`
is at the top level, in [CHANGES.md](CHANGES.md), and the changelog for
`ops-scenario` is in the `/testing` folder, [CHANGES.md](testing/CHANGES.md).
There will be overlap between the two files, as many PRs will include changes to
common infrastructure, or will adjust both `ops` and also the testing API in
`ops-scenario`.

Adding the changes is done in preparation for a release. Use the "Generate
Release Notes" button in the GitHub releases page, and copy the text to the
CHANGES.md files.

* Group the changes by the commit type (feat, fix, and so on) and use full names
  ("Features", not "feat", "Fixes", not "fix") for group headings.
* Remove any chores.
* Remove any bullets that do not apply to the package. For instance, if a bullet
  only affects `ops[testing]`, don't include it in [CHANGES.md](CHANGES.md) when
  doing an `ops` release. The bullet should go in [testing/CHANGES.md](testing/CHANGES.md)
  instead. If `ops[testing]` is not being released yet, put the bullet in a placeholder
  section at top of [testing/CHANGES.md](testing/CHANGES.md).
* Strip the commit type prefix from the bullet point, and capitalise the first
  word.
* Strip the username (who did each commit) if the author is a member of the
  Charm Tech team.
* Replace the link to the pull request with the PR number in parentheses.
* Where appropriate, collapse multiple tightly related bullet points into a
  single point that refers to multiple commits.
* Where appropriate, add backticks for code formatting.
* Do not include the "New Contributors" section and the "Full Changelog" link
  (created by "Generate Release Notes").

For example: the PR

```
* docs: clarify where StoredState is stored by @benhoyt in https://github.com/canonical/operator/pull/2006
```

is added to the "Documentation" section as:

```
* Clarify where StoredState is stored (#2006)
```

### GitHub Release Notes

The GitHub release notes include the list of changes found in the changelogs,
but:

* If both `ops` and `ops-scenario` packages are being released, include all the
  changes in the same set of release notes. If only one package is being
  released, remove any bullets that apply only to the other package.
* The links to the PRs are left in full.
* Add a section above the list of changes that briefly outlines any key changes
  in the release.

### Discourse Release Announcement

Post to the [framework category](https://discourse.charmhub.io/c/framework/42)
with a subject matching the GitHub release title.

The post should resemble this:

```
The Charm Tech team has just released version x.y.z of ops!

It’s available from PyPI by using `pip install ops`, and `pip install ops[testing]`,
which will pick up the latest version. Upgrade by running `pip install --upgrade ops`.

The main improvements in this release are ...

Read more in the [full release notes on GitHub](link to the GitHub release).
```

In the post, outline the key improvements both in `ops` and `ops-scenario`.
The point here is to encourage people to check out the full notes and to upgrade
promptly, so ensure that you entice them with the best that the new versions
have to offer.

## Updating the Ops versions in the Charmcraft profiles

The Charmcraft `kubernetes` and `machine` profiles specify a minimum Ops version in their `pyproject.toml` templates. If an Ops release includes a major new feature or resolves a dependency issue, open a PR to Charmcraft to increase the minimum Ops version in the profiles and refresh the `uv.lock` templates.

First, fork the [Charmcraft repo](https://github.com/canonical/charmcraft) and create a branch for local development. In your branch, run `make setup` to create a virtual environment, then run `source .venv/bin/activate`.

> See also: Charmcraft's [contributing guide](https://github.com/canonical/charmcraft/blob/main/CONTRIBUTING.md)

Next, do the following for the `kubernetes` profile:

1. In `charmcraft/templates/init-kubernetes/pyproject.toml.j2`, modify the Ops version specifier.
2. At the repo root, create a directory called `generated-temp`.
3. Inside `generated-temp`, run:
    ```text
    CHARMCRAFT_DEVELOPER=1 python -m charmcraft init --profile=kubernetes
    ```
4. Inside `generated-temp`, run `uv lock`.
5. Copy `generated-temp/uv.lock` to `charmcraft/templates/init-kubernetes/uv.lock.j2`, overwriting the existing file.
6. In `charmcraft/templates/init-kubernetes/uv.lock.j2`, replace `generated-temp` by `{{ name }}`.
7. Delete the `generated-temp` directory.

For the `machine` profile, modify the Ops version specifier in `charmcraft/templates/init-machine/pyproject.toml.j2`. Then run a diff between `.../init-machine/pyproject.toml.j2` and `.../init-kubernetes/pyproject.toml.j2`. If the files match, copy `uv.lock.j2` from the `kubernetes` profile to the `machine` profile. Otherwise, repeat the full process for the `machine` profile.

Commit your changes. You should have changed these files:
* charmcraft/templates/init-kubernetes/pyproject.toml.j2
* charmcraft/templates/init-kubernetes/uv.lock.j2
* charmcraft/templates/init-machine/pyproject.toml.j2
* charmcraft/templates/init-machine/uv.lock.j2
