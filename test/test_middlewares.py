from unittest.mock import patch, MagicMock

# impossible to test with harness ATM since harness doesn't mock at the level of `main`.
from scenario import Context
from scenario.state import State

from middlewares import Middleware
from ops import CharmBase, Framework


class MyCharm(CharmBase):
    def __init__(self, framework: Framework):
        super().__init__(framework)

        self.foo = 1


class MyMiddleware(Middleware):
    def pre_init(self, charm: CharmBase):
        assert not hasattr(charm, "foo")  # not yet, anyway

    def post_init(self, charm: CharmBase):
        assert charm.foo


def test_middleware_setup_called():
    for name in ("pre_init", "post_init"):
        with patch.object(MyMiddleware, name, new=MagicMock()) as p:
            c = Context(MyCharm, meta={"name": "middleman"},
                        middlewares=[MyMiddleware()]
                        ).run("update-status", State())
        assert p.called
