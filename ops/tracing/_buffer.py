# Copyright 2025 Canonical Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this
# file except in compliance with the License. You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software distributed under
# the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF
# ANY KIND, either express or implied. See the License for the specific language
# governing permissions and limitations under the License.
"""FIXME Docstring."""
from __future__ import annotations

import logging
import os
import pathlib
import tempfile
from typing import IO

BUFFER_SAFETY_LIMIT = 64 * 1024 ** 2
SEPARATOR = b'__CHARM_TRACING_BUFFER_SPAN_SEP__'
"""Exact, verbatim value that separates buffered chunks."""

logger = logging.getLogger(__name__)


class Buffer:
    """On-disk buffer for bytes, anonymous or at a path."""

    file: IO[bytes]
    """A Python file.

    Holds an open file descriptor to a file-system file in which the data is stored.
    The file offset points to one-past-last-byte of data.
    """

    def __init__(self):
        self.file = tempfile.TemporaryFile(mode='wb+')

    def pivot(self, buffer_path: pathlib.Path) -> None:
        """Pivot fron anonymous temporary file to a named buffer file."""
        self.file.seek(0)
        data = self.file.read()

        self.file = os.fdopen(os.open(buffer_path, os.O_RDWR | os.O_CREAT), 'rb+')
        self.file.seek(0, os.SEEK_END)
        self.append(data)

    def append(self, data: bytes) -> None:
        load = self.file.tell()
        # FIXME maybe some protection against double pivot.
        # or against doubling by pivot to the very same path.

        if load and data and load + len(SEPARATOR) + len(data) > BUFFER_SAFETY_LIMIT:
            logger.warning("Buffer full, dropping old data")
            self.file.seek(0)
            self.file.truncate(0)
            load = 0

        if load and data:
            self.file.write(SEPARATOR + data)
        elif data:
            self.file.write(data)

    def load(self) -> list[bytes]:
        """Load currently buffered spans from the cache file.

        This method should be as fail-safe as possible.
        """
        self.file.seek(0)
        return [chunk for chunk in self.file.read().split(SEPARATOR) if chunk]

    def drop(self) -> None:
        self.file.seek(0)
        self.file.truncate(0)
