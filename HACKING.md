We welcome contributions to Ops! Before you start work on a contribution, please also read [CONTRIBUTING.md](./CONTRIBUTING.md).

# Setting up a Dev Environment

To work in the framework itself you will need Python >= 3.8. Linting, testing,
and docs automation is performed using
[`tox`](https://tox.readthedocs.io/en/latest/).

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
#ops ~= 2.9
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
and extends the Python 3.8 type hinting support through the
[typing_extensions](https://pypi.org/project/typing-extensions/) package.

Formatting uses [Ruff](https://docs.astral.sh/ruff/).

All tool configuration is kept in [project.toml](pyproject.toml). The list of
dependencies can be found in the relevant `tox.ini` environment `deps` field.

## Building

The build backend is [setuptools](https://pypi.org/project/setuptools/), and
the build frontend is [build](https://pypi.org/project/build/).

# Publishing a Release

To make a release of the `ops` and/or `ops-scenario` packages, do the following:

1. Check if there's a `chore: update charm pins` auto-generated PR in the queue.
   If it looks good, merge it and check that tests still pass. If needed, you
   can re-trigger the `Update Charm Pins` workflow manually to ensure latest
   charms and ops get tested.
2. Visit the [releases page on GitHub](https://github.com/canonical/operator/releases).
3. Click "Draft a new release"
4. The "Release Title" is the full version numbers of ops and ops-scenario,
   in the form `ops <major>.<minor>.<patch> and ops-scenario <major>.<minor>.<patch>`
   and a brief summary of the main changes in the release.
   For example: `2.3.12 Bug fixes for the Juju foobar feature when using Python 3.12`
5. Have the release create a new tag, in the form `<major>.<minor>.<patch>` for `ops`.
6. Leave the previous tag choice on `auto`.
7. Use the "Generate Release Notes" button to get a copy of the changes into the
   notes field.
8. Format the auto-generated release notes according to the 'Release Documentation'
   section below, save the release notes as a draft, and have someone else in the
   Charm-Tech team proofread it.
9. Format the auto-generated release notes according to the `CHANGES.md` section below,
   and add it to `CHANGES.md`.
10. Change the versions for `ops`, `ops-scenario` and `ops-tracing` to the versions
   being released: `ops==2.xx.y, ops-tracing==2.xx.y, ops-scenario==7.xx.y`.
   We use both [semantic versioning](https://semver.org/) and lockstep releases, so if
   one library requires a version bump, the other will too. There will be a total of
   seven changes:
    - in [ops/version.py for `ops`](ops/version.py), the version declared in the `version` variable
    - in [pyroject.toml for `ops`](pyproject.toml), the required versions for `ops-scenario` and `ops-tracing`
    - in [pyproject.toml for `ops-scenario`](testing/pyproject.toml), the `version` attribute and the required version for `ops`
    - in [pyproject.toml for `ops-tracing`](tracing/pyproject.toml), the `version` attribute and the required version for `ops`
11. Add, commit, and push, and open a PR to get the `CHANGES.md` update and version
   bumps into main (and get it merged).
12. Wait until the tests pass after the PR is merged. It takes around 10 minutes.
   If the tests don't pass at the tip of the main branch, do not release.
13. When you are ready, click "Publish". GitHub will create the additional tag.

    Pushing the tags will trigger automatic builds for the Python packages and
    publish them to PyPI ([ops](https://pypi.org/project/ops/) and
    [ops-scenario](https://pypi.org/project/ops-scenario)) (authorisation is handled
    via a [Trusted Publisher](https://docs.pypi.org/trusted-publishers/) relationship).
    Note that it sometimes take a bit of time for the new releases to show up.

    See [.github/workflows/publish-ops.yaml](.github/workflows/publish-ops.yaml) and
    [.github/workflows/publish-ops-scenario.yaml](.github/workflows/publish-ops-scenario.yaml) for details.
    (Note that the versions in the YAML refer to versions of the GitHub actions, not the versions of the ops  library.)

    You can troubleshoot errors on the [Actions Tab](https://github.com/canonical/operator/actions).
14. Announce the release on [Discourse](https://discourse.charmhub.io/c/framework/42)
    and [Matrix](https://matrix.to/#/#charmhub-charmdev:ubuntu.com).
15. Open a PR to change the version strings to the expected next version, with ".dev0" appended.
   For example, if 2.90.0 is the next expected `ops` version, use
   `ops==2.90.0.dev0 ops-tracing==2.90.0.dev0 ops-scenario==7.90.0.dev0`.
   There will be a total of seven changes:
    - in [pyroject.toml for `ops`](pyproject.toml), the required versions for `ops-scenario` and `ops-tracing`
    - in [ops/version.py for `ops`](ops/version.py), the version declared in the `version` variable
    - in [pyproject.toml for `ops-scenario`](testing/pyproject.toml), the `version` attribute and the required version for `ops`
    - in [pyproject.toml for `ops-tracing`](tracing/pyproject.toml), the `version` attribute and the required version for `ops`

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
**Full Changelog**: https://github.com/canonical/operator/compare/2.17.0...2.18.0
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
