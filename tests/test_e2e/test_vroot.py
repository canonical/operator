import tempfile
from pathlib import Path

import pytest
from ops.charm import CharmBase
from ops.framework import Framework
from ops.model import ActiveStatus

from scenario import State
from scenario.runtime import DirtyVirtualCharmRootError
from tests.helpers import trigger


class MyCharm(CharmBase):
    META = {"name": "my-charm"}

    def __init__(self, framework: Framework):
        super().__init__(framework)
        foo = self.framework.charm_dir / "src" / "foo.bar"
        baz = self.framework.charm_dir / "src" / "baz" / "qux.kaboodle"

        self.unit.status = ActiveStatus(f"{foo.read_text()} {baz.read_text()}")


def test_vroot():
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

        out = trigger(
            State(),
            "start",
            charm_type=MyCharm,
            meta=MyCharm.META,
            charm_root=t,
        )

    assert out.unit_status == ("active", "hello world")


@pytest.mark.parametrize("meta_overwrite", ["metadata", "actions", "config"])
def test_dirty_vroot_raises(meta_overwrite):
    with tempfile.TemporaryDirectory() as myvroot:
        t = Path(myvroot)
        meta_file = t / f"{meta_overwrite}.yaml"
        meta_file.touch()

        with pytest.raises(DirtyVirtualCharmRootError):
            trigger(
                State(),
                "start",
                charm_type=MyCharm,
                meta=MyCharm.META,
                charm_root=t,
            )
