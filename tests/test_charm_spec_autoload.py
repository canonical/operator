import importlib
import sys
import tempfile
from pathlib import Path
from typing import Type

import pytest
import yaml
from ops.testing import CharmType

from scenario import Context, Relation, State
from scenario.context import ContextSetupError

CHARM = """
from ops import CharmBase

class MyCharm(CharmBase): pass
"""


def import_name(name: str, source: Path) -> Type[CharmType]:
    pkg_path = str(source.parent)
    sys.path.append(pkg_path)
    charm = importlib.import_module("charm")
    obj = getattr(charm, name)
    sys.path.remove(pkg_path)
    return obj


def create_tempcharm(
    charm: str = CHARM, meta=None, actions=None, config=None, name: str = "MyCharm"
):
    root = Path(tempfile.TemporaryDirectory().name)

    src = root / "src"
    src.mkdir(parents=True)
    charmpy = src / "charm.py"
    charmpy.write_text(charm)

    if meta is not None:
        (root / "metadata.yaml").write_text(yaml.safe_dump(meta))

    if actions is not None:
        (root / "actions.yaml").write_text(yaml.safe_dump(actions))

    if config is not None:
        (root / "config.yaml").write_text(yaml.safe_dump(config))

    return import_name(name, charmpy)


def test_meta_autoload(tmp_path):
    charm = create_tempcharm(meta={"name": "foo"})
    ctx = Context(charm)
    ctx.run("start", State())


def test_no_meta_raises(tmp_path):
    charm = create_tempcharm()
    with pytest.raises(ContextSetupError):
        Context(charm)


def test_relations_ok(tmp_path):
    charm = create_tempcharm(
        meta={"name": "josh", "requires": {"cuddles": {"interface": "arms"}}}
    )
    # this would fail if there were no 'cuddles' relation defined in meta
    Context(charm).run("start", State(relations=[Relation("cuddles")]))


def test_config_defaults(tmp_path):
    charm = create_tempcharm(
        meta={"name": "josh"},
        config={"options": {"foo": {"type": "bool", "default": True}}},
    )
    # this would fail if there were no 'cuddles' relation defined in meta
    with Context(charm).manager("start", State()) as mgr:
        mgr.run()
        assert mgr.charm.config["foo"] is True
