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

These test the _EntityStatus and Port conversions between scenario and ops.
Both are pure in-memory round-trips with a wide input space and a simple
invariant, which is where property-based testing earns its keep.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st
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

# Every status type. UnknownStatus takes no message, so it is the one fixed value.
_status_strategy = st.one_of(
    st.builds(ActiveStatus, message=st.text()),
    st.builds(BlockedStatus, message=st.text()),
    st.builds(MaintenanceStatus, message=st.text()),
    st.builds(WaitingStatus, message=st.text()),
    st.builds(ErrorStatus, message=st.text()),
    st.just(UnknownStatus()),
)

# All three concrete Port types; TCPPort/UDPPort accept validated port numbers.
_port_strategy = st.one_of(
    st.integers(min_value=1, max_value=65535).map(TCPPort),
    st.integers(min_value=1, max_value=65535).map(UDPPort),
    st.just(ICMPPort()),
)


# ── tests ────────────────────────────────────────────────────────────────────


@given(status=_status_strategy)
def test_entity_status_ops_roundtrip(status: _EntityStatus) -> None:
    """_EntityStatus → ops.StatusBase → _EntityStatus preserves name and message.

    This bridges the scenario and ops status representations; any mismatch in
    the name/message mapping would silently corrupt the visible status after a
    charm event.
    """
    round_tripped = _EntityStatus.from_ops(status._to_ops())
    assert round_tripped == status
    assert round_tripped.name == status.name
    assert round_tripped.message == status.message


@given(port=_port_strategy)
def test_port_to_ops_preserves_attributes(port: TCPPort | UDPPort | ICMPPort) -> None:
    """Port._to_ops() faithfully copies port number and protocol to ops.Port.

    If the mapping were to swap protocol strings or clamp the port number, ops
    would open the wrong port at runtime.
    """
    ops_port = port._to_ops()
    assert ops_port.port == port.port
    assert ops_port.protocol == port.protocol
