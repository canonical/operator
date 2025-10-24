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

import pytest

from charm import tinyproxy


class MockVersionProcess:
    """Mock object that represents the result of calling 'tinyproxy -v'."""

    def __init__(self, version: str):
        self.stdout = f"tinyproxy {version}"


def test_version(monkeypatch: pytest.MonkeyPatch):
    """Test that the helper module correctly returns the version of tinyproxy."""
    version_process = MockVersionProcess("1.0.0")
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: version_process)
    assert tinyproxy.get_version() == "1.0.0"
