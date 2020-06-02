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
import json
import pickle
import subprocess
import sqlite3
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

    def save_snapshot(self, handle_path, snapshot_data):
        self._db.execute("REPLACE INTO snapshot VALUES (?, ?)", (handle_path, snapshot_data))

    def load_snapshot(self, handle_path):
        c = self._db.cursor()
        c.execute("SELECT data FROM snapshot WHERE handle=?", (handle_path,))
        row = c.fetchone()
        if row:
            return row[0]
        return None

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

    def __init__(self):
        subprocess.call("juju-log 'using server-side storage provider'", shell=True)

    def close(self):
        return

    def commit(self):
        return

    def save_snapshot(self, handle_path, snapshot_data):
        self.store_key(handle_path, snapshot_data)

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
