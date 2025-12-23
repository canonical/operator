# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest
import yaml
from scenario import Context

from test.charms.test_secrets.src.charm import SecretsCharm


@pytest.fixture
def secrets_context(secrets_charm_meta: dict[str, Any]):
    return Context(SecretsCharm, meta=secrets_charm_meta, actions=secrets_charm_meta['actions'])


@pytest.fixture
def secrets_charm_meta(pytestconfig: pytest.Config) -> Generator[dict[str, Any]]:
    """Metadata for the secret test charm."""
    return yaml.safe_load(
        (pytestconfig.rootpath / 'test/charms/test_secrets/charmcraft.yaml').read_text()
    )
