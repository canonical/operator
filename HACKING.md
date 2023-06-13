# Setting up a Dev Environment

To work in the framework itself you will need Python >= 3.8. Linting, testing,
and docs automation is performed using
[`tox`](https://tox.readthedocs.io/en/latest/) which you should install.
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

# Format the code using isort
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

The framework has some tests that interact with a real/live pebble server.  To
run these tests, you must have (pebble)[https://github.com/canonical/pebble]
installed and available in your path.  If you have the Go toolchain installed,
you can run `go install github.com/canonical/pebble/cmd/pebble@latest`.  This will
install pebble to `$GOBIN` if it is set or `$HOME/go/bin` otherwise.  Add
`$GOBIN` to your path (e.g. `export PATH=$PATH:$GOBIN` or `export
PATH=$PATH:$HOME/go/bin` in your `.bashrc`) and you are ready to run the real
pebble tests:

```sh
tox -e pebble
```

To do this even more manually, you could start the pebble server yourself:

```sh
export PEBBLE=$HOME/pebble
export RUN_REAL_PEBBLE_TESTS=1
pebble run --create-dirs &>pebble.log &

# Then
tox -e unit -- -k RealPebble
# or
source .tox/unit/bin/activate
pytest -v -k RealPebble
```

# Documentation

In general, new functionality
should always be accompanied by user-focused documentation that is posted to
https://juju.is/docs/sdk.  The content for this site is written and hosted on
https://discourse.charmhub.io/c/doc.  New documentation should get a new
topic/post on this discourse forum and then should be linked into the main
docs navigation page(s) as appropriate.  The ops library's SDK page
content is pulled from
[here](https://discourse.charmhub.io/t/the-charmed-operator-software-development-kit-sdk-docs/4449).
Each page on [juju.is](https://juju.is/docs/sdk) has a link at the bottom that
takes you to the corresponding discourse page where docs can be commented on
and edited (if you have earned those privileges).

The ops library's API reference is automatically built and published to
[here](https://ops.readthedocs.io/en/latest/).  Please be complete with
docstrings and keep them informative for _users_.

Currently we don't publish separate versions of documentation for separate releases.  Instead, new features should be sign-posted like done [here](https://juju.is/docs/sdk/pebble#heading--file-exists) with markdown like this:

```markdown
[note status="version"]1.4[/note]
```

next to the relevant content (e.g. headings, etc.).


## Dependencies

The Python dependencies of `ops` are kept as minimal as possible, to avoid
bloat and to minimise conflict with the charm's dependencies. The dependencies
are listed in [requirements.txt](requirements.txt).


# Publishing a Release

To make a release of the ops library, do the following:

1. Visit the [releases page on github](https://github.com/canonical/operator/releases).
2. Click "Draft a new release"
3. The "Release Title" is simply the full version number, in the form <major>.<minor>.<patch>
   E.g. 2.3.12
4. Drop notes and a changelog in the description.
5. When you are ready, click "Publish". (If you are not ready, click "Save as Draft".)

This will trigger an automatic build for the Python package and publish it to PyPI (the API token/secret is already set up in the repository settings).

See [.github/workflows/publish.yml](.github/workflows/publish.yml) for details. (Note that the versions in publish.yml refer to versions of the github actions, not the versions of the ops library.)

You can troubleshoot errors on the [Actions Tab](https://github.com/canonical/operator/actions).

Announce the release on discourse.
