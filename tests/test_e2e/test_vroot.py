import tempfile
from pathlib import Path

import pytest
import yaml
from ops.charm import CharmBase
from ops.framework import Framework
from ops.model import ActiveStatus

from scenario import Context, State
from tests.helpers import trigger


class MyCharm(CharmBase):
    META = {"name": "my-charm"}

    def __init__(self, framework: Framework):
        super().__init__(framework)
        foo = self.framework.charm_dir / "src" / "foo.bar"
        baz = self.framework.charm_dir / "src" / "baz" / "qux.kaboodle"

        self.unit.status = ActiveStatus(f"{foo.read_text()} {baz.read_text()}")


@pytest.fixture
def vroot():
    with tempfile.TemporaryDirectory() as myvroot:
        t = Path(myvroot)
        src = t / "src"
        src.mkdir()
        foobar = src / "foo.bar"
        foobar.write_text("hello")

        baz = src / "baz"
        baz.mkdir(parents=True)
        quxcos = baz / "qux.kaboodle"
        quxcos.write_text("world")

        yield t


def test_vroot(vroot):
    out = trigger(
        State(),
        "start",
        charm_type=MyCharm,
        meta=MyCharm.META,
        charm_root=vroot,
    )
    assert out.unit_status == ("active", "hello world")


def test_vroot_cleanup_if_exists(vroot):
    meta_file = vroot / "metadata.yaml"
    meta_file.write_text(yaml.safe_dump({"name": "karl"}))

    with Context(MyCharm, meta=MyCharm.META, charm_root=vroot).manager(
        "start",
        State(),
    ) as mgr:
        assert meta_file.exists()
        assert (
            mgr.charm.meta.name == "my-charm"
        )  # not karl! Context.meta takes precedence
        mgr.run()
        assert meta_file.exists()

    assert meta_file.exists()


def test_vroot_cleanup_if_not_exists(vroot):
    meta_file = vroot / "metadata.yaml"

    assert not meta_file.exists()

    with Context(MyCharm, meta=MyCharm.META, charm_root=vroot).manager(
        "start",
        State(),
    ) as mgr:
        assert meta_file.exists()
        assert meta_file.read_text() == yaml.safe_dump({"name": "my-charm"})
        mgr.run()
        assert not meta_file.exists()

    assert not meta_file.exists()
