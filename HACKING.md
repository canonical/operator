
# Setting up a Dev Environment

To work in the framework itself you will need Python >= 3.5. Linting, testing,
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
you can run `go install github.com/canonical/pebble@latest`.  This will
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

