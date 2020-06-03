# Copyright 2020 Canonical Ltd.
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

import base64
import binascii
from datetime import timedelta
import json
import pickle
import shutil
import subprocess
import sqlite3

import yaml


class NoSnapshotError(Exception):

    def __init__(self, handle_path):
        self.handle_path = handle_path

    def __str__(self):
        return 'no snapshot data found for {} object'.format(self.handle_path)


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

    def save_snapshot(self, handle_path, snapshot_data):
        # Use pickle for serialization, so the value remains portable.
        raw_data = pickle.dumps(snapshot_data)
        self._db.execute("REPLACE INTO snapshot VALUES (?, ?)", (handle_path, raw_data))

    def load_snapshot(self, handle_path):
        c = self._db.cursor()
        c.execute("SELECT data FROM snapshot WHERE handle=?", (handle_path,))
        row = c.fetchone()
        if row:
            pickled_data = row[0]
            return pickle.loads(pickled_data)
        raise NoSnapshotError(handle_path)

    def drop_snapshot(self, handle_path):
        self._db.execute("DELETE FROM snapshot WHERE handle=?", (handle_path,))

    def save_notice(self, event_path, observer_path, method_name):
        self._db.execute('INSERT INTO notice VALUES (NULL, ?, ?, ?)',
                         (event_path, observer_path, method_name))

    def drop_notice(self, event_path, observer_path, method_name):
        self._db.execute('''
            DELETE FROM notice
             WHERE event_path=?
               AND observer_path=?
               AND method_name=?
            ''', (event_path, observer_path, method_name))

    def notices(self, event_path):
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


class JujuStorage:
    """"Storing the content tracked by the Framework in Juju.

    This uses :class:`_JujuStorageBackend` to interact with state-get/state-set
    as the way to store state for the framework and for components.
    """

    def __init__(self, backend: '_JujuStorageBackend'):
        self._backend = backend

    def close(self):
        return

    def commit(self):
        return

    def save_snapshot(self, handle_path: str, snapshot_data: bytes) -> None:
        self._backend.set(handle_path, snapshot_data)

    def load_snapshot(self, handle_path):
        return self.load_key(handle_path)

    def drop_snapshot(self, handle_path):
        self.delete_key(handle_path)

    def save_notice(self, event_path, observer_path, method_name):
        notice_list = self.load_notice_list()
        notice_list.append([event_path, observer_path, method_name])
        self.store_notice_list(notice_list)

    def drop_notice(self, event_path, observer_path, method_name):
        notice_list = self.load_notice_list()
        notice_list.remove([event_path, observer_path, method_name])
        self.store_notice_list(notice_list)

    def notices(self, event_path):
        notice_list = self.load_notice_list()
        if event_path:
            notice_list = list(filter(lambda row: row[0] == event_path, notice_list))
        for row in notice_list:
            yield tuple(row)

    def load_notice_list(self):
        serialized_notices = self.load_key("#notices#")
        if serialized_notices is None:
            return []
        return pickle.loads(serialized_notices)

    def store_notice_list(self, notice_list):
        serialized_notices = pickle.dumps(notice_list)
        self.store_key("#notices#", serialized_notices)

    def load_key(self, key):
        # We could use yaml here but would need an external package
        encoded_val = json.loads(subprocess.check_output(["state-get", "--format", "json", key]))
        if not encoded_val:
            return None
        return base64.b64decode(encoded_val)

    def store_key(self, key, value):
        value = base64.b64encode(value)
        p = subprocess.Popen(["state-set", "--file", "-"],
                             stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT)
        p.communicate(input="{}: {}".format(key, value.decode('latin1')).encode())

    def delete_key(self, key):
        subprocess.check_output(["state-delete", key])


class _JujuStorageBackend:
    """Implements the interface from the Operator framework to Juju's state-get/set/etc."""

    @staticmethod
    def is_available() -> bool:
        """Check if Juju state storage is available.

        This checks if there is a 'state-get' executable in PATH.
        """
        p = shutil.which('state-get')
        return p is not None

    @staticmethod
    def set(key: str, value: bytes) -> None:
        """Set a key to a given bytes value.

        Args:
            key: The string key that will be used to find the value later
            value: Arbitrary bytes that will be returned by get().
        Raises:
            CalledProcessError: if 'state-set' returns an error code.
        """
        # encoded = base64.b64encode(value).decode('ascii')
        # content = yaml.dump({key: encoded}, encoding='utf-8')
        content = yaml.dump({key: value}, encoding='utf-8')
        # Note: 'capture_output' would be good here, but was added in Python 3.7
        p = subprocess.run(["state-set", "--file", "-"], input=content)
        p.check_returncode()

    @staticmethod
    def get(key: str) -> bytes:
        """Get the bytes value associated with a given key.

        Args:
            key: The string key that will be used to find the value
        Raises:
            CalledProcessError: if 'state-get' returns an error code.
        """
        # Note: 'capture_output' would be good here, but was added in Python 3.7
        p = subprocess.run(
            ["state-get", key],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        p.check_returncode()
        try:
            content = base64.b64decode(p.stdout)
        except binascii.Error as e:
            # TODO: translate non b64 content into a better error
            import pdb
            pdb.set_trace()
            raise
        return content

    @staticmethod
    def delete(key: str) -> None:
        """Remove a key from being tracked.

        Args:
            key: The key to stop storing
        Raises:
            CalledProcessError: if 'state-delete' returns an error code.
        """
        p = subprocess.run(["state-delete", key])
        p.check_returncode()
