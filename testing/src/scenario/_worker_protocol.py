# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Length-prefixed framing for messages between the test process and a worker.

A charm can write anything to its output, so messages aren't line-delimited:
each is a 4-byte big-endian length followed by that many bytes of UTF-8 JSON.
"""

from __future__ import annotations

import json
import struct
from typing import IO, Any

_HEADER = struct.Struct('>I')


def write_message(stream: IO[bytes], message: dict[str, Any]) -> None:
    """Write one message to ``stream`` and flush it."""
    data = json.dumps(message).encode()
    stream.write(_HEADER.pack(len(data)) + data)
    stream.flush()


def read_message(stream: IO[bytes]) -> dict[str, Any] | None:
    """Read one message from ``stream``, or return ``None`` if it closes first."""
    header = _read_exact(stream, _HEADER.size)
    if header is None:
        return None
    (length,) = _HEADER.unpack(header)
    data = _read_exact(stream, length)
    return None if data is None else json.loads(data)


def _read_exact(stream: IO[bytes], count: int) -> bytes | None:
    # A read from a pipe can return fewer bytes than asked for.
    chunks: list[bytes] = []
    while count:
        chunk = stream.read(count)
        if not chunk:
            return None
        chunks.append(chunk)
        count -= len(chunk)
    return b''.join(chunks)
