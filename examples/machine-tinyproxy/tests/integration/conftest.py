# Copyright 2026 Canonical
# See LICENSE file for licensing details.
#
# The integration tests use the Jubilant library. See https://documentation.ubuntu.com/jubilant/
# The pytest-jubilant plugin (https://github.com/canonical/pytest-jubilant) provides a
# module-scoped `juju` fixture that creates a temporary Juju model.
# To learn more about testing, see https://documentation.ubuntu.com/ops/latest/explanation/testing/

import os
import pathlib

import pytest


@pytest.fixture(scope="session")
def charm():
    """Return the path of the charm under test."""
    charm = os.environ.get("CHARM_PATH")
    if not charm:
        charm_dir = pathlib.Path()  # Assume the current working directory is the charm root.
        charms = list(charm_dir.glob("*.charm"))
        assert charms, f"No charms were found in {charm_dir.absolute()}"
        assert len(charms) == 1, f"Found more than one charm {charms}"
        charm = charms[0]
    path = pathlib.Path(charm).resolve()
    assert path.is_file(), f"{path} is not a file"
    return path
