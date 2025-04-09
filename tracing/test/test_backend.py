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

import pytest

import ops_tracing
from ops_tracing import _backend
from ops_tracing._buffer import Config


def test_unset_destination(setup_tracing: None):
    exporter = _backend.get_exporter()
    assert exporter
    ops_tracing.set_destination(None, None)
    assert exporter.buffer.get_destination() == Config(None, None)


def test_set_destination(setup_tracing: None):
    exporter = _backend.get_exporter()
    assert exporter
    ops_tracing.set_destination('http://a.com', None)
    assert exporter.buffer.get_destination() == Config('http://a.com', None)


def test_set_destination_again(setup_tracing: None):
    exporter = _backend.get_exporter()
    assert exporter
    ops_tracing.set_destination('http://a.com', None)
    ops_tracing.set_destination('http://a.com', None)
    # maybe check that the database was written only once?


@pytest.mark.parametrize('url', ['file:///etc/passwd', 'gopher://aaa'])
def test_set_destination_invalid_url(setup_tracing: None, url: str):
    exporter = _backend.get_exporter()
    assert exporter
    with pytest.raises(ValueError):
        ops_tracing.set_destination(url, None)
