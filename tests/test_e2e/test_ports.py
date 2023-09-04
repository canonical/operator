import pytest
from ops import CharmBase

from scenario import Context, State
from scenario.state import Port


class MyCharm(CharmBase):
    META = {"name": "edgar"}


@pytest.fixture
def ctx():
    return Context(MyCharm, meta=MyCharm.META)


def test_open_port(ctx):
    def post_event(charm: CharmBase):
        charm.unit.open_port("tcp", 12)

    out = ctx.run("start", State(), post_event=post_event)
    port = out.opened_ports.pop()

    assert port.protocol == "tcp"
    assert port.port == 12


def test_close_port(ctx):
    def post_event(charm: CharmBase):
        assert charm.unit.opened_ports()
        charm.unit.close_port("tcp", 42)

    out = ctx.run("start", State(opened_ports={Port("tcp", 42)}), post_event=post_event)
    assert not out.opened_ports
