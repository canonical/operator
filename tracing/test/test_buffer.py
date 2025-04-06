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

import pathlib

from ops_tracing._buffer import OBSERVED_PRIORITY, Buffer  # type: ignore


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
