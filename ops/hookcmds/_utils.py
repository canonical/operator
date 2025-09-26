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
from typing import (
    Any,
    Mapping,
    MutableMapping,
    cast,
)


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


def format_action_result_dict(
    input: Mapping[str, Any],
    parent_key: str | None = None,
    output: dict[str, str] | None = None,
) -> dict[str, str]:
    """Turn a nested dictionary into a flattened dictionary, using '.' as a key separator.

    This is used to allow nested dictionaries to be translated into the dotted
    format required by the Juju `action-set` hook command in order to set nested
    data on an action.

    Example::

        >>> test_dict = {'a': {'b': 1, 'c': 2}}
        >>> format_action_result_dict(test_dict)
        {'a.b': 1, 'a.c': 2}

    Arguments:
        input: The dictionary to flatten
        parent_key: The string to prepend to dictionary's keys
        output: The current dictionary to be returned, which may or may not yet
            be completely flat

    Returns:
        A flattened dictionary

    Raises:
        ValueError: if the dict is passed with a mix of dotted/non-dotted keys
            that expand out to result in duplicate keys. For example:
            ``{'a': {'b': 1}, 'a.b': 2}``.
    """
    output_: dict[str, str] = output or {}

    for key, value in input.items():
        if parent_key:
            key = f'{parent_key}.{key}'

        if isinstance(value, MutableMapping):
            value = cast('dict[str, Any]', value)
            output_ = format_action_result_dict(value, key, output_)
        elif key in output_:
            raise ValueError(
                f"duplicate key detected in dictionary passed to 'action-set': {key!r}"
            )
        else:
            output_[key] = value

    return output_


def datetime_from_iso(dt: str) -> datetime.datetime:
    """Converts a Juju-specific ISO 8601 string to a datetime object."""
    # Older versions of Python cannot handle the 'Z'.
    return datetime.datetime.fromisoformat(dt.replace('Z', '+00:00'))


def datetime_to_iso(dt: datetime.datetime) -> str:
    """Converts a datetime object to a Juju-specific ISO 8601 string."""
    # Older versions of Python cannot generate the 'Z'.
    if dt.tzinfo == datetime.timezone.utc:
        return dt.isoformat().replace('+00:00', 'Z')
    return dt.isoformat()
