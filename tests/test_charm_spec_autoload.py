import importlib
import sys
import tempfile
from contextlib import contextmanager
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


@contextmanager
def import_name(name: str, source: Path) -> Type[CharmType]:
    pkg_path = str(source.parent)
    sys.path.append(pkg_path)
    charm = importlib.import_module("charm")
    obj = getattr(charm, name)
    sys.path.remove(pkg_path)
    yield obj
    del sys.modules["charm"]


@contextmanager
def create_tempcharm(
    root: Path,
    charm: str = CHARM,
    meta=None,
    actions=None,
    config=None,
    name: str = "MyCharm",
):
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

    with import_name(name, charmpy) as charm:
        yield charm


def test_meta_autoload(tmp_path):
    with create_tempcharm(tmp_path, meta={"name": "foo"}) as charm:
        ctx = Context(charm)
        ctx.run("start", State())


def test_no_meta_raises(tmp_path):
    with create_tempcharm(
        tmp_path,
    ) as charm:
        # metadata not found:
        with pytest.raises(ContextSetupError):
            Context(charm)


def test_relations_ok(tmp_path):
    with create_tempcharm(
        tmp_path, meta={"name": "josh", "requires": {"cuddles": {"interface": "arms"}}}
    ) as charm:
        # this would fail if there were no 'cuddles' relation defined in meta
        Context(charm).run("start", State(relations=[Relation("cuddles")]))


def test_config_defaults(tmp_path):
    with create_tempcharm(
        tmp_path,
        meta={"name": "josh"},
        config={"options": {"foo": {"type": "bool", "default": True}}},
    ) as charm:
        # this would fail if there were no 'cuddles' relation defined in meta
        with Context(charm).manager("start", State()) as mgr:
            mgr.run()
            assert mgr.charm.config["foo"] is True
