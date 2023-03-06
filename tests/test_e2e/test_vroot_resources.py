import tempfile
from pathlib import Path

from ops.charm import CharmBase
from ops.framework import Framework
from ops.model import ActiveStatus

from scenario import State


class MyCharm(CharmBase):
    META = {"name": "my-charm"}

    def __init__(self, framework: Framework):
        super().__init__(framework)
        foo = self.framework.charm_dir / "src" / "foo.bar"
        baz = self.framework.charm_dir / "src" / "baz" / "qux.kaboodle"

        self.unit.status = ActiveStatus(f"{foo.read_text()} {baz.read_text()}")


def test_resources():
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        foobar = t / "foo.bar"
        foobar.write_text("hello")

        baz = t / "baz"
        baz.mkdir(parents=True)
        quxcos = baz / "qux.cos"
        quxcos.write_text("world")

        out = State().trigger(
            "start",
            charm_type=MyCharm,
            meta=MyCharm.META,
            copy_to_charm_root={
                "/src/foo.bar": foobar,
                "/src/baz/qux.kaboodle": quxcos,
            },
        )

    assert out.status.unit == ("active", "hello world")
