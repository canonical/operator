import pytest
from ops import CharmBase, Framework, StartEvent, StopEvent

from scenario import Context, State
from scenario.state import Port, StateValidationError, TCPPort, UDPPort


class MyCharm(CharmBase):
    META = {"name": "edgar"}

    def __init__(self, framework: Framework):
        super().__init__(framework)
        framework.observe(self.on.start, self._open_port)
        framework.observe(self.on.stop, self._close_port)

    def _open_port(self, _: StartEvent):
        self.unit.open_port("tcp", 12)

    def _close_port(self, _: StopEvent):
        assert self.unit.opened_ports()
        self.unit.close_port("tcp", 42)


@pytest.fixture
def ctx():
    return Context(MyCharm, meta=MyCharm.META)


def test_open_port(ctx):
    out = ctx.run(ctx.on.start(), State())
    assert len(out.opened_ports) == 1
    port = tuple(out.opened_ports)[0]

    assert port.protocol == "tcp"
    assert port.port == 12


def test_close_port(ctx):
    out = ctx.run(ctx.on.stop(), State(opened_ports={TCPPort(42)}))
    assert not out.opened_ports


def test_port_no_arguments():
    with pytest.raises(RuntimeError):
        Port()


@pytest.mark.parametrize("klass", (TCPPort, UDPPort))
def test_port_port(klass):
    with pytest.raises(StateValidationError):
        klass(port=0)
    with pytest.raises(StateValidationError):
        klass(port=65536)
