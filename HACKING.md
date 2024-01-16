# Setting up a Dev Environment

To work in the framework itself you will need Python >= 3.8. Linting, testing,
and docs automation is performed using
[`tox`](https://tox.readthedocs.io/en/latest/), which you should install.
For improved performance on the tests, ensure that you have PyYAML
installed with the correct extensions:

```sh
apt-get install libyaml-dev
pip install --force-reinstall --no-cache-dir pyyaml
```

# Testing

The following are likely to be useful during development:

```sh
# Run linting and unit tests
tox

# Run tests, specifying whole suite or specific files
tox -e unit
tox -e unit test/test_charm.py

# Format the code using isort and autopep8
tox -e fmt

# Generate a local copy of the Sphinx docs in docs/_build
tox -e docs

# run only tests matching a certain pattern
tox -e unit -- -k <pattern>
```

For more in depth debugging, you can enter any of `tox`'s created virtualenvs
provided they have been run at least once and do fun things - e.g. run
`pytest` directly:

```sh
# Enter the linting virtualenv
source .tox/lint/bin/activate

...

# Enter the unit testing virtualenv and run tests
source .tox/unit/bin/activate
pytest
...

```

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

# Documentation

In general, new functionality
should always be accompanied by user-focused documentation that is posted to
https://juju.is/docs/sdk.  The content for this site is written and hosted on
https://discourse.charmhub.io/c/doc.  New documentation should get a new
topic/post on this Discourse forum and then should be linked into the main
docs navigation page(s) as appropriate.  The ops library's SDK page
content is pulled from
[the corresponding Discourse topic](https://discourse.charmhub.io/t/the-charmed-operator-software-development-kit-sdk-docs/4449).
Each page on [juju.is](https://juju.is/docs/sdk) has a link at the bottom that
takes you to the corresponding Discourse page where docs can be commented on
and edited (if you have earned those privileges).

The ops library's API reference is automatically built and published to
[ops.readthedocs.io](https://ops.readthedocs.io/en/latest/).  Please be complete with
docstrings and keep them informative for _users_.

Currently we don't publish separate versions of documentation for separate releases.  Instead, new features should be sign-posted (for example, as done for [File and directory existence in 1.4](https://juju.is/docs/sdk/interact-with-pebble#heading--file-exists)) with Markdown like this:

```markdown
[note status="version"]1.4[/note]
```

next to the relevant content (e.g. headings, etc.).

Noteworthy changes should also get a new entry in [CHANGES.md](CHANGES.md).

As noted above, you can generate a local copy of the API reference docs with tox:

```sh
tox -e docs
open docs/_build/html/index.html
```

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

Formatting uses [isort](https://pypi.org/project/isort/) and
[autopep8](https://pypi.org/project/autopep8/), with linting also using
[flake8](https://github.com/PyCQA/flake8), including the
[docstrings](https://pypi.org/project/flake8-docstrings/),
[builtins](https://pypi.org/project/flake8-builtins/) and
[pep8-naming](https://pypi.org/project/pep8-naming/) extensions.

All tool configuration is kept in [project.toml](pyproject.toml). The list of
dependencies can be found in the relevant `tox.ini` environment `deps` field.

## Building

The build backend is [setuptools](https://pypi.org/project/setuptools/), and
the build frontend is [build](https://pypi.org/project/build/).

# Publishing a Release

To make a release of the ops library, do the following:

1. Open a PR to change [version.py][ops/version.py]'s `version` to the
   [appropriate string](https://semver.org/), and get that merged to main.
2. Visit the [releases page on GitHub](https://github.com/canonical/operator/releases).
3. Click "Draft a new release"
4. The "Release Title" is simply the full version number, in the form <major>.<minor>.<patch>
   and a brief summary of the main changes in the release
   E.g. 2.3.12 Bug fixes for the Juju foobar feature when using Python 3.12
5. Drop notes and a changelog in the description.
6. When you are ready, click "Publish". (If you are not ready, click "Save as Draft".) Wait for the new version to be published successfully to [the PyPI project](https://pypi.org/project/ops/).
7. Open a PR to change [version.py][ops/version.py]'s `version` to the expected
   next version, with "+dev" appended (for example, if 3.14.1 is the next expected version, use
   `'3.14.1.dev0'`).

This will trigger an automatic build for the Python package and publish it to PyPI (authorization is handled via a [Trusted Publisher](https://docs.pypi.org/trusted-publishers/) relationship).

See [.github/workflows/publish.yml](.github/workflows/publish.yml) for details. (Note that the versions in publish.yml refer to versions of the GitHub actions, not the versions of the ops library.)

You can troubleshoot errors on the [Actions Tab](https://github.com/canonical/operator/actions).

Announce the release on [Discourse](https://discourse.charmhub.io/c/framework/42) and [Mattermost](https://chat.charmhub.io/charmhub/channels/charm-dev)
