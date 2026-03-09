# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from scenario import Context, State
from scenario.errors import UncaughtCharmError
from scenario.state import ICMPPort, Port, StateValidationError, TCPPort, UDPPort

import ops
from ops import CharmBase, Framework, StartEvent, StopEvent


class MyCharm(CharmBase):
    META: Mapping[str, Any] = {'name': 'edgar'}

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
def ctx():
    return Context(MyCharm, meta=MyCharm.META)


def test_open_port(ctx):
    out = ctx.run(ctx.on.start(), State())
    assert len(out.opened_ports) == 1
    port = next(iter(out.opened_ports))

    assert port.protocol == 'tcp'
    assert port.port == 12


def test_close_port(ctx):
    out = ctx.run(ctx.on.stop(), State(opened_ports={TCPPort(42)}))
    assert not out.opened_ports


def test_port_no_arguments():
    with pytest.raises(RuntimeError):
        Port()


@pytest.mark.parametrize('klass', (TCPPort, UDPPort))
def test_port_port(klass):
    with pytest.raises(StateValidationError):
        klass(port=0)
    with pytest.raises(StateValidationError):
        klass(port=65536)


# --- Port ranges and endpoints ---


class _RangeCharm(CharmBase):
    META: Mapping[str, Any] = {'name': 'range-charm'}

    def __init__(self, framework: Framework):
        super().__init__(framework)
        framework.observe(self.on.start, self._on_start)
        framework.observe(self.on.stop, self._on_stop)

    def _on_start(self, _: StartEvent):
        self.unit.open_port('tcp', (8000, 8090))

    def _on_stop(self, _: StopEvent):
        self.unit.close_port('tcp', (8000, 8090))


class _ICMPCharm(CharmBase):
    META: Mapping[str, Any] = {'name': 'icmp-charm'}

    def __init__(self, framework: Framework):
        super().__init__(framework)
        framework.observe(self.on.start, self._on_start)

    def _on_start(self, _: StartEvent):
        self.unit.open_port('icmp')


class _UDPRangeCharm(CharmBase):
    META: Mapping[str, Any] = {'name': 'udp-range-charm'}

    def __init__(self, framework: Framework):
        super().__init__(framework)
        framework.observe(self.on.start, self._on_start)

    def _on_start(self, _: StartEvent):
        self.unit.open_port('udp', (5000, 5010))


class _EndpointCharm(CharmBase):
    META: Mapping[str, Any] = {'name': 'endpoint-charm'}

    def __init__(self, framework: Framework):
        super().__init__(framework)
        framework.observe(self.on.start, self._on_start)

    def _on_start(self, _: StartEvent):
        self.unit.open_port('tcp', 8080, endpoints=['ep1'])


class _OverlapCharm(CharmBase):
    META: Mapping[str, Any] = {'name': 'overlap-charm'}

    def __init__(self, framework: Framework):
        super().__init__(framework)
        framework.observe(self.on.start, self._on_start)

    def _on_start(self, _: StartEvent):
        # Overlaps with TCPPort(8000, to_port=8090) in the initial state.
        self.unit.open_port('tcp', (8050, 8100))


class _SetPortsCharm(CharmBase):
    META: Mapping[str, Any] = {'name': 'set-ports-charm'}

    def __init__(self, framework: Framework):
        super().__init__(framework)
        framework.observe(self.on.start, self._on_start)

    def _on_start(self, _: StartEvent):
        self.unit.set_ports(8000, ops.Port('udp', 5000), (9000, 9010))


class _ReadPortsCharm(CharmBase):
    """Charm that asserts the contents of opened_ports() from within the handler."""

    META: Mapping[str, Any] = {'name': 'read-ports-charm'}

    def __init__(self, framework: Framework):
        super().__init__(framework)
        framework.observe(self.on.start, self._on_start)

    def _on_start(self, _: StartEvent):
        ports = self.unit.opened_ports()
        assert len(ports) == 1
        port = next(iter(ports))
        assert port.protocol == 'tcp'
        assert port.port == 8000
        assert port.to_port == 8090


def test_open_port_range():
    ctx = Context(_RangeCharm, meta=_RangeCharm.META)
    out = ctx.run(ctx.on.start(), State())
    assert len(out.opened_ports) == 1
    port = next(iter(out.opened_ports))
    assert port.protocol == 'tcp'
    assert port.port == 8000
    assert port.to_port == 8090


def test_close_port_range():
    ctx = Context(_RangeCharm, meta=_RangeCharm.META)
    out = ctx.run(ctx.on.stop(), State(opened_ports={TCPPort(8000, to_port=8090)}))
    assert not out.opened_ports


def test_open_icmp_port():
    ctx = Context(_ICMPCharm, meta=_ICMPCharm.META)
    out = ctx.run(ctx.on.start(), State())
    assert len(out.opened_ports) == 1
    port = next(iter(out.opened_ports))
    assert port.protocol == 'icmp'
    assert port.port is None


def test_open_udp_range():
    ctx = Context(_UDPRangeCharm, meta=_UDPRangeCharm.META)
    out = ctx.run(ctx.on.start(), State())
    assert len(out.opened_ports) == 1
    port = next(iter(out.opened_ports))
    assert port.protocol == 'udp'
    assert port.port == 5000
    assert port.to_port == 5010


def test_open_port_with_endpoint():
    ctx = Context(_EndpointCharm, meta=_EndpointCharm.META)
    out = ctx.run(ctx.on.start(), State())
    assert len(out.opened_ports) == 1
    port = next(iter(out.opened_ports))
    assert port.protocol == 'tcp'
    assert port.port == 8080
    assert port.endpoints == ('ep1',)


def test_overlapping_port_raises():
    ctx = Context(_OverlapCharm, meta=_OverlapCharm.META)
    with pytest.raises(UncaughtCharmError) as exc_info:
        ctx.run(ctx.on.start(), State(opened_ports={TCPPort(8000, to_port=8090)}))
    assert isinstance(exc_info.value.__cause__, ops.ModelError)


def test_set_ports_via_charm():
    ctx = Context(_SetPortsCharm, meta=_SetPortsCharm.META)
    out = ctx.run(ctx.on.start(), State())
    assert TCPPort(8000) in out.opened_ports
    assert UDPPort(5000) in out.opened_ports
    assert TCPPort(9000, to_port=9010) in out.opened_ports


def test_opened_ports_in_charm():
    # State has a TCP range port open; the charm asserts it can be read back
    # correctly via unit.opened_ports().
    ctx = Context(_ReadPortsCharm, meta=_ReadPortsCharm.META)
    ctx.run(ctx.on.start(), State(opened_ports={TCPPort(8000, to_port=8090)}))


def test_to_port_validation():
    with pytest.raises(StateValidationError):
        TCPPort(8000, to_port=0)
    with pytest.raises(StateValidationError):
        TCPPort(8000, to_port=65536)
    with pytest.raises(StateValidationError):
        UDPPort(8000, to_port=65536)


def test_icmp_port_with_to_port():
    # to_port is not permitted for ICMP since ICMP has no port concept.
    with pytest.raises(TypeError):
        ICMPPort(to_port=80)  # type: ignore
