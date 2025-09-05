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


def test_slug_valid():
    tinyproxy.check_slug("example")  # No error raised.


# Define a reusable fixture that provides invalid slugs.
@pytest.fixture(params=["", "foo_bar", "foo/bar"])
def invalid_slug(request):
    return request.param


def test_slug_invalid(invalid_slug: str):
    with pytest.raises(ValueError):
        tinyproxy.check_slug(invalid_slug)
