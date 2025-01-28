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
"""Buffer for tracing data."""

from __future__ import annotations

import contextlib
import logging
import os
import pathlib
import sqlite3
import tempfile
import typing
from typing import IO

# TODO: bike-shedding, how much? 40M? 64M? etc.
# Approximate safety limit for the database file size
BUFFER_SIZE = 40 * 1024 * 1024

# Default priority for tracing data.
# Dispatch invocation that doesn't result in any event being observed
# by charm or its charm lib produces data at this priority.
DEFAULT_PRIORITY = 10

# Higher priority for data from invocation with observed events.
OBSERVED_PRIORITY = 50

# Some DB timeout
# NOTE: we'd want a high initial timeout and low timeout on exit, perhaps?
DB_TIMEOUT = 60

# - new autocommit flag was added in 3.11
# - must use isolation_level=None for consistency between Python versions
# - may want to use isolation_level=None anyway, for manual transaction control
# - can't use the STRICT keyword for tables, requires sqlite 3.37.0
# - can't use the octet_length() either, requires 3.43.0
#
# Summary
#
# Ubuntu 20.04  Python  3.8.x  Sqlite 3.31.1  Adds UPSERT, window functions
# Ubuntu 22.04  Python 3.10.x  Sqlite 3.37.2  Adds STRICT tables, JSON ops
# Ubuntu 24.04  Python 3.12.x  Sqlite 3.45.2  Adds math functions

logger = logging.getLogger(__name__)


class Buffer:
    """Buffer for tracing data."""

    _ids: set[int] | None
    """tracing data ids buffered during this dispatch invocation.

    None if we're not recording the ids.
    Access to this attribute is effectively protected by an sqlite transaction.
    """

    priority: int = DEFAULT_PRIORITY
    """current priority for tracing data from this dispatch invocation.

    Access to this attribute is effectively protected by an sqlite transaction.
    """

    def __init__(self, path: str):
        self._ids = set()
        self.path = path
        # NOTE: measure the cost of this vs two-level approach:
        # - check table and index in read-only mode
        # - if needed, update the DSL
        # NOTE: ops storage sets u+rw, go-rw permissions
        # should we follow suit?
        with self.tx() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tracing (
                    -- effectively auto-incremented
                    id INTEGER PRIMARY KEY,
                    -- observed events are more important
                    priority INTEGER NOT NULL,
                    -- Protobuf-formatted tracing data
                    data BLOB NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS tracing_priority_id
                ON tracing
                (priority, id)
                """
            )

    @contextlib.contextmanager
    # TODO: maybe add a mode="w" flag if read-only transactions are needed
    def tx(self):
        """Thread-safe transaction context manager."""
        with sqlite3.connect(self.path, isolation_level=None, timeout=DB_TIMEOUT) as conn:
            conn.execute('BEGIN IMMEDIATE')
            try:
                yield conn
            except:
                conn.execute('ROLLBACK')
                raise
            else:
                conn.execute('COMMIT')

    def mark_observed(self):
        if self._ids is None:
            return

        with self.tx() as conn:
            conn.execute(
                f"""
                UPDATE tracing
                SET priority = ?
                WHERE id IN ({','.join(('?',) * len(self._ids))})
                """,  # noqa: S608
                (OBSERVED_PRIORITY, *tuple(self._ids)),
            )
            self.priority = OBSERVED_PRIORITY
            self._ids = None

    def pump(self, chunk: bytes | None = None) -> tuple[int, bytes] | None:
        """Pump the buffer queue.

        Accepts an optional new data chunk.
        Removes old, boring data if needed.
        Returns the oldest important record.
        """
        # NOTE: discussion about transaction type:
        # - this may be a read-only transaction (no data to save, read out one record)
        # - or a read transaction later upgraded to write (check space, then delete some)
        # currently I've made `self.tx()` return a write transaction always
        # which is safer, but may incur a filesystem modification cost.
        with self.tx() as conn:
            if chunk:
                # Ensure that there's enough space in the buffer
                chunklen = (len(chunk) + 4095) // 4096 * 4096
                stored: int | None = conn.execute(
                    """
                    SELECT sum((length(data)+4095)/4096*4096)
                    FROM tracing
                    """
                ).fetchone()[0]
                excess = (stored or 0) + chunklen - BUFFER_SIZE
                logging.debug(f'{excess=}')

                if excess > 0:
                    # Drop lower-priority, older data
                    cursor = conn.execute(
                        """
                        SELECT id, (length(data)+4095)/4096*4096
                        FROM tracing
                        ORDER BY priority ASC, id ASC
                        """
                    )

                    collected_ids: set[int] = set()
                    collected_size: int = 0
                    for id_, size in cursor:
                        collected_ids.add(id_)
                        collected_size += size
                        if collected_size > excess:
                            break

                    assert collected_ids
                    logging.debug(f'{len(collected_ids)=}')
                    conn.execute(
                        f"""
                        DELETE FROM tracing
                        WHERE id IN ({','.join(('?',) * len(collected_ids))})
                        """,  # noqa: S608
                        tuple(collected_ids),
                    )

                # Store the new tracing data
                cursor = conn.execute(
                    """
                    INSERT INTO tracing (priority, data)
                    VALUES (?, ?)
                    """,
                    (self.priority, chunk),
                )

                assert cursor.lastrowid is not None
                if self._ids is not None:
                    self._ids.add(cursor.lastrowid)

            # Return oldest important data
            return conn.execute(
                """
                SELECT id, data
                FROM tracing
                ORDER BY priority DESC, id ASC
                LIMIT 1
                """
            ).fetchone()

    def remove(self, id_: int):
        with self.tx() as conn:
            conn.execute(
                """
                DELETE FROM tracing
                WHERE id = ?
                """,
                (id_,),
            )
            if self._ids:
                self._ids -= {id_}

    def pivot(self, buffer_path: typing.Any) -> None:
        raise NotImplementedError('TODO')


# FIXME: this only makes sense if we want to
# pick up the old tracing data that was buffered
# by the charm-tracing charm lib before charm was upgraded
# It's contingent on being able to send protobugs,
# the other option is to switch to JSON and wipe old data on upgrade.
SEPARATOR = b'__CHARM_TRACING_BUFFER_SPAN_SEP__'
"""Exact, verbatim value that separates buffered chunks."""
BUFFER_SAFETY_LIMIT = 64 * 1024 * 1024


class DropBinaryBuffer:
    """On-disk buffer for bytes, anonymous or at a path."""

    file: IO[bytes]
    """A Python file.

    Holds an open file descriptor to a file-system file in which the data is stored.
    The file offset points to one-past-last-byte of data.
    """

    def __init__(self):
        self.file = tempfile.TemporaryFile(mode='wb+')  # noqa: SIM115

    def pivot(self, buffer_path: pathlib.Path) -> None:
        """Pivot from anonymous temporary file to a named buffer file."""
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
            logger.warning('Buffer full, dropping old data')
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

    def __len__(self) -> int:
        return self.file.tell()
