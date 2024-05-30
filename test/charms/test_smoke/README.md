# smoke

## Description

A simple test charm for running smoke tests.

## Usage

Make sure that you are on a box with charmcraft and juju installed, and that you are connected to a "machine" controller, such as a local lxd cloud.

Then, from the root directory of this repository, execute `tox -e smoke` to build and deploy this charm.
