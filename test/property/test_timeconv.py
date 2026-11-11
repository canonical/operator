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

"""Hypothesis property-based tests for ops._private.timeconv.

``parse_duration`` and ``parse_rfc3339`` read what Go writes: Pebble's
durations and timestamps, and Juju's timestamps. The tests generate a value,
format it the way Go does, and check that parsing gets the value back, to
the microsecond that ``datetime`` can hold.
"""

from __future__ import annotations

import datetime

from hypothesis import given
from hypothesis import strategies as st

from ops._private import timeconv

_NS_PER_US = 1_000
_NS_PER_S = 1_000_000_000

# Go writes U+00B5; parse_duration also accepts U+03BC, which looks the same.
_MICRO_SIGN = '\u00b5'
_GREEK_MU = '\u03bc'

# ── Go-style formatting ─────────────────────────────────────────────────────


def _with_fraction(whole: int, frac: int, digits: int) -> str:
    if not frac:
        return str(whole)
    return f'{whole}.{frac:0{digits}d}'.rstrip('0')


def _go_duration(ns: int) -> str:
    """Format nanoseconds the way Go's time.Duration.String does."""
    if ns == 0:
        return '0s'
    sign = '-' if ns < 0 else ''
    u = abs(ns)
    if u < _NS_PER_S:
        if u < 1_000:
            return f'{sign}{u}ns'
        if u < 1_000_000:
            return sign + _with_fraction(*divmod(u, 1_000), 3) + _MICRO_SIGN + 's'
        return sign + _with_fraction(*divmod(u, 1_000_000), 6) + 'ms'
    secs, frac = divmod(u, _NS_PER_S)
    out = _with_fraction(secs % 60, frac, 9) + 's'
    mins = secs // 60
    if mins:
        out = f'{mins % 60}m' + out
        hours = mins // 60
        if hours:
            out = f'{hours}h' + out
    return sign + out


def _go_timestamp(dt: datetime.datetime, frac_ns: int, sep: str) -> str:
    """Format a datetime the way Go's RFC3339Nano does (Juju uses a space separator)."""
    out = (
        f'{dt.year:04d}-{dt.month:02d}-{dt.day:02d}{sep}'
        f'{dt.hour:02d}:{dt.minute:02d}:{dt.second:02d}'
    )
    if frac_ns:
        out += f'.{frac_ns:09d}'.rstrip('0')
    offset = dt.utcoffset()
    assert offset is not None
    if not offset:
        return out + 'Z'
    minutes = int(offset.total_seconds()) // 60
    sign = '+' if minutes >= 0 else '-'
    hh, mm = divmod(abs(minutes), 60)
    return f'{out}{sign}{hh:02d}:{mm:02d}'


# ── strategies ──────────────────────────────────────────────────────────────

# Go durations are int64 nanoseconds; timedelta can hold all of them.
_durations_ns = st.integers(min_value=-(2**63) + 1, max_value=2**63 - 1)

_offsets = st.integers(min_value=-(23 * 60 + 59), max_value=23 * 60 + 59).map(
    lambda m: datetime.timezone(datetime.timedelta(minutes=m))
)

_timestamps = st.datetimes(
    min_value=datetime.datetime(1, 1, 2),
    max_value=datetime.datetime(9999, 12, 30),
).map(lambda dt: dt.replace(microsecond=0))

# ── tests ───────────────────────────────────────────────────────────────────


@given(_durations_ns)
def test_parse_duration_reads_go_durations(ns: int):
    """Any Go duration string parses to its value, to the microsecond."""
    parsed = timeconv.parse_duration(_go_duration(ns))
    expected = datetime.timedelta(microseconds=ns / _NS_PER_US)
    assert abs(parsed - expected) <= datetime.timedelta(microseconds=1)


@given(_durations_ns, st.sampled_from(['+', '']))
def test_parse_duration_explicit_plus_sign(ns: int, plus: str):
    """A leading "+" makes no difference."""
    formatted = _go_duration(abs(ns))
    assert timeconv.parse_duration(plus + formatted) == timeconv.parse_duration(formatted)


@given(st.integers(min_value=1_000, max_value=999_999))
def test_parse_duration_micro_sign_and_mu_agree(ns: int):
    """The micro sign and the Greek mu mean the same thing."""
    formatted = _go_duration(ns)
    assert _MICRO_SIGN + 's' in formatted
    assert timeconv.parse_duration(formatted) == timeconv.parse_duration(
        formatted.replace(_MICRO_SIGN, _GREEK_MU)
    )


@given(
    _timestamps,
    _offsets,
    st.integers(min_value=0, max_value=_NS_PER_S - 1),
    st.sampled_from(['T', 't', ' ']),
)
def test_parse_rfc3339_reads_go_timestamps(
    naive: datetime.datetime, tz: datetime.timezone, frac_ns: int, sep: str
):
    """Any Go RFC 3339 timestamp parses to the same instant, to the microsecond.

    Fractions that round up to a whole second are clamped, as the standard
    library does, so the result never moves into the next second.
    """
    dt = naive.replace(tzinfo=tz)
    parsed = timeconv.parse_rfc3339(_go_timestamp(dt, frac_ns, sep))
    assert parsed.replace(microsecond=0) == dt
    assert parsed.utcoffset() == dt.utcoffset()
    assert abs(parsed.microsecond * _NS_PER_US - frac_ns) <= _NS_PER_US
