import importlib
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Type

import pytest
import yaml

from scenario import Context, Relation, State
from scenario.context import ContextSetupError
from scenario.state import CharmType, MetadataNotFoundError, _CharmSpec

CHARM = """
from ops import CharmBase

class MyCharm(CharmBase): pass
"""


@contextmanager
def import_name(name: str, source: Path) -> Type[CharmType]:
    pkg_path = str(source.parent)
    sys.path.append(pkg_path)
    charm = importlib.import_module("mycharm")
    obj = getattr(charm, name)
    sys.path.remove(pkg_path)
    yield obj
    del sys.modules["mycharm"]


@contextmanager
def create_tempcharm(
    root: Path,
    charm: str = CHARM,
    meta=None,
    actions=None,
    config=None,
    name: str = "MyCharm",
    legacy: bool = False,
):
    src = root / "src"
    src.mkdir(parents=True)
    charmpy = src / "mycharm.py"
    charmpy.write_text(charm)

    # we add a charmcraft.yaml file to verify that _CharmSpec._load_metadata
    # is able to tell that the presence of charmcraft.yaml ALONE is not enough
    # to make this a valid charm
    charmcraft = {"builds-on": "literally anywhere! isn't that awesome?"}
    (root / "charmcraft.yaml").write_text(yaml.safe_dump(charmcraft))

    if legacy:
        if meta is not None:
            (root / "metadata.yaml").write_text(yaml.safe_dump(meta))

        if actions is not None:
            (root / "actions.yaml").write_text(yaml.safe_dump(actions))

        if config is not None:
            (root / "config.yaml").write_text(yaml.safe_dump(config))
    else:
        unified_meta = meta or {}

        if actions:
            unified_meta["actions"] = actions
        if config:
            unified_meta["config"] = config
        if unified_meta:
            (root / "charmcraft.yaml").write_text(yaml.safe_dump(unified_meta))

    with import_name(name, charmpy) as charm:
        yield charm


def test_autoload_no_meta_fails(tmp_path):
    with create_tempcharm(tmp_path) as charm:
        with pytest.raises(MetadataNotFoundError):
            _CharmSpec.autoload(charm)


def test_autoload_no_type_fails(tmp_path):
    with create_tempcharm(tmp_path, meta={"name": "foo"}) as charm:
        with pytest.raises(MetadataNotFoundError):
            _CharmSpec.autoload(charm)


def test_autoload_legacy_no_meta_fails(tmp_path):
    with create_tempcharm(tmp_path, legacy=True) as charm:
        with pytest.raises(MetadataNotFoundError):
            _CharmSpec.autoload(charm)


def test_autoload_legacy_no_type_passes(tmp_path):
    with create_tempcharm(tmp_path, legacy=True, meta={"name": "foo"}) as charm:
        _CharmSpec.autoload(charm)


@pytest.mark.parametrize("config_type", ("charm", "foo"))
def test_autoload_legacy_type_passes(tmp_path, config_type):
    with create_tempcharm(
        tmp_path, legacy=True, meta={"type": config_type, "name": "foo"}
    ) as charm:
        _CharmSpec.autoload(charm)


@pytest.mark.parametrize("legacy", (True, False))
def test_meta_autoload(tmp_path, legacy):
    with create_tempcharm(
        tmp_path,
        legacy=legacy,
        meta={"type": "charm", "name": "foo", "summary": "foo", "description": "foo"},
    ) as charm:
        ctx = Context(charm)
        ctx.run(ctx.on.start(), State())


@pytest.mark.parametrize("legacy", (True, False))
def test_no_meta_raises(tmp_path, legacy):
    with create_tempcharm(
        tmp_path,
        legacy=legacy,
    ) as charm:
        # metadata not found:
        with pytest.raises(ContextSetupError):
            Context(charm)


@pytest.mark.parametrize("legacy", (True, False))
def test_relations_ok(tmp_path, legacy):
    with create_tempcharm(
        tmp_path,
        legacy=legacy,
        meta={
            "type": "charm",
            "summary": "foo",
            "description": "foo",
            "name": "josh",
            "requires": {"cuddles": {"interface": "arms"}},
        },
    ) as charm:
        # this would fail if there were no 'cuddles' relation defined in meta
        ctx = Context(charm)
        ctx.run(ctx.on.start(), State(relations={Relation("cuddles")}))


@pytest.mark.parametrize("legacy", (True, False))
def test_config_defaults(tmp_path, legacy):
    with create_tempcharm(
        tmp_path,
        legacy=legacy,
        meta={
            "type": "charm",
            "name": "josh",
            "summary": "foo",
            "description": "foo",
        },
        config={"options": {"foo": {"type": "bool", "default": True}}},
    ) as charm:
        # this would fail if there were no 'cuddles' relation defined in meta
        ctx = Context(charm)
        with ctx(ctx.on.start(), State()) as mgr:
            mgr.run()
            assert mgr.charm.config["foo"] is True
