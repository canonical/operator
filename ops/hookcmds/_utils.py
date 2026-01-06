# Copyright 2025 Canonical Ltd.
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

from __future__ import annotations

import datetime
import subprocess

from .._private import timeconv


class Error(Exception):
    """Raised when a hook command exits with a non-zero code."""

    returncode: int
    """Exit status of the child process."""

    cmd: list[str]
    """The full command that was run."""

    stdout: str = ''
    """Stdout output of the child process."""

    stderr: str = ''
    """Stderr output of the child process."""

    def __init__(self, *, returncode: int, cmd: list[str], stdout: str = '', stderr: str = ''):
        self.returncode = returncode
        self.cmd = cmd
        self.stdout = stdout
        self.stderr = stderr
        super().__init__(f'command {cmd!r} exited with status {returncode}')


def run(
    *args: str,
    input: str | None = None,
) -> str:
    try:
        result = subprocess.run(
            args, capture_output=True, check=True, encoding='utf-8', input=input
        )
    except subprocess.CalledProcessError as e:
        raise Error(returncode=e.returncode, cmd=e.cmd, stdout=e.stdout, stderr=e.stderr) from None
    return result.stdout


def datetime_from_iso(dt: str) -> datetime.datetime:
    """Converts a Juju-specific ISO 8601 string to a datetime object."""
    # parse_rfc3339 handles arbitrary precision fractional seconds, but requires a timezone.
    # If no timezone is present, assume UTC (add 'Z').
    if not dt.endswith('Z') and not ('+' in dt[-6:] or '-' in dt[-6:]):
        dt = dt + 'Z'
    return timeconv.parse_rfc3339(dt)


def datetime_to_iso(dt: datetime.datetime) -> str:
    """Converts a datetime object to a Juju-specific ISO 8601 string."""
    # Older versions of Python cannot generate the 'Z'.
    if dt.tzinfo == datetime.timezone.utc:
        return dt.isoformat().replace('+00:00', 'Z')
    return dt.isoformat()
