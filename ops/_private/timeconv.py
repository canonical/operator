# Copyright 2022 Canonical Ltd.
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

"""Time conversion utilities."""

import datetime
import re
from typing import Union

# Matches yyyy-mm-ddTHH:MM:SS(.sss)ZZZ
_TIMESTAMP_RE = re.compile(r'(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(\.\d+)?(.*)')

# Matches [-+]HH:MM
_TIMEOFFSET_RE = re.compile(r'([-+])(\d{2}):(\d{2})')

# Matches n.n<unit> (allow U+00B5 micro symbol as well as U+03BC Greek letter mu)
_DURATION_RE = re.compile(r'([0-9.]+)([a-zµμ]+)')


def parse_rfc3339(s: str) -> datetime.datetime:
    """Parse an RFC3339 timestamp.

    This parses RFC3339 timestamps (which are a subset of ISO8601 timestamps)
    that Go's encoding/json package produces for time.Time values.

    Unfortunately we can't use datetime.fromisoformat(), as that does not
    support more than 6 digits for the fractional second, nor the 'Z' for UTC,
    in Python 3.8 (Python 3.11+ has the required functionality).
    """
    match = _TIMESTAMP_RE.match(s)
    if not match:
        raise ValueError(f'invalid timestamp {s!r}')
    y, m, d, hh, mm, ss, sfrac, zone = match.groups()

    if zone in ('Z', 'z'):
        tz = datetime.timezone.utc
    else:
        match = _TIMEOFFSET_RE.match(zone)
        if not match:
            raise ValueError(f'invalid timestamp {s!r}')
        sign, zh, zm = match.groups()
        tz_delta = datetime.timedelta(hours=int(zh), minutes=int(zm))
        tz = datetime.timezone(tz_delta if sign == '+' else -tz_delta)

    microsecond = round(float(sfrac or '0') * 1000000)
    # Ignore any overflow into the seconds - this aligns with the Python
    # standard library behaviour.
    microsecond = min(microsecond, 999999)

    return datetime.datetime(
        int(y), int(m), int(d), int(hh), int(mm), int(ss), microsecond=microsecond, tzinfo=tz
    )


def parse_duration(s: str) -> datetime.timedelta:
    """Parse a formatted Go duration.

    This is similar to Go's time.ParseDuration function: it parses the output
    of Go's time.Duration.String method, for example "72h3m0.5s". Units are
    required after each number part, and valid units are "ns", "us", "µs",
    "ms", "s", "m", and "h".
    """
    negative = False
    if s and s[0] in '+-':
        negative = s[0] == '-'
        s = s[1:]

    if s == '0':  # no unit is only okay for "0", "+0", and "-0"
        return datetime.timedelta(seconds=0)

    matches = list(_DURATION_RE.finditer(s))
    if not matches:
        raise ValueError('invalid duration: no number-unit groups')
    if matches[0].start() != 0 or matches[-1].end() != len(s):
        raise ValueError('invalid duration: extra input at start or end')

    hours, minutes, seconds, milliseconds, microseconds = 0, 0, 0, 0, 0
    for match in matches:
        number, unit = match.groups()
        if unit == 'ns':
            microseconds += _duration_number(number) / 1000
        elif unit in ('us', 'µs', 'μs'):  # U+00B5 (micro symbol), U+03BC (Greek letter mu)
            microseconds += _duration_number(number)
        elif unit == 'ms':
            milliseconds += _duration_number(number)
        elif unit == 's':
            seconds += _duration_number(number)
        elif unit == 'm':
            minutes += _duration_number(number)
        elif unit == 'h':
            hours += _duration_number(number)
        else:
            raise ValueError(f'invalid duration: invalid unit {unit!r}')

    duration = datetime.timedelta(
        hours=hours,
        minutes=minutes,
        seconds=seconds,
        milliseconds=milliseconds,
        microseconds=microseconds,
    )

    return -duration if negative else duration


def _duration_number(s: str) -> Union[int, float]:
    """Try converting s to int; if that fails, try float; otherwise raise ValueError.

    This is to preserve precision where possible.
    """
    try:
        try:
            return int(s)
        except ValueError:
            return float(s)
    except ValueError:
        # Same exception type, but a slightly more specific error message
        raise ValueError(f'invalid duration: {s!r} is not a valid float') from None
