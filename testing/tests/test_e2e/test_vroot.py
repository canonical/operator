import tempfile
from pathlib import Path

import pytest
import yaml
from ops.charm import CharmBase
from ops.framework import Framework
from ops.model import ActiveStatus

from scenario import Context, State
from ..helpers import trigger


class MyCharm(CharmBase):
    META = {"name": "my-charm"}

    def __init__(self, framework: Framework):
        super().__init__(framework)
        foo = self.framework.charm_dir / "src" / "foo.bar"
        baz = self.framework.charm_dir / "src" / "baz" / "qux.kaboodle"

        self.unit.status = ActiveStatus(f"{foo.read_text()} {baz.read_text()}")


@pytest.fixture
def charm_virtual_root():
    with tempfile.TemporaryDirectory() as mycharm_virtual_root:
        t = Path(mycharm_virtual_root)
        src = t / "src"
        src.mkdir()
        foobar = src / "foo.bar"
        foobar.write_text("hello")

        baz = src / "baz"
        baz.mkdir(parents=True)
        quxcos = baz / "qux.kaboodle"
        quxcos.write_text("world")

        yield t


def test_charm_virtual_root(charm_virtual_root):
    out = trigger(
        State(),
        "start",
        charm_type=MyCharm,
        meta=MyCharm.META,
        charm_root=charm_virtual_root,
    )
    assert out.unit_status == ActiveStatus("hello world")


def test_charm_virtual_root_cleanup_if_exists(charm_virtual_root):
    meta_file = charm_virtual_root / "metadata.yaml"
    raw_ori_meta = yaml.safe_dump({"name": "karl"})
    meta_file.write_text(raw_ori_meta)

    ctx = Context(MyCharm, meta=MyCharm.META, charm_root=charm_virtual_root)
    with ctx(
        ctx.on.start(),
        State(),
    ) as mgr:
        assert meta_file.exists()
        assert meta_file.read_text() == yaml.safe_dump({"name": "my-charm"})
        assert (
            mgr.charm.meta.name == "my-charm"
        )  # not karl! Context.meta takes precedence
        mgr.run()
        assert meta_file.exists()

    # meta file was restored to its previous contents
    assert meta_file.read_text() == raw_ori_meta
    assert meta_file.exists()


def test_charm_virtual_root_cleanup_if_not_exists(charm_virtual_root):
    meta_file = charm_virtual_root / "metadata.yaml"

    assert not meta_file.exists()

    ctx = Context(MyCharm, meta=MyCharm.META, charm_root=charm_virtual_root)
    with ctx(
        ctx.on.start(),
        State(),
    ) as mgr:
        assert meta_file.exists()
        assert meta_file.read_text() == yaml.safe_dump({"name": "my-charm"})
        mgr.run()
        assert not meta_file.exists()

    assert not meta_file.exists()
