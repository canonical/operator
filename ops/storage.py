# Copyright 2019-2020 Canonical Ltd.
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

import pickle
import sqlite3
import typing
from datetime import timedelta


class SQLiteStorage:

    DB_LOCK_TIMEOUT = timedelta(hours=1)

    def __init__(self, filename):
        # The isolation_level argument is set to None such that the implicit
        # transaction management behavior of the sqlite3 module is disabled.
        self._db = sqlite3.connect(str(filename),
                                   isolation_level=None,
                                   timeout=self.DB_LOCK_TIMEOUT.total_seconds())
        self._setup()

    def _setup(self):
        # Make sure that the database is locked until the connection is closed,
        # not until the transaction ends.
        self._db.execute("PRAGMA locking_mode=EXCLUSIVE")
        c = self._db.execute("BEGIN")
        c.execute("SELECT count(name) FROM sqlite_master WHERE type='table' AND name='snapshot'")
        if c.fetchone()[0] == 0:
            # Keep in mind what might happen if the process dies somewhere below.
            # The system must not be rendered permanently broken by that.
            self._db.execute("CREATE TABLE snapshot (handle TEXT PRIMARY KEY, data BLOB)")
            self._db.execute('''
                CREATE TABLE notice (
                  sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                  event_path TEXT,
                  observer_path TEXT,
                  method_name TEXT)
                ''')
            self._db.commit()

    def close(self):
        self._db.close()

    def commit(self):
        self._db.commit()

    # There's commit but no rollback. For abort to be supported, we'll need logic that
    # can rollback decisions made by third-party code in terms of the internal state
    # of objects that have been snapshotted, and hooks to let them know about it and
    # take the needed actions to undo their logic until the last snapshot.
    # This is doable but will increase significantly the chances for mistakes.

    def save_snapshot(self, handle_path: str, snapshot_data: typing.Any) -> None:
        """Part of the Storage API, persist a snapshot data under the given handle.

        Args:
            handle_path: The string identifying the snapshot.
            snapshot_data: The data to be persisted. (as returned by Object.snapshot()). This
            might be a dict/tuple/int, but must only contain 'simple' python types.
        """
        # Use pickle for serialization, so the value remains portable.
        raw_data = pickle.dumps(snapshot_data)
        self._db.execute("REPLACE INTO snapshot VALUES (?, ?)", (handle_path, raw_data))

    def load_snapshot(self, handle_path: str) -> typing.Any:
        """Part of the Storage API, retrieve a snapshot that was previously saved.

        Args:
            handle_path: The string identifying the snapshot.
        Raises:
            NoSnapshotError: if there is no snapshot for the given handle_path.
        """
        c = self._db.cursor()
        c.execute("SELECT data FROM snapshot WHERE handle=?", (handle_path,))
        row = c.fetchone()
        if row:
            return pickle.loads(row[0])
        raise NoSnapshotError(handle_path)

    def drop_snapshot(self, handle_path: str):
        """Part of the Storage API, remove a snapshot that was previously saved.

        Dropping a snapshot that doesn't exist is treated as a no-op.
        """
        self._db.execute("DELETE FROM snapshot WHERE handle=?", (handle_path,))

    def list_snapshots(self) -> typing.Generator[str, None, None]:
        """Return the name of all snapshots that are currently saved."""
        c = self._db.cursor()
        c.execute("SELECT handle FROM snapshot")
        while True:
            rows = c.fetchmany()
            if not rows:
                break
            for row in rows:
                yield row[0]

    def save_notice(self, event_path: str, observer_path: str, method_name: str) -> None:
        """Part of the Storage API, record an notice (event and observer)"""
        self._db.execute('INSERT INTO notice VALUES (NULL, ?, ?, ?)',
                         (event_path, observer_path, method_name))

    def drop_notice(self, event_path: str, observer_path: str, method_name: str) -> None:
        """Part of the Storage API, remove a notice that was previously recorded."""
        self._db.execute('''
            DELETE FROM notice
             WHERE event_path=?
               AND observer_path=?
               AND method_name=?
            ''', (event_path, observer_path, method_name))

    def notices(self, event_path: typing.Optional[str]) ->\
            typing.Generator[typing.Tuple[str, str, str], None, None]:
        """Part of the Storage API, return all notices that begin with event_path.

        Args:
            event_path: If supplied, will only yield events that match event_path. If not
                supplied (or None/'') will return all events.
        Returns:
            Iterable of (event_path, observer_path, method_name) tuples
        """
        if event_path:
            c = self._db.execute('''
                SELECT event_path, observer_path, method_name
                  FROM notice
                 WHERE event_path=?
                 ORDER BY sequence
                ''', (event_path,))
        else:
            c = self._db.execute('''
                SELECT event_path, observer_path, method_name
                  FROM notice
                 ORDER BY sequence
                ''')
        while True:
            rows = c.fetchmany()
            if not rows:
                break
            for row in rows:
                yield tuple(row)


class NoSnapshotError(Exception):

    def __init__(self, handle_path):
        self.handle_path = handle_path

    def __str__(self):
        return 'no snapshot data found for {} object'.format(self.handle_path)
