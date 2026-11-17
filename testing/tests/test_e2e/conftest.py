# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

from __future__ import annotations

import pathlib
from collections.abc import Generator
from typing import Any

import pytest
import yaml
from scenario import Context

from test.charms.test_secrets.src.charm import SecretsCharm


@pytest.fixture
def secrets_context(secrets_charm_meta: dict[str, Any]):
    return Context(SecretsCharm, meta=secrets_charm_meta)


@pytest.fixture
def secrets_charm_meta() -> Generator[dict[str, Any]]:
    """Metadata for the secret test charm."""
    # The repository root, so the path doesn't depend on pytest's rootdir.
    root = pathlib.Path(__file__).parents[3]
    return yaml.safe_load((root / 'test/charms/test_secrets/charmcraft.yaml').read_text())
