from __future__ import annotations

import pytest
from ops import CharmBase, Framework, StartEvent, StopEvent

from scenario import Context, State
from scenario.errors import StateValidationError
from scenario.state import Port, TCPPort, UDPPort


class MyCharm(CharmBase):
    META = {'name': 'edgar'}

    def __init__(self, framework: Framework):
        super().__init__(framework)
        framework.observe(self.on.start, self._open_port)
        framework.observe(self.on.stop, self._close_port)

    def _open_port(self, _: StartEvent):
        self.unit.open_port('tcp', 12)

    def _close_port(self, _: StopEvent):
        assert self.unit.opened_ports()
        self.unit.close_port('tcp', 42)


@pytest.fixture
def ctx() -> Context[MyCharm]:
    return Context(MyCharm, meta=MyCharm.META)


def test_open_port(ctx: Context[MyCharm]):
    out = ctx.run(ctx.on.start(), State())
    ports = tuple(out.opened_ports)
    assert len(ports) == 1
    port = ports[0]

    assert port.protocol == 'tcp'
    assert port.port == 12


def test_close_port(ctx: Context[MyCharm]):
    out = ctx.run(ctx.on.stop(), State(opened_ports={TCPPort(42)}))
    assert not out.opened_ports


def test_port_no_arguments():
    with pytest.raises(RuntimeError):
        Port()


@pytest.mark.parametrize('klass', (TCPPort, UDPPort))
def test_port_port(klass: type[Port]):
    with pytest.raises(StateValidationError):
        klass(port=0)
    with pytest.raises(StateValidationError):
        klass(port=65536)
