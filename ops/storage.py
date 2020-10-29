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

"""Structures to offer storage to the charm (through Juju or locally)."""

from datetime import timedelta
import pickle
import shutil
import subprocess
import sqlite3
import typing

import yaml


def _run(args, **kw):
    cmd = shutil.which(args[0])
    if cmd is None:
        raise FileNotFoundError(args[0])
    return subprocess.run([cmd, *args[1:]], **kw)


class SQLiteStorage:
    """Storage using SQLite backend."""

    DB_LOCK_TIMEOUT = timedelta(hours=1)

    def __init__(self, filename):
        # The isolation_level argument is set to None such that the implicit
        # transaction management behavior of the sqlite3 module is disabled.
        self._db = sqlite3.connect(str(filename),
                                   isolation_level=None,
                                   timeout=self.DB_LOCK_TIMEOUT.total_seconds())
        self._setup()

    def _setup(self):
        """Make the database ready to be used as storage."""
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
        """Part of the Storage API, close the storage backend."""
        self._db.close()

    def commit(self):
        """Part of the Storage API, commit latest changes in the storage backend."""
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
        """Part of the Storage API, record an notice (event and observer)."""
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

    def notices(self, event_path: str = None) ->\
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


class JujuStorage:
    """Storing the content tracked by the Framework in Juju.

    This uses :class:`_JujuStorageBackend` to interact with state-get/state-set
    as the way to store state for the framework and for components.
    """

    NOTICE_KEY = "#notices#"

    def __init__(self, backend: '_JujuStorageBackend' = None):
        self._backend = backend
        if backend is None:
            self._backend = _JujuStorageBackend()

    def close(self):
        """Part of the Storage API, close the storage backend.

        Nothing to be done for Juju backend, as it's transactional.
        """

    def commit(self):
        """Part of the Storage API, commit latest changes in the storage backend.

        Nothing to be done for Juju backend, as it's transactional.
        """

    def save_snapshot(self, handle_path: str, snapshot_data: typing.Any) -> None:
        """Part of the Storage API, persist a snapshot data under the given handle.

        Args:
            handle_path: The string identifying the snapshot.
            snapshot_data: The data to be persisted. (as returned by Object.snapshot()). This
                might be a dict/tuple/int, but must only contain 'simple' python types.
        """
        self._backend.set(handle_path, snapshot_data)

    def load_snapshot(self, handle_path):
        """Part of the Storage API, retrieve a snapshot that was previously saved.

        Args:
            handle_path: The string identifying the snapshot.

        Raises:
            NoSnapshotError: if there is no snapshot for the given handle_path.
        """
        try:
            content = self._backend.get(handle_path)
        except KeyError:
            raise NoSnapshotError(handle_path)
        return content

    def drop_snapshot(self, handle_path):
        """Part of the Storage API, remove a snapshot that was previously saved.

        Dropping a snapshot that doesn't exist is treated as a no-op.
        """
        self._backend.delete(handle_path)

    def save_notice(self, event_path: str, observer_path: str, method_name: str):
        """Part of the Storage API, record an notice (event and observer)."""
        notice_list = self._load_notice_list()
        notice_list.append([event_path, observer_path, method_name])
        self._save_notice_list(notice_list)

    def drop_notice(self, event_path: str, observer_path: str, method_name: str):
        """Part of the Storage API, remove a notice that was previously recorded."""
        notice_list = self._load_notice_list()
        notice_list.remove([event_path, observer_path, method_name])
        self._save_notice_list(notice_list)

    def notices(self, event_path: str = None):
        """Part of the Storage API, return all notices that begin with event_path.

        Args:
            event_path: If supplied, will only yield events that match event_path. If not
                supplied (or None/'') will return all events.

        Returns:
            Iterable of (event_path, observer_path, method_name) tuples
        """
        notice_list = self._load_notice_list()
        for row in notice_list:
            if event_path and row[0] != event_path:
                continue
            yield tuple(row)

    def _load_notice_list(self) -> typing.List[typing.Tuple[str]]:
        """Load a notice list from current key.

        Returns:
            List of (event_path, observer_path, method_name) tuples; empty if no key or is None.
        """
        try:
            notice_list = self._backend.get(self.NOTICE_KEY)
        except KeyError:
            return []
        if notice_list is None:
            return []
        return notice_list

    def _save_notice_list(self, notices: typing.List[typing.Tuple[str]]) -> None:
        """Save a notice list under current key.

        Args:
            notices: List of (event_path, observer_path, method_name) tuples.
        """
        self._backend.set(self.NOTICE_KEY, notices)


class _SimpleLoader(getattr(yaml, 'CSafeLoader', yaml.SafeLoader)):
    """Handle a couple basic python types.

    yaml.SafeLoader can handle all the basic int/float/dict/set/etc that we want. The only one
    that it *doesn't* handle is tuples. We don't want to support arbitrary types, so we just
    subclass SafeLoader and add tuples back in.
    """
    # Taken from the example at:
    # https://stackoverflow.com/questions/9169025/how-can-i-add-a-python-tuple-to-a-yaml-file-using-pyyaml

    construct_python_tuple = yaml.Loader.construct_python_tuple


_SimpleLoader.add_constructor(
    u'tag:yaml.org,2002:python/tuple',
    _SimpleLoader.construct_python_tuple)


class _SimpleDumper(getattr(yaml, 'CSafeDumper', yaml.SafeDumper)):
    """Add types supported by 'marshal'.

    YAML can support arbitrary types, but that is generally considered unsafe (like pickle). So
    we want to only support dumping out types that are safe to load.
    """


_SimpleDumper.represent_tuple = yaml.Dumper.represent_tuple
_SimpleDumper.add_representer(tuple, _SimpleDumper.represent_tuple)


def juju_backend_available() -> bool:
    """Check if Juju state storage is available."""
    p = shutil.which('state-get')
    return p is not None


class _JujuStorageBackend:
    """Implements the interface from the Operator framework to Juju's state-get/set/etc."""

    def set(self, key: str, value: typing.Any) -> None:
        """Set a key to a given value.

        Args:
            key: The string key that will be used to find the value later
            value: Arbitrary content that will be returned by get().

        Raises:
            CalledProcessError: if 'state-set' returns an error code.
        """
        # default_flow_style=None means that it can use Block for
        # complex types (types that have nested types) but use flow
        # for simple types (like an array). Not all versions of PyYAML
        # have the same default style.
        encoded_value = yaml.dump(value, Dumper=_SimpleDumper, default_flow_style=None)
        content = yaml.dump(
            {key: encoded_value}, encoding='utf8', default_style='|',
            default_flow_style=False,
            Dumper=_SimpleDumper)
        _run(["state-set", "--file", "-"], input=content, check=True)

    def get(self, key: str) -> typing.Any:
        """Get the bytes value associated with a given key.

        Args:
            key: The string key that will be used to find the value
        Raises:
            CalledProcessError: if 'state-get' returns an error code.
        """
        # We don't capture stderr here so it can end up in debug logs.
        p = _run(["state-get", key], stdout=subprocess.PIPE, check=True, universal_newlines=True)
        if p.stdout == '' or p.stdout == '\n':
            raise KeyError(key)
        return yaml.load(p.stdout, Loader=_SimpleLoader)

    def delete(self, key: str) -> None:
        """Remove a key from being tracked.

        Args:
            key: The key to stop storing
        Raises:
            CalledProcessError: if 'state-delete' returns an error code.
        """
        _run(["state-delete", key], check=True)


class NoSnapshotError(Exception):
    """Exception to flag that there is no snapshot for the given handle_path."""

    def __init__(self, handle_path):
        self.handle_path = handle_path

    def __str__(self):
        return 'no snapshot data found for {} object'.format(self.handle_path)
