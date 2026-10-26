# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

from __future__ import annotations

import pytest
from scenario import Context, ICMPPort, Port, State, TCPPort, UDPPort
from scenario.errors import StateValidationError

import ops
from ops import CharmBase, Framework, StartEvent, StopEvent


class Charm(CharmBase):
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
def ctx() -> Context[Charm]:
    return Context(Charm, meta={'name': 'edgar'})


def test_open_port(ctx: Context[Charm]):
    out = ctx.run(ctx.on.start(), State())
    ports = tuple(out.opened_ports)
    assert len(ports) == 1
    port = ports[0]

    assert port.protocol == 'tcp'
    assert port.port == 12


def test_close_port(ctx: Context[Charm]):
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


def test_state_normalises_ops_ports():
    state = State(opened_ports=[ops.Port('tcp', 80), ops.Port('udp', 53), ops.Port('icmp', None)])
    assert state.opened_ports == {TCPPort(80), UDPPort(53), ICMPPort()}
    assert {type(port) for port in state.opened_ports} == {TCPPort, UDPPort, ICMPPort}


def test_port_equality_with_ops_port():
    assert TCPPort(80) == ops.Port('tcp', 80)
    assert UDPPort(53) == ops.Port('udp', 53)
    assert ICMPPort() == ops.Port('icmp', None)
    assert TCPPort(80) != UDPPort(80)
    assert TCPPort(80) != ops.Port('tcp', 81)
    assert TCPPort(80) in {TCPPort(80)}
