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

import contextlib
import logging
import pathlib
import sqlite3

import pytest

from ops_tracing import _buffer
from ops_tracing._buffer import DEFAULT_PRIORITY, OBSERVED_PRIORITY, Buffer  # type: ignore


def setup_buffer_with_data(path: pathlib.Path, ids: list[int]) -> Buffer:
    buf = Buffer(path)
    buf.observed = False

    with buf.tx() as conn:
        for i in ids:
            conn.execute(
                'INSERT INTO tracing(id, priority, data, mime) VALUES (?, ?, ?, ?)',
                (i, 0, b'data', 'application/octet-stream'),
            )
            buf.ids.add(i)
    return buf


def test_mark_observed(tmp_path: pathlib.Path):
    buf = setup_buffer_with_data(tmp_path / 'db', [1, 2, 3])

    buf.mark_observed()

    with buf.tx(readonly=True) as conn:
        ids: set[int] = set()
        for row in conn.execute('SELECT id, priority FROM tracing'):
            assert row[1] == OBSERVED_PRIORITY
            ids.add(row[0])
        assert ids == {1, 2, 3}
        assert buf.observed is True
        assert not buf.ids


def test_mark_observed_no_ids(tmp_path: pathlib.Path):
    buf = setup_buffer_with_data(tmp_path / 'db', [])

    buf.mark_observed()

    assert buf.observed
    assert not buf.ids

    with buf.tx(readonly=True) as conn:
        assert not list(conn.execute('SELECT id FROM tracing'))


def test_mark_observed_missing_ids(tmp_path: pathlib.Path):
    buf = setup_buffer_with_data(tmp_path / 'db', [1, 2])
    buf.ids.add(99)  # does not exist, will be ignored

    buf.mark_observed()

    with buf.tx(readonly=True) as conn:
        priorities = {row[0]: row[1] for row in conn.execute('SELECT id, priority FROM tracing')}
        assert priorities == {1: OBSERVED_PRIORITY, 2: OBSERVED_PRIORITY}
        assert buf.observed is True
        assert not buf.ids


def test_eviction_frees_only_what_is_needed(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(_buffer, 'BUFFER_SIZE', 3 * 4096)
    buf = Buffer(tmp_path / 'db')
    mime = 'application/octet-stream'

    # Fill the buffer with three observed (high priority) one-page chunks.
    buf.observed = True
    for _ in range(3):
        buf.pushpop((b'x', mime))

    # One more page is needed, so exactly one chunk must go, oldest first.
    buf.observed = False
    buf.pushpop((b'new', mime))

    with buf.tx(readonly=True) as conn:
        rows = list(conn.execute('SELECT id, priority FROM tracing ORDER BY id'))
    assert rows == [(2, OBSERVED_PRIORITY), (3, OBSERVED_PRIORITY), (4, DEFAULT_PRIORITY)]
    assert buf.stored == 3 * 4096


def test_unreadable_buffer_is_recreated(tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture):
    path = tmp_path / 'db'
    path.write_bytes(b'this is not an sqlite database\n' * 100)

    with caplog.at_level(logging.WARNING, logger='ops_tracing._buffer'):
        buf = Buffer(path)

    assert buf.pushpop() is None
    assert 'Discarding the unreadable trace buffer' in caplog.text


def test_locked_buffer_is_not_discarded(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / 'db'
    Buffer(path).pushpop((b'data', 'application/octet-stream'))
    monkeypatch.setattr(_buffer, 'LONG_DB_TIMEOUT', 0.01)

    with contextlib.closing(sqlite3.connect(path, isolation_level=None)) as conn:
        conn.execute('BEGIN EXCLUSIVE')
        with pytest.raises(sqlite3.OperationalError):
            Buffer(path)
        conn.execute('ROLLBACK')

    assert Buffer(path).pushpop() is not None
