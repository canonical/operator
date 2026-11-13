# Copyright 2026 Canonical Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Hypothesis property-based tests for scenario.state.

These test the _EntityStatus conversion between scenario and ops, and the
port-number validation of TCPPort, UDPPort and ICMPPort. Both are pure and
in-memory, with a wide input space and a simple invariant, which is where
property-based testing earns its keep.
"""

from __future__ import annotations

import pytest
from hypothesis import example, given
from hypothesis import strategies as st
from scenario.errors import StateValidationError
from scenario.state import (
    ActiveStatus,
    BlockedStatus,
    ErrorStatus,
    ICMPPort,
    MaintenanceStatus,
    TCPPort,
    UDPPort,
    UnknownStatus,
    WaitingStatus,
    _EntityStatus,
)

# ── strategies ──────────────────────────────────────────────────────────────
#
# Strategy design is where Hypothesis pays off or doesn't.
# The choices below are deliberately broad so the tool can discover input
# combinations the authors wouldn't reach for by hand.

# Every status type that carries a message. Unknown is tested separately, because
# it drops its message.
_status_strategy = st.one_of(
    st.builds(ActiveStatus, message=st.text()),
    st.builds(BlockedStatus, message=st.text()),
    st.builds(MaintenanceStatus, message=st.text()),
    st.builds(WaitingStatus, message=st.text()),
    st.builds(ErrorStatus, message=st.text()),
)


# ── tests ────────────────────────────────────────────────────────────────────


@given(status=_status_strategy)
def test_entity_status_ops_roundtrip(status: _EntityStatus) -> None:
    """_EntityStatus → ops.StatusBase → _EntityStatus preserves name and message.

    This bridges the scenario and ops status representations; any mismatch in
    the name/message mapping would silently corrupt the visible status after a
    charm event. The unknown status is the exception: see the next test.
    """
    round_tripped = _EntityStatus.from_ops(status._to_ops())
    assert round_tripped == status
    assert round_tripped.name == status.name
    assert round_tripped.message == status.message


@given(message=st.text())
def test_unknown_status_drops_its_message(message: str) -> None:
    """An unknown status round-trips to UnknownStatus(), whatever its message.

    ops has no message for an unknown status, so it's dropped on the way to ops
    and doesn't come back.
    """
    status = _EntityStatus(name='unknown', message=message)
    assert _EntityStatus.from_ops(status._to_ops()) == UnknownStatus()


@given(port_type=st.sampled_from([TCPPort, UDPPort]), number=st.integers())
# Random integers almost never land on the edges, so check those every time.
@example(port_type=TCPPort, number=0)
@example(port_type=TCPPort, number=1)
@example(port_type=TCPPort, number=65535)
@example(port_type=TCPPort, number=65536)
@example(port_type=UDPPort, number=0)
@example(port_type=UDPPort, number=1)
@example(port_type=UDPPort, number=65535)
@example(port_type=UDPPort, number=65536)
def test_tcp_and_udp_ports_validate_their_range(
    port_type: type[TCPPort | UDPPort], number: int
) -> None:
    """A TCP or UDP port can be created exactly when its number is in [1, 65535]."""
    if 1 <= number <= 65535:
        port = port_type(number)
        assert port._to_ops().port == number
    else:
        with pytest.raises(StateValidationError):
            port_type(number)


@given(number=st.integers())
def test_icmp_port_rejects_any_port(number: int) -> None:
    """ICMP has no ports, so an ICMPPort with any port number is rejected."""
    with pytest.raises(StateValidationError):
        ICMPPort(port=number)
