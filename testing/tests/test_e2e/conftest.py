from __future__ import annotations

import sys
from typing import Any, Generator

import pytest
import yaml

from ops.charm import CharmBase
from scenario import Context


@pytest.fixture
def secrets_context(secrets_charm: CharmBase, secrets_charm_meta: dict[str, Any]):
    return Context(secrets_charm, meta=secrets_charm_meta, actions=secrets_charm_meta['actions'])


@pytest.fixture
def secrets_charm(pytestconfig: pytest.Config) -> Generator[type[CharmBase]]:
    """A reference to the secret test charm class."""
    # FIXME: consider which is better:
    # a. fixture that provides the charm class, or
    # b. fixture that provides a Context with a charm class
    extra = str(pytestconfig.rootpath / 'test/charms/test_secrets/src')
    sys.path.append(extra)
    from charm import TestSecretsCharm  # type: ignore

    yield TestSecretsCharm
    sys.path.remove(extra)
    del sys.modules['charm']


@pytest.fixture
def secrets_charm_meta(pytestconfig: pytest.Config) -> Generator[dict[str, Any]]:
    """Metadata for the secret test charm."""
    return yaml.safe_load(
        (pytestconfig.rootpath / 'test/charms/test_secrets/charmcraft.yaml').read_text()
    )
