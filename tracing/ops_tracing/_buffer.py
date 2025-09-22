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

"""Buffer for trace data in the ops-tracing extension."""

from __future__ import annotations

import contextlib
import dataclasses
import functools
import os
import pathlib
import sqlite3
import stat
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from typing_extensions import ParamSpec, TypeVar

    P = ParamSpec('P')
    R = TypeVar('R')

# Must use isolation_level=None for consistency between Python 3.8 and 3.12
# Can't use the STRICT keyword for tables, requires sqlite 3.37.0
# Can't use the octet_length() either, requires sqlite 3.43.0
# Can't use DELETE ... RETURNING, requires sqlite 3.35.0
#
# Ubuntu 20.04  Python  3.8.2  Sqlite 3.31.1  Adds UPSERT, window functions
# Ubuntu 22.04  Python 3.10.x  Sqlite 3.37.2  Adds STRICT tables, JSON ops
# Ubuntu 24.04  Python 3.12.x  Sqlite 3.45.2  Adds math functions

DB_RETRY = 3
# Must have a short timeout when terminating.
# May want to have a longer timeout otherwise.
DB_TIMEOUT = 5
LONG_DB_TIMEOUT = 3600

# Approximate safety limit for the database file size.
BUFFER_SIZE = 40 * 1024 * 1024

# Default priority for trace data.
# Dispatch invocation where the juju event is not observed by the charm or any charm lib
# produces data at this priority.
DEFAULT_PRIORITY = 10

# Higher priority for data from dispatch where the juju event is observed.
OBSERVED_PRIORITY = 50


@dataclasses.dataclass
class Destination:
    """Tracing destination configuration."""

    url: str | None
    """The URL to send trace data to."""
    ca: str | None
    """CA list, a PEM bundle."""


def retry(f: Callable[P, R]) -> Callable[P, R]:
    """Retry a database operation N times."""

    @functools.wraps(f)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        exc: sqlite3.Error | None = None

        for _ in range(DB_RETRY):
            try:
                return f(*args, **kwargs)
            except sqlite3.Error as e:  # noqa: PERF203
                exc = e

        assert exc  # noqa: S101  # we'd have returned otherwise
        raise exc

    return wrapper


class Buffer:
    """Buffer for trace data.

    Access to the buffer attributes is effectively protected by an sqlite transaction.
    """

    path: pathlib.Path
    """Location of the buffer on disk."""
    ids: set[int]
    """Trace data ids buffered during this dispatch invocation."""
    observed = False
    """Marks that data from this dispatch invocation has been marked observed."""
    stored: int | None = None
    """Estimate of stored data size in bytes if known, or None if not yet known."""

    def __init__(self, path: pathlib.Path):
        self.path = path
        self.ids = set()
        self._set_db_schema()

    @retry
    def _set_db_schema(self) -> None:
        mode = stat.S_IRUSR | stat.S_IWUSR
        try:
            os.close(os.open(self.path, os.O_CREAT | os.O_EXCL, mode))
        except FileExistsError:
            if stat.S_IMODE(self.path.stat().st_mode) != mode:
                self.path.chmod(mode)

        with self.tx(timeout=LONG_DB_TIMEOUT) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tracing (
                    -- effectively auto-incremented
                    id INTEGER PRIMARY KEY,
                    -- observed events are more important
                    priority INTEGER NOT NULL,
                    -- a chunk of trace data
                    data BLOB NOT NULL,
                    -- MIME type for these data
                    mime TEXT NOT NULL
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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    -- setting key, like "url" and "ca"
                    key TEXT PRIMARY KEY,
                    -- the value, with None coerced to empty string
                    value TEXT NOT NULL
                )
                """
            )

    @contextlib.contextmanager
    def tx(self, *, timeout: float = DB_TIMEOUT, readonly: bool = False):
        """Thread-safe transaction context manager."""
        with sqlite3.connect(self.path, isolation_level=None, timeout=timeout) as conn:
            mode = 'DEFERRED' if readonly else 'IMMEDIATE'
            conn.execute(f'BEGIN {mode}')
            try:
                yield conn
            except:
                conn.execute('ROLLBACK')
                raise
            else:
                conn.execute('COMMIT')

    @retry
    def load_destination(self) -> Destination:
        """Get the tracing destination from the database."""
        with self.tx(readonly=True) as conn:
            settings = {k: v for k, v in conn.execute("""SELECT key, value FROM settings""")}
            return Destination(settings.get('url') or None, settings.get('ca') or None)

    @retry
    def save_destination(self, destination: Destination) -> None:
        """Update the tracing destination in the database."""
        with self.tx() as conn:
            conn.execute(
                """REPLACE INTO settings(key, value) VALUES ('url', ?), ('ca', ?)""",
                (destination.url or '', destination.ca or ''),
            )

    @retry
    def mark_observed(self) -> None:
        """Mark the trace data collected in this dispatch as higher priority."""
        if self.observed:
            return

        with self.tx(timeout=LONG_DB_TIMEOUT) as conn:
            conn.execute(
                f"""
                UPDATE tracing
                SET priority = ?
                WHERE id IN ({','.join(('?',) * len(self.ids))})
                """,  # noqa: S608
                (OBSERVED_PRIORITY, *tuple(self.ids)),
            )
        self.observed = True
        self.ids.clear()

    @retry
    def pushpop(self, record: tuple[bytes, str] | None = None) -> tuple[int, bytes, str] | None:
        """Push a message into the queue and return another.

        Accepts an optional new data chunk (data, mime type).
        Removes old, boring data if the queue would grow beyond the set limit.
        Returns the oldest important record (id, data, mime type).
        """
        data, mime = record if record else (None, None)
        stored_size = 0 if data is None else (len(data) + 4095) // 4096 * 4096
        collected_size = 0

        with self.tx(readonly=not data) as conn:
            if data:
                # Ensure that there's enough space in the buffer

                # TODO: expose `stored` in metrics, one day.
                if self.stored is None:
                    self.stored = self._stored_size(conn)
                excess = self.stored + stored_size - BUFFER_SIZE

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
                    for id_, size in cursor:
                        collected_ids.add(id_)
                        collected_size += size
                        if collected_size > excess:
                            break

                    collected_template = ','.join(['?'] * len(collected_ids))
                    conn.execute(
                        f"""
                        DELETE FROM tracing
                        WHERE id IN ({collected_template})
                        """,  # noqa: S608
                        tuple(collected_ids),
                    )

                # Store the new trace data.
                priority = OBSERVED_PRIORITY if self.observed else DEFAULT_PRIORITY
                cursor = conn.execute(
                    """
                    INSERT INTO tracing (priority, data, mime)
                    VALUES (?, ?, ?)
                    """,
                    (priority, data, mime),
                )

                assert cursor.lastrowid is not None  # noqa: S101  # Just inserted.
                if not self.observed:
                    self.ids.add(cursor.lastrowid)

            # Return the oldest important record, if any.
            rv = conn.execute(
                """
                SELECT id, data, mime
                FROM tracing
                ORDER BY priority DESC, id ASC
                LIMIT 1
                """
            ).fetchone()

        if self.stored is not None:
            self.stored += stored_size - collected_size

        return rv

    def _stored_size(self, conn: sqlite3.Connection) -> int:
        """Must be called in a transaction."""
        stored: int | None = conn.execute(
            """
            SELECT sum((length(data)+4095)/4096*4096)
            FROM tracing
            """
        ).fetchone()[0]
        return stored or 0

    @retry
    def remove(self, id_: int) -> None:
        """Remove a tracing record by id."""
        with self.tx() as conn:
            # The RETURNING clause would be ideal here, but it can't be used.
            # Sqlite shipped with Python 3.8 is too old.
            row = conn.execute(
                """
                SELECT (length(data)+4095)/4096*4096
                FROM tracing
                WHERE id = ?
                """,
                (id_,),
            ).fetchone()

            if not row:
                return

            conn.execute(
                """
                DELETE FROM tracing
                WHERE id = ?
                """,
                (id_,),
            )

        self.ids -= {id_}
        if self.stored is not None:
            self.stored -= row[0]
