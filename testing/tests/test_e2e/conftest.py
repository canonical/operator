from __future__ import annotations

from typing import Any, Generator

import pytest
import yaml

from scenario import Context
from test.charms.test_secrets.src.charm import TestSecretsCharm


@pytest.fixture
def secrets_context(secrets_charm_meta: dict[str, Any]):
    return Context(
        TestSecretsCharm, meta=secrets_charm_meta, actions=secrets_charm_meta['actions']
    )


@pytest.fixture
def secrets_charm_meta(pytestconfig: pytest.Config) -> Generator[dict[str, Any]]:
    """Metadata for the secret test charm."""
    return yaml.safe_load(
        (pytestconfig.rootpath / 'test/charms/test_secrets/charmcraft.yaml').read_text()
    )
